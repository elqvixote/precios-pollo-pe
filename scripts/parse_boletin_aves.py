#!/usr/bin/env python3
"""
Parser del Boletín Diario de Aves (MIDAGRI / SISAP).
Uso:  python parse_boletin_aves.py boletin1.pdf [boletin2.pdf ...] --out salida/

Genera (long/tidy, listo para Power Query o una base):
  diario.csv   -> fecha_boletin, region, serie, unidad, metrica, fecha_dato, valor
                  metrica: valor | prom_7d | var_pct
  mensual.csv  -> fecha_boletin, region, anio, mes, oferta_t, precio_kg
  ingreso.csv  -> fecha_boletin, region, fecha_dato, oferta_t   (serie de 31 días del gráfico)

Las columnas se asignan por posición X bajo el encabezado, no por orden,
porque el boletín a veces omite columnas (ej. Arequipa o pescado sin dato del día).
"""
import re, sys, argparse, logging
from datetime import date, timedelta
from pathlib import Path
import pdfplumber
import pandas as pd

logging.getLogger("pdfminer").setLevel(logging.ERROR)

MESES = {"ene":1,"enero":1,"feb":2,"febrero":2,"mar":3,"marzo":3,"abr":4,"abril":4,
         "may":5,"mayo":5,"jun":6,"junio":6,"jul":7,"julio":7,"ago":8,"agosto":8,
         "sep":9,"set":9,"septiembre":9,"setiembre":9,"oct":10,"octubre":10,
         "nov":11,"noviembre":11,"dic":12,"diciembre":12}
DIAS = {"lun","mar","mié","mie","jue","vie","sáb","sab","dom"}
NUM = re.compile(r"^-?[\d,]+(\.\d+)?%?$")

# serie -> (región, etiqueta en el PDF, unidad)
FILAS = {
    "Granja":            ("Lima", "pollo_vivo_granja", "S/ por kg"),
    "Mayorista":         ("Lima", "pollo_vivo_mayorista", "S/ por kg"),
    "Consumidor":        ("Lima", "pollo_eviscerado_consumidor", "S/ por kg"),
    "Peso":              ("Lima", "peso_promedio_pollo_vivo", "kg por unidad"),
    "De postura":        ("Lima", "gallina_colorada", "S/ por kg"),
    "Reproductora":      ("Lima", "gallina_reproductora", "S/ por kg"),
    "Huevo":             ("Lima", "huevo_rosado", "S/ por kg"),
    "Jurel":             ("Lima", "jurel", "S/ por kg"),
    "Bonito":            ("Lima", "bonito", "S/ por kg"),
    "Al mayorista":      ("Arequipa", "pollo_vivo_mayorista", "S/ por kg"),
    "Oferta (t)":        ("Arequipa", "oferta_pollo_vivo", "t"),
}


def to_num(s):
    s = s.replace(",", "").replace("%", "")
    return float(s)


def lines_of(words, tol=3.5):
    """Agrupa palabras en líneas por coordenada vertical con tolerancia."""
    out = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if out and abs(out[-1]["top"] - w["top"]) <= tol:
            out[-1]["words"].append(w)
        else:
            out.append({"top": w["top"], "words": [w]})
    for l in out:
        l["words"].sort(key=lambda w: w["x0"])
        l["text"] = " ".join(w["text"] for w in l["words"])
    return out


def fecha_boletin(pdf):
    t = pdf.pages[0].extract_text() or ""
    m = re.search(r"(\d{1,2}) de (\w+) del? (\d{4})", t)
    if not m:
        raise ValueError("No se encontró la fecha del boletín")
    return date(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1)))


def resolver_dia(dia, fb):
    """'15' -> date usando el mes del boletín (o el anterior si el día es mayor)."""
    d = int(dia)
    if d <= fb.day:
        return fb.replace(day=d)
    prev = fb.replace(day=1) - timedelta(days=1)
    return prev.replace(day=d)


