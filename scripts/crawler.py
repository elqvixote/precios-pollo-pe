#!/usr/bin/env python3
"""
Crawler + pipeline del Boletín Diario de Aves (MIDAGRI).

1. Lee la colección oficial de gob.pe y obtiene las páginas mensuales.
2. En cada página mensual encuentra los PDFs diarios.
3. Descarga solo los que no están en data/manifest.csv, los parsea y valida.
4. Acumula en data/*.csv. Los PDFs que fallan quedan en estado 'cuarentena'.

Uso:
  python scripts/crawler.py --desde 2026-01-01            # backfill 2026
  python scripts/crawler.py --ultimos-meses 2             # corrida diaria
"""
import argparse, csv, re, sys, tempfile, time, traceback
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from parse_boletin_aves import parse_pdf  # noqa: E402

BASE = "https://www.gob.pe"
COLECCION = BASE + "/institucion/midagri/colecciones/4-boletin-diario-de-comercializacion-y-precio-de-aves"
HOJAS_COLECCION = 6  # se detiene antes si una hoja viene vacía
DATA = Path(__file__).resolve().parent.parent / "data"
MANIFEST = DATA / "manifest.csv"
CAMPOS_MANIFEST = ["fecha", "pub_id", "url", "estado", "detalle", "procesado_utc"]

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}

S = requests.Session()
S.headers["User-Agent"] = "precios-pollo-pe/0.1 (+https://github.com/elqvixote/precios-pollo-pe)"


def get(url, **kw):
    for intento in range(3):
        try:
            r = S.get(url, timeout=60, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if intento == 2:
                raise
            time.sleep(5 * (intento + 1))


# ---------------------------------------------------------------- descubrimiento
def paginas_mensuales():
    """[(pub_id, anio, mes, url)] desde la colección, sin duplicados."""
    vistos, out = set(), []
    for hoja in range(1, HOJAS_COLECCION + 1):
        html = get(COLECCION + (f"?sheet={hoja}" if hoja > 1 else "")).text
        encontrados = re.findall(r'/institucion/midagri/informes-publicaciones/(\d+)-([a-z0-9-]+)', html)
        nuevos = 0
        for pub_id, slug in encontrados:
            if pub_id in vistos or "aves" not in slug:
                continue
            m = re.search(r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|setiembre|septiembre|"
                          r"octubre|noviembre|diciembre)-?(\d{4})$", slug)
            if not m:
                continue
            vistos.add(pub_id); nuevos += 1
            out.append((pub_id, int(m.group(2)), MESES[m.group(1)],
                        f"{BASE}/institucion/midagri/informes-publicaciones/{pub_id}-{slug}"))
        if nuevos == 0:
            break
        time.sleep(1)
    return sorted(out, key=lambda x: (x[1], x[2]))


def pdfs_de_pagina(pub_id, url):
    """[(fecha, url_pdf)] de una página mensual."""
    html = get(url).text
    urls = re.findall(r'https://cdn\.www\.gob\.pe/uploads/document/file/\d+/[^"\'\s<>]+?\.pdf', html)
    out = {}
    for u in urls:
        nombre = u.rsplit("/", 1)[-1]
        if not nombre.startswith(f"{pub_id}-"):
            continue  # links a otras publicaciones
        m = re.search(r"(\d{2})-(\d{2})-(\d{4})\.pdf$", nombre)
        if m:
            f = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            out[f] = u
    return sorted(out.items())


# ---------------------------------------------------------------- almacenamiento
def leer_manifest():
    if not MANIFEST.exists():
        return {}
    with MANIFEST.open(newline="", encoding="utf-8") as fh:
        return {r["url"]: r for r in csv.DictReader(fh)}


def escribir_manifest(m):
    filas = sorted(m.values(), key=lambda r: (r["fecha"], r["url"]))
    with MANIFEST.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_MANIFEST)
        w.writeheader(); w.writerows(filas)


def anexar(nombre, filas, claves):
    """Anexa filas a data/<nombre>.csv; ante duplicados por `claves` se queda la última."""
    if not filas:
        return
    p = DATA / f"{nombre}.csv"
    nuevo = pd.DataFrame(filas)
    if p.exists():
        nuevo = pd.concat([pd.read_csv(p), nuevo], ignore_index=True)
    for c in nuevo.columns:
        if "fecha" in c:
            nuevo[c] = pd.to_datetime(nuevo[c].astype(str)).dt.date.astype(str)
    if "fecha_boletin" in nuevo.columns:
        nuevo = nuevo.sort_values("fecha_boletin", kind="stable")
    nuevo = nuevo.drop_duplicates(subset=claves, keep="last").sort_values(claves)
    nuevo.to_csv(p, index=False)


