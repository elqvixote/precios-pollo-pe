#!/usr/bin/env python3
"""
Genera la imagen diaria (1080x1350, formato 4:5 para WhatsApp / Instagram).

Uso:
  python scripts/imagen_diaria.py                 # último día con precio mayorista
  python scripts/imagen_diaria.py --fecha 2026-10-16

Salida: imagenes/AAAA-MM-DD.png e imagenes/ultima.png
"""
import argparse
from datetime import date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
SALIDA = RAIZ / "imagenes"

for f in (RAIZ / "assets" / "fonts").glob("*.otf"):
    font_manager.fontManager.addfont(str(f))
plt.rcParams["font.family"] = "Inter"

# Paleta (instancia de referencia, modo claro)
C = dict(
    fondo="#fcfcfb", tarjeta="#f3f2ee", borde="#e4e2dc",
    texto="#0b0b0b", texto2="#52514e", tenue="#8a8984",
    serie1="#2a78d6",   # pollo vivo mayorista
    serie2="#eb6834",   # granja
)
MARCA = "preciopollo.pe"
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
MES3 = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_larga(d):
    return f"{DIAS[d.weekday()].capitalize()} {d.day} de {MESES[d.month - 1]} de {d.year}"


def fecha_corta(d):
    return f"{d.day}-{MES3[d.month - 1]}"


def cargar():
    s = pd.read_csv(DATA / "serie_diaria.csv", parse_dates=["fecha"])
    s = s[s.region == "Lima"]
    series = {k: g.set_index("fecha").valor.sort_index() for k, g in s.groupby("serie")}
    ing = pd.read_csv(DATA / "ingreso.csv", parse_dates=["fecha_dato"])
    series["oferta"] = ing[ing.region == "Lima"].set_index("fecha_dato").oferta_t.sort_index()
    return series


def hoy_y_previo(serie, f):
    """(valor del día f, valor del día con dato anterior, fecha anterior) o Nones."""
    if serie is None or f not in serie.index:
        return None, None, None
    prev = serie[serie.index < f]
    if prev.empty:
        return serie[f], None, None
    return serie[f], prev.iloc[-1], prev.index[-1]


def lectura(serie, f):
    """Frase corta de contexto para el precio mayorista."""
    v = serie[serie.index <= f]
    dif = v.diff().dropna()
    racha, signo = 0, 0
    for x in reversed(dif.values):
        s = int(x > 0.004) - int(x < -0.004)
        if s == 0 or (signo and s != signo):
            break
        signo, racha = s, racha + 1
    partes = []
    if racha >= 2:
        partes.append(f"{racha}.° día seguido de {'baja' if signo < 0 else 'alza'}")
    elif racha == 1:
        partes.append("bajó respecto al día anterior" if signo < 0 else "subió respecto al día anterior")
    else:
        partes.append("se mantiene igual que el día anterior")
    hoy = v.iloc[-1]
    atras = v.iloc[:-1]
    if signo < 0:
        menores = atras[atras <= hoy]
        if menores.empty:
            partes.append("el más bajo de toda la serie")
        elif (f - menores.index[-1]).days > 14:
            partes.append(f"el más bajo desde el {fecha_corta(menores.index[-1])}"
                          f"{'' if menores.index[-1].year == f.year else ' de ' + str(menores.index[-1].year)}")
    elif signo > 0:
        mayores = atras[atras >= hoy]
        if mayores.empty:
            partes.append("el más alto de toda la serie")
        elif (f - mayores.index[-1]).days > 14:
            partes.append(f"el más alto desde el {fecha_corta(mayores.index[-1])}"
                          f"{'' if mayores.index[-1].year == f.year else ' de ' + str(mayores.index[-1].year)}")
    return " · ".join(partes)


def delta_txt(v, p, dec=2, pref="S/ ", suf=""):
    if v is None or p is None or p == 0:
        return ""
    d = v - p
    pct = d / p * 100
    if abs(d) < 10 ** -(dec + 1):
        return "= igual"
    flecha = "▲" if d > 0 else "▼"
    return f"{flecha} {abs(pct):.1f}%"


def caja(fig, rect, color, radio_pulg=0.16):
    """Fondo redondeado con esquinas circulares (compensa la proporción del eje)."""
    ax = fig.add_axes(rect); ax.axis("off")
    ancho, alto = rect[2] * fig.get_figwidth(), rect[3] * fig.get_figheight()
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle=f"round,pad=0,rounding_size={radio_pulg / ancho}",
                                mutation_aspect=ancho / alto, transform=ax.transAxes, fc=color, ec="none"))
    return ax