def columnas_de_header(line, fb):
    """Devuelve lista de (x_centro, metrica, fecha) desde una línea de encabezado."""
    cols, ws = [], line["words"]
    # Lima usa "(Prom. Últ. 7 días)"; Arequipa solo "Precio promedio". "(Prom." manda si existe.
    marca = "(Prom." if any(w["text"] == "(Prom." for w in ws) else "promedio"
    for i, w in enumerate(ws):
        t = w["text"]
        if t == marca and not any(c[1] == "prom_7d" for c in cols):
            cols.append((w["x0"] + 20, "prom_7d", None))
        elif t.lower() in DIAS and i + 1 < len(ws) and ws[i + 1]["text"].isdigit():
            cols.append(((w["x0"] + ws[i + 1]["x1"]) / 2, "valor", resolver_dia(ws[i + 1]["text"], fb)))
        elif t == "Var.":
            cols.append((w["x0"] + 8, "var_pct", None))
    return cols


def serie_de_linea(text):
    for k in FILAS:
        if text.startswith(k):
            return k
    return None


def parse_tablas_diarias(page, fb, region_hint):
    rows = []
    lines = lines_of(page.extract_words())
    cols = None
    pendiente = None  # etiqueta sin números (ej. "De postura (colorada)" con valores en otra línea)
    for ln in lines:
        txt = ln["text"]
        es_header = ("Var." in txt or "(Prom." in txt) and any(w["text"].lower() in DIAS for w in ln["words"])
        if es_header:
            cols = columnas_de_header(ln, fb)
            continue
        if cols is None:
            continue
        izq = [w for w in ln["words"] if w["x0"] < 200]
        nums = [w for w in ln["words"] if w["x0"] >= 150 and NUM.match(w["text"])]
        etiqueta = serie_de_linea(" ".join(w["text"] for w in izq)) if izq else None
        # Regla especial: Arequipa "Oferta (t)" vs tabla mensual "Oferta (t) Precio..."
        if etiqueta == "Oferta (t)" and ("Precio" in txt or region_hint != "Arequipa"):
            etiqueta = None
        if etiqueta and not nums:
            pendiente = etiqueta
            continue
        if not etiqueta and nums and pendiente and not izq:
            etiqueta = pendiente
        if not etiqueta or not nums:
            continue
        pendiente = None
        if etiqueta in ("Jurel", "Bonito", "Al mayorista", "Oferta (t)") and region_hint == "Lima":
            continue
        region, serie, unidad = FILAS[etiqueta]
        if etiqueta in ("Jurel", "Bonito"):
            region = "Lima"
        for w in nums:
            xc = (w["x0"] + w["x1"]) / 2
            c = min(cols, key=lambda c: abs(c[0] - xc))
            if abs(c[0] - xc) > 45:
                continue
            rows.append(dict(fecha_boletin=fb, region=region, serie=serie, unidad=unidad,
                             metrica=c[1], fecha_dato=c[2] or fb, valor=to_num(w["text"])))
    return rows


def parse_mensual(page, fb, region):
    rows = []
    for ln in lines_of(page.extract_words()):
        ws = [w for w in ln["words"] if w["x0"] < 300]
        if not ws or ws[0]["text"].lower() not in MESES or ws[0]["x0"] > 40:
            continue
        vals = [w for w in ws[1:] if NUM.match(w["text"])]
        if not vals:
            continue
        mes = MESES[ws[0]["text"].lower()]
        # columnas: oferta 2025, oferta 2026, var, precio 2025, precio 2026, var
        xs = {"of_prev": 80, "of_act": 112, "pr_prev": 205, "pr_act": 236}
        d = {}
        for w in vals:
            if w["text"].endswith("%"):
                continue
            xc = w["x0"]
            k = min(xs, key=lambda k: abs(xs[k] - xc))
            if abs(xs[k] - xc) < 20:
                d[k] = to_num(w["text"])
        for anio, of, pr in ((fb.year - 1, "of_prev", "pr_prev"), (fb.year, "of_act", "pr_act")):
            if of in d or pr in d:
                rows.append(dict(fecha_boletin=fb, region=region, anio=anio, mes=mes,
                                 oferta_t=d.get(of), precio_kg=d.get(pr)))
    return rows