def construir_series():
    """data/serie_diaria.csv: un valor por región/serie/fecha (del boletín más reciente).
    Es la tabla que consume la web."""
    p = DATA / "diario.csv"
    if not p.exists():
        return
    d = pd.read_csv(p)
    v = (d[d.metrica == "valor"].sort_values("fecha_boletin")
         .drop_duplicates(["region", "serie", "fecha_dato"], keep="last")
         [["region", "serie", "unidad", "fecha_dato", "valor"]]
         .rename(columns={"fecha_dato": "fecha"}).sort_values(["region", "serie", "fecha"]))
    v.to_csv(DATA / "serie_diaria.csv", index=False)


# ---------------------------------------------------------------- validación por boletín
def validar_uno(fb, kpi, diario, ingreso):
    precio, oferta = kpi
    probs = []
    may = [r["valor"] for r in diario if r["region"] == "Lima" and r["serie"] == "pollo_vivo_mayorista"
           and r["metrica"] == "valor" and r["fecha_dato"] == fb]
    if precio is None or not may or abs(may[0] - precio) > 0.005:
        probs.append(f"precio portada {precio} vs tabla {may}")
    if oferta is not None:  # None = la plantilla no reporta oferta diaria (familia Excel)
        ing = [r["oferta_t"] for r in ingreso if r["fecha_dato"] == fb]
        if not ing or abs(ing[0] - oferta) > 1:
            probs.append(f"oferta portada {oferta} vs gráfico {ing}")
    if len(diario) < 12:
        probs.append(f"solo {len(diario)} filas diarias")
    return probs


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=date.fromisoformat, help="procesar boletines desde esta fecha")
    ap.add_argument("--ultimos-meses", type=int, default=None, help="revisar solo las N páginas mensuales más recientes")
    ap.add_argument("--reintentar-cuarentena", action="store_true")
    a = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    manifest = leer_manifest()
    meses = paginas_mensuales()
    print(f"Colección: {len(meses)} páginas mensuales ({meses[0][1]}-{meses[0][2]:02d} a {meses[-1][1]}-{meses[-1][2]:02d})")
    if a.desde:
        meses = [m for m in meses if (m[1], m[2]) >= (a.desde.year, a.desde.month)]
    if a.ultimos_meses:
        meses = meses[-a.ultimos_meses:]

    pendientes = []
    for pub_id, anio, mes, url in meses:
        pdfs = pdfs_de_pagina(pub_id, url)
        for f, u in pdfs:
            if a.desde and f < a.desde:
                continue
            est = manifest.get(u, {}).get("estado")
            if est == "ok" or (est == "cuarentena" and not a.reintentar_cuarentena):
                continue
            pendientes.append((f, pub_id, u))
        print(f"  {anio}-{mes:02d}: {len(pdfs)} PDFs")
        time.sleep(1)

    print(f"Pendientes: {len(pendientes)}")
    D, M, I = [], [], []
    ok = cuar = 0
    with tempfile.TemporaryDirectory() as tmp:
        for f, pub_id, u in pendientes:
            fila = dict(fecha=f.isoformat(), pub_id=pub_id, url=u,
                        procesado_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            try:
                ruta = Path(tmp) / u.rsplit("/", 1)[-1]
                ruta.write_bytes(get(u).content)
                fb, kpi, diario, mensual, ingreso = parse_pdf(ruta)
                probs = validar_uno(fb, kpi, diario, ingreso)
                if fb != f:
                    probs.append(f"fecha interna {fb} != nombre de archivo {f}")
                if probs:
                    fila.update(estado="cuarentena", detalle="; ".join(probs)); cuar += 1
                else:
                    D += diario; M += mensual; I += ingreso
                    fila.update(estado="ok", detalle=""); ok += 1
                ruta.unlink()
            except Exception as e:
                fila.update(estado="cuarentena", detalle=f"{type(e).__name__}: {e}"[:300]); cuar += 1
                traceback.print_exc(limit=1)
            manifest[u] = fila
            print(f"  {f} {fila['estado']} {fila['detalle']}")
            time.sleep(0.5)

    anexar("diario", D, ["region", "serie", "metrica", "fecha_dato", "fecha_boletin"])
    # mensual: se conserva la foto del boletín más reciente para cada mes
    anexar("mensual", M, ["region", "anio", "mes"])
    # ingreso: el gráfico repite 31 días; se conserva el valor del boletín más reciente
    anexar("ingreso", I, ["region", "fecha_dato"])
    construir_series()
    escribir_manifest(manifest)
    print(f"\nResumen: {ok} ok, {cuar} en cuarentena, {len(pendientes)} procesados")


if __name__ == "__main__":
    main()