def tarjeta(fig, x, y, w, h, etiqueta, valor, unidad, delta, nota=""):
    ax = caja(fig, [x, y, w, h], C["tarjeta"])
    ax.text(0.07, 0.80, etiqueta, fontsize=15, color=C["texto2"], fontweight="medium", transform=ax.transAxes)
    ax.text(0.07, 0.36, valor, fontsize=34, color=C["texto"], fontweight="semibold", transform=ax.transAxes)
    ax.text(0.07, 0.13, unidad, fontsize=13, color=C["tenue"], transform=ax.transAxes)
    if delta:
        ax.text(0.93, 0.13, delta, fontsize=15, color=C["texto2"], fontweight="medium", ha="right",
                transform=ax.transAxes)
    if nota:
        ax.text(0.93, 0.80, nota, fontsize=12, color=C["tenue"], ha="right", transform=ax.transAxes)


def generar(fecha=None, solo_si_nueva=False):
    S = cargar()
    may = S["pollo_vivo_mayorista"]
    f = pd.Timestamp(fecha) if fecha else may.index.max()
    if solo_si_nueva and (SALIDA / f"{f.date().isoformat()}.png").exists():
        return None
    v, p, fp = hoy_y_previo(may, f)
    if v is None:
        raise SystemExit(f"No hay precio mayorista para {f.date()}")

    fig = plt.figure(figsize=(10.8, 13.5), dpi=100, facecolor=C["fondo"])

    # --- Encabezado
    fig.text(0.06, 0.945, "PRECIO DEL POLLO · LIMA", fontsize=17, color=C["serie1"], fontweight="bold")
    fig.text(0.06, 0.912, fecha_larga(f.date()), fontsize=24, color=C["texto"], fontweight="semibold")

    # --- Número del día
    fig.text(0.06, 0.855, "Pollo vivo · precio mayorista", fontsize=19, color=C["texto2"], fontweight="medium")
    num = fig.text(0.055, 0.735, f"S/ {v:.2f}", fontsize=120, color=C["texto"], fontweight="bold")
    bb = num.get_window_extent(renderer=fig.canvas.get_renderer()).transformed(fig.transFigure.inverted())
    fig.text(bb.x1 + 0.015, 0.745, "por kg", fontsize=26, color=C["texto2"])

    d = pd.read_csv(DATA / "diario.csv", parse_dates=["fecha_boletin"])
    p7 = d[(d.region == "Lima") & (d.serie == "pollo_vivo_mayorista") & (d.metrica == "prom_7d")
           & (d.fecha_boletin == f)].valor
    prom7 = p7.iloc[0] if len(p7) else may[(may.index <= f) & (may.index > f - timedelta(days=7))].mean()
    linea = []
    if p is not None:
        d = v - p
        if abs(d) < 0.005:
            linea.append(f"= igual que el {DIAS[fp.weekday()]}")
        else:
            linea.append(f"{'▲' if d > 0 else '▼'} S/ {abs(d):.2f} ({d / p * 100:+.1f}%) vs. {DIAS[fp.weekday()]}")
    if pd.notna(prom7) and prom7:
        linea.append(f"{(v - prom7) / prom7 * 100:+.1f}% vs. promedio 7 días")
    fig.text(0.06, 0.700, "   ·   ".join(linea), fontsize=19, color=C["texto"], fontweight="medium")

    # --- Lectura rápida
    ax = caja(fig, [0.06, 0.630, 0.88, 0.045], "#e8f0fb", radio_pulg=0.3)
    ax.text(0.03, 0.5, lectura(may, f).capitalize(), fontsize=17, color=C["texto"],
            va="center", transform=ax.transAxes, fontweight="medium")

    # --- Tendencia 30 días (mismo eje, misma unidad: S/ por kg)
    ax = fig.add_axes([0.08, 0.425, 0.80, 0.175])
    ini = f - timedelta(days=30)
    m30 = may[(may.index > ini) & (may.index <= f)]
    g30 = S["pollo_vivo_granja"]; g30 = g30[(g30.index > ini) & (g30.index <= f)]
    ax.plot(m30.index, m30.values, color=C["serie1"], lw=2.5, solid_capstyle="round")
    ax.plot(g30.index, g30.values, color=C["serie2"], lw=2.5, solid_capstyle="round")
    ax.scatter([f], [v], s=70, color=C["serie1"], zorder=3, edgecolor=C["fondo"], linewidth=2)
    ax.text(m30.index[-1] + timedelta(days=0.6), m30.values[-1], " Mayorista", color=C["texto2"],
            fontsize=13, va="bottom")
    if len(g30):
        ax.text(g30.index[-1] + timedelta(days=0.6), g30.values[-1], " Granja", color=C["texto2"],
                fontsize=13, va="top")
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(C["borde"])
    ax.tick_params(colors=C["tenue"], labelsize=12, length=0)
    ax.grid(axis="y", color=C["borde"], lw=0.8); ax.set_axisbelow(True)
    ax.set_facecolor(C["fondo"])
    lo = min(m30.min(), g30.min() if len(g30) else m30.min()); hi = max(m30.max(), g30.max() if len(g30) else m30.max())
    ax.set_ylim(lo - (hi - lo) * 0.18 - 0.05, hi + (hi - lo) * 0.08 + 0.05)
    ticks = pd.date_range(ini, f, periods=4)
    ax.set_xticks(ticks); ax.set_xticklabels([fecha_corta(t) for t in ticks])
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y:.1f}"))
    fig.text(0.06, 0.612, "Últimos 30 días · S/ por kg", fontsize=14, color=C["texto2"], fontweight="medium")

    # --- Tarjetas
    def val(k, fmt, unidad, etiqueta, nota=""):
        x, px, _ = hoy_y_previo(S.get(k), f)
        return dict(etiqueta=etiqueta, valor=fmt(x) if x is not None else "s/d", unidad=unidad,
                    delta=delta_txt(x, px), nota=nota)

    peso, _, _ = hoy_y_previo(S.get("peso_promedio_pollo_vivo"), f)
    por_ave = dict(etiqueta="Precio por ave (vivo)",
                   valor=f"S/ {v * peso:.2f}" if peso else "s/d",
                   unidad=f"{peso:.2f} kg promedio por ave" if peso else "", delta="")
    tarjetas = [
        val("pollo_vivo_granja", lambda x: f"S/ {x:.2f}", "por kg · pollo vivo", "Granja"),
        val("pollo_eviscerado_consumidor", lambda x: f"S/ {x:.2f}", "por kg · eviscerado", "Mercado minorista"),
        por_ave,
        val("oferta", lambda x: f"{x:,.0f} t", "ingreso a centros de distribución", "Oferta del día"),
        val("huevo_rosado", lambda x: f"S/ {x:.2f}", "por kg · mayorista", "Huevo rosado"),
        val("gallina_colorada", lambda x: f"S/ {x:.2f}", "por kg · mayorista", "Gallina colorada"),
    ]
    W, H, GX, GY = 0.43, 0.085, 0.02, 0.014
    for i, t in enumerate(tarjetas):
        fila, col = divmod(i, 2)
        tarjeta(fig, 0.06 + col * (W + GX), 0.305 - fila * (H + GY), W, H, **t)

    # --- Línea secundaria (series con rezago de un día)
    extra = []
    for k, nombre in (("gallina_reproductora", "Gallina reproductora"), ("jurel", "Jurel"), ("bonito", "Bonito")):
        s = S.get(k)
        if s is None:
            continue
        s = s[s.index <= f]
        if len(s) and (f - s.index[-1]).days <= 3:
            marca = "" if s.index[-1] == f else "*"
            extra.append(f"{nombre} S/ {s.iloc[-1]:.2f}{marca}")
    if extra:
        fig.text(0.06, 0.088, "   ·   ".join(extra), fontsize=14, color=C["texto2"])
        if any(e.endswith("*") for e in extra):
            fig.text(0.06, 0.068, "* último dato disponible (día anterior)", fontsize=11.5, color=C["tenue"])

    # --- Pie
    fig.add_artist(plt.Line2D([0.06, 0.94], [0.052, 0.052], color=C["borde"], lw=1))
    fig.text(0.06, 0.025, "Fuente: MIDAGRI – SISAP, boletín diario de aves. Lima Metropolitana.",
             fontsize=12, color=C["tenue"])
    fig.text(0.94, 0.025, MARCA, fontsize=14, color=C["texto2"], fontweight="semibold", ha="right")

    SALIDA.mkdir(exist_ok=True)
    out = SALIDA / f"{f.date().isoformat()}.png"
    fig.savefig(out, dpi=100, facecolor=C["fondo"])
    fig.savefig(SALIDA / "ultima.png", dpi=100, facecolor=C["fondo"])
    plt.close(fig)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", type=date.fromisoformat)
    ap.add_argument("--solo-si-nueva", action="store_true", help="no regenerar si ya existe la imagen de ese día")
    a = ap.parse_args()
    out = generar(a.fecha, a.solo_si_nueva)
    print(out or "La imagen del último día ya existe; nada que hacer.")
    # Para GitHub Actions: avisar si se generó una imagen nueva
    import os
    if out and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"nueva={out.relative_to(RAIZ)}\n")