def parse_ingreso_lima(page, fb):
    """Etiquetas del gráfico de barras: texto duplicado '22,,117777' -> '2,177'."""
    vals = []
    for w in page.extract_words():
        t = w["text"]
        if re.fullmatch(r"(\d\d)+,,(\d\d)+", t):
            vals.append((w["x0"], to_num(t[::2])))
    vals.sort()
    n = len(vals)
    if n == 0:
        return []
    return [dict(fecha_boletin=fb, region="Lima", fecha_dato=fb - timedelta(days=n - 1 - i), oferta_t=v)
            for i, (_, v) in enumerate(vals)]


def kpis_portada(pdf):
    t = pdf.pages[0].extract_text() or ""
    m = re.search(r"S/\s*([\d.]+)\s+([\d,]+\.?\d*)\s*t", t)
    return (float(m.group(1)), to_num(m.group(2))) if m else (None, None)


def validar(D, I, kpis):
    """Devuelve lista de alertas. Vacía = boletín consistente."""
    alertas = []
    d = pd.DataFrame(D); i = pd.DataFrame(I)
    for fb, (precio, oferta) in kpis.items():
        x = d[(d.fecha_boletin == fb) & (d.region == "Lima") & (d.serie == "pollo_vivo_mayorista")
              & (d.metrica == "valor") & (d.fecha_dato == fb)]
        if x.empty or abs(x.valor.iloc[0] - precio) > 0.005:
            alertas.append(f"{fb}: precio mayorista portada {precio} != tabla {x.valor.tolist()}")
        y = i[(i.fecha_boletin == fb) & (i.fecha_dato == fb)]
        if y.empty or abs(y.oferta_t.iloc[0] - oferta) > 1:
            alertas.append(f"{fb}: oferta portada {oferta} != gráfico {y.oferta_t.tolist()}")
    # El mismo (serie, fecha_dato) reportado en dos boletines debe coincidir
    v = d[d.metrica == "valor"].groupby(["region", "serie", "fecha_dato"]).valor.agg(["nunique", "unique"])
    for k, r in v[v["nunique"] > 1].iterrows():
        alertas.append(f"Revisión entre boletines {k}: {list(r['unique'])}")
    w = i.groupby("fecha_dato").oferta_t.agg(["nunique", "unique"])
    for k, r in w[w["nunique"] > 1].iterrows():
        alertas.append(f"Revisión de ingreso {k}: {list(r['unique'])}")
    return alertas


# ======================================================================
# Familia "Excel" (2020 -> 18-08-2026): una hoja de Excel exportada a PDF.
# Las filas traen etiqueta + 4 tokens: prom_7d, día anterior, día, var%.
# Un "-" significa sin dato y se respeta la posición.
# ======================================================================
TOK = r"(-?\d+\.\d+%?|-)"  # número primero: si no, "-0.2%" se lee como "-"
FILAS_EXCEL = [
    (r"(?:Granja \(pollo vivo\)|Precio en granja \(S/ x kg\))", "pollo_vivo_granja", "S/ por kg"),
    (r"(?:Centros de Distribuci[oó]n \(pollo vivo\)|Precio en Centros de (?:Acopio|Distribuci[oó]n) \(S/ x kg\))",
     "pollo_vivo_mayorista", "S/ por kg"),
    (r"(?:Mercados Minoristas \(pollo eviscerado\)|Precio en Mercados Minoristas \(S/ x kg\))",
     "pollo_eviscerado_consumidor", "S/ por kg"),
    (r"Peso promedio por pollo \(kg x unid\.\)", "peso_promedio_pollo_vivo", "kg por unidad"),
    (r"Gallina colorada", "gallina_colorada", "S/ por kg"),
    (r"Gallina reproductora:?", "gallina_reproductora", "S/ por kg"),
    (r"Huevo rosado", "huevo_rosado", "S/ por kg"),
]
MES_LARGO = r"(Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Setiembre|Septiembre|Octubre|Noviembre|Diciembre|" \
            r"Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Set|Sep|Oct|Nov|Dic)"
VOL = r"(\d{1,3}(?:,\d{3})+)"


def es_excel(pdf):
    return "excel" in (pdf.metadata.get("Creator") or "").lower()


def parse_excel(pdf, fb):
    t = pdf.pages[0].extract_text() or ""
    diario = []
    h = re.search(r"Promedio\s+\w{3}-(\d{2})\s+\w{3}-(\d{2})", t)
    if not h:
        raise ValueError("Excel: no se encontró el encabezado de fechas")
    d_ant, d_hoy = resolver_dia(h.group(1), fb), resolver_dia(h.group(2), fb)
    if d_hoy != fb:
        raise ValueError(f"Excel: encabezado {d_hoy} no coincide con boletín {fb}")
    for patron, serie, unidad in FILAS_EXCEL:
        m = re.search(patron + r"\s+(?:[ab]\s+)?" + r"\s+".join([TOK] * 4), t)
        if not m:
            continue
        for metrica, fecha, tok in (("prom_7d", fb, m.group(1)), ("valor", d_ant, m.group(2)),
                                    ("valor", d_hoy, m.group(3)), ("var_pct", fb, m.group(4))):
            if tok == "-":
                continue
            diario.append(dict(fecha_boletin=fb, region="Lima", serie=serie, unidad=unidad,
                               metrica=metrica, fecha_dato=fecha, valor=to_num(tok)))
    mensual = []
    for linea in t.splitlines():
        for m in re.finditer(MES_LARGO + r"\s+(?:1\s+)?" + VOL + r"\s+(?:" + VOL + r"\s+-?[\d.]+%\s+)?(\d+\.\d+)"
                             r"(?:\s+(\d+\.\d+)\s+-?[\d.]+%)?", linea):
            mes = MESES[m.group(1).lower()]
            mensual.append(dict(fecha_boletin=fb, region="Lima", anio=fb.year - 1, mes=mes,
                                oferta_t=to_num(m.group(2)), precio_kg=float(m.group(4))))
            if m.group(3):
                mensual.append(dict(fecha_boletin=fb, region="Lima", anio=fb.year, mes=mes,
                                    oferta_t=to_num(m.group(3)),
                                    precio_kg=float(m.group(5)) if m.group(5) else None))
    k = re.search(r"vendi[oó]\s*(?:a|en)\s*S/\s*(\d+\.\d+)", t.replace(" ", ""))
    kpi = (float(k.group(1)) if k else None, None)  # la familia Excel no trae oferta diaria confiable
    return kpi, diario, mensual, []


def parse_pdf(path):
    with pdfplumber.open(path) as pdf:
        fb = fecha_boletin(pdf)
        if es_excel(pdf):
            kpi, diario, mensual, ingreso = parse_excel(pdf, fb)
            return fb, kpi, diario, mensual, ingreso
        kpi = kpis_portada(pdf)
        p_lima, p_aqp = pdf.pages[1], pdf.pages[2]
        diario = parse_tablas_diarias(p_lima, fb, "Lima") + parse_tablas_diarias(p_aqp, fb, "Arequipa")
        mensual = parse_mensual(p_lima, fb, "Lima") + parse_mensual(p_aqp, fb, "Arequipa")
        ingreso = parse_ingreso_lima(p_lima, fb)
    return fb, kpi, diario, mensual, ingreso


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--out", default="salida")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    D, M, I, K = [], [], [], {}
    for p in a.pdfs:
        fb, kpi, d, m, i = parse_pdf(p)
        K[fb] = kpi
        print(f"{Path(p).name}: boletín {fb} -> {len(d)} diarios, {len(m)} mensuales, {len(i)} días de ingreso")
        D += d; M += m; I += i
    pd.DataFrame(D).to_csv(out / "diario.csv", index=False)
    pd.DataFrame(M).to_csv(out / "mensual.csv", index=False)
    pd.DataFrame(I).to_csv(out / "ingreso.csv", index=False)
    alertas = validar(D, I, K)
    print("\nVALIDACIÓN:", "OK" if not alertas else f"{len(alertas)} alertas")
    for x in alertas:
        print("  -", x)


if __name__ == "__main__":
    main()
