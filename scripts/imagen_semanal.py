#!/usr/bin/env python3
"""
Comentario semanal (segunda lámina, viernes). No modifica el reporte diario:
reutiliza sus estilos importando imagen_diaria y el cálculo de comentario_semanal.py.

Uso:
  python scripts/imagen_semanal.py                    # con el último dato disponible
  python scripts/imagen_semanal.py --fecha 2026-10-29 # con datos hasta esa fecha
  python scripts/imagen_semanal.py --automatico       # para el workflow: solo si corresponde

Salida: imagenes/comentario_semanal_AAAA-MM-DD.png (+ .json con los valores de control)
"""
import argparse
import json
import os
import sys
import textwrap
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imagen_diaria as diario                 # estilos, fuentes y utilidades (solo lectura)
from comentario_semanal import calcular_comentario

DATA, SALIDA, RAIZ = diario.DATA, diario.SALIDA, diario.RAIZ
C = diario.C
SEMAFORO = {"verde": "#4caf7a", "amarillo": "#f2b544", "rojo": "#e2655a"}   # tonos suaves
W, H = 1080, 1350
NOTA = "Referencial, basado en precios desde 2020. No es un pronóstico."


# ---------------------------------------------------------------- datos
def preparar_serie():
    """serie_diaria.csv + oferta diaria de Lima (ingreso.csv), en formato largo.
    Equivale a unir el consolidado precios_pollo_2026.csv: la única serie que el histórico
    no trae en formato largo es la oferta de Lima. Se escribe en un archivo aparte para no
    tocar los datos del reporte diario."""
    old = pd.read_csv(DATA / "serie_diaria.csv", parse_dates=["fecha"])
    ing = pd.read_csv(DATA / "ingreso.csv", parse_dates=["fecha_dato"])
    ing = ing[ing.region == "Lima"].rename(columns={"fecha_dato": "fecha", "oferta_t": "valor"})
    ing = ing.assign(region="Lima", serie="oferta_pollo_vivo", unidad="t")
    out = (pd.concat([old, ing[["region", "serie", "unidad", "fecha", "valor"]]])
             .drop_duplicates(["region", "serie", "fecha"], keep="last")
             .sort_values(["region", "serie", "fecha"]))
    ruta = DATA / "serie_semanal.csv"
    out.to_csv(ruta, index=False)
    return ruta


# ---------------------------------------------------------------- dibujo
def y(px):
    return 1 - px / H


def caja_px(fig, top, left, ancho, alto, color):
    return diario.caja(fig, [left / W, y(top + alto), ancho / W, alto / H], color, radio_pulg=0.16)


def envolver(texto, ancho_chars):
    # "S/ 5.40" nunca se parte en dos líneas (espacio duro)
    return textwrap.wrap(texto.replace("S/ ", "S/\u00a0"), width=ancho_chars, break_long_words=False)


def generar(r):
    f = pd.Timestamp(r["fecha"])
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=C["fondo"])
    M = 65                                   # margen lateral (px), igual que el diario
    ancho = W - 2 * M

    # Encabezado
    fig.text(M / W, 0.945, "PRECIO DEL POLLO · LIMA", fontsize=17, color=C["serie1"], fontweight="bold")
    fig.text(M / W, 0.912, f"Comentario semanal · {diario.fecha_larga(f.date())}",
             fontsize=23, color=C["texto"], fontweight="semibold")

    # Semáforo
    s = r["semaforo"]
    top, alto = 165, 190
    caja_px(fig, top, M, ancho, alto, C["tarjeta"])
    cx, cy, rad = M + 85, top + alto / 2, 48
    fig.add_artist(matplotlib.patches.Ellipse((cx / W, y(cy)), 2 * rad / W, 2 * rad / H, transform=fig.transFigure,
                                              facecolor=SEMAFORO.get(s["color"], C["tenue"]), edgecolor="none"))
    tx = M + 170
    fig.text(tx / W, y(top + 62), s["titulo"], fontsize=30, color=C["texto"], fontweight="bold", va="center")
    lineas = envolver(s["detalle"], 54)
    for i, l in enumerate(lineas[:3]):
        fig.text(tx / W, y(top + 112 + i * 34), l, fontsize=18.5, color=C["texto2"], va="center")

    # Bloques 2 a 5
    cursor = top + alto + 22
    GAP, LH, PAD = 16, 37, 26
    for k in ("despues", "calendario", "granjas", "margen"):
        b = r[k]
        lineas = envolver(b["detalle"], 57)
        h = PAD + 30 + 10 + len(lineas) * LH + PAD - 8
        caja_px(fig, cursor, M, ancho, h, C["tarjeta"])
        fig.text((M + 32) / W, y(cursor + PAD + 12), b["titulo"], fontsize=15, color=C["texto2"],
                 fontweight="medium", va="center")
        for i, l in enumerate(lineas):
            fig.text((M + 32) / W, y(cursor + PAD + 30 + 10 + LH / 2 + i * LH), l, fontsize=20.5,
                     color=C["texto"], va="center")
        cursor += h + GAP

    # Nota y pie (igual que el diario)
    fig.text(M / W, 0.068, NOTA, fontsize=11.5, color=C["tenue"])
    fig.add_artist(plt.Line2D([0.06, 0.94], [0.052, 0.052], color=C["borde"], lw=1))
    fig.text(0.06, 0.025, "Fuente: MIDAGRI – SISAP, boletín diario de aves. Lima Metropolitana.",
             fontsize=12, color=C["tenue"])
    fig.text(0.94, 0.025, diario.MARCA, fontsize=14, color=C["texto2"], fontweight="semibold", ha="right")

    if cursor > H * (1 - 0.085):
        print(f"AVISO: el contenido llega a {cursor:.0f}px y podría tocar la nota del pie", file=sys.stderr)

    SALIDA.mkdir(exist_ok=True)
    out = SALIDA / f"comentario_semanal_{f.date().isoformat()}.png"
    fig.savefig(out, dpi=100, facecolor=C["fondo"])
    plt.close(fig)
    return out


def control(r):
    c = {k: v for blq in r.values() if isinstance(blq, dict) for k, v in blq.items() if k.startswith("_")}
    c["fecha"] = str(pd.Timestamp(r["fecha"]).date())
    c["semaforo"] = r["semaforo"]["color"]
    return c


# ---------------------------------------------------------------- cuándo corresponde
def corresponde(ref, hoy):
    """Viernes con dato, o sábado cuando el último dato de la semana es lun–jue
    (viernes feriado o sin boletín)."""
    misma_semana = ref.isocalendar()[:2] == hoy.isocalendar()[:2]
    if ref.weekday() == 4 and (hoy - ref).days <= 2:
        return True
    return hoy.weekday() == 5 and misma_semana and ref.weekday() < 4


def generar_comentario_semanal(fecha=None, automatico=False):
    ruta = preparar_serie()
    if automatico:
        s = pd.read_csv(ruta, parse_dates=["fecha"])
        ref = s[(s.region == "Lima") & (s.serie == "pollo_vivo_mayorista")].fecha.max().date()
        hoy = datetime.now(timezone(timedelta(hours=-5))).date()
        lunes = ref - timedelta(days=ref.weekday())
        ya = [p for p in SALIDA.glob("comentario_semanal_*.png")
              if lunes <= date.fromisoformat(p.stem[-10:]) <= lunes + timedelta(days=6)]
        if ya or not corresponde(ref, hoy):
            return None, None
        fecha = ref
    r = calcular_comentario(str(ruta), hasta=fecha)
    out = generar(r)
    c = control(r)
    out.with_suffix(".json").write_text(json.dumps(c, ensure_ascii=False, indent=2))
    return out, c


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", type=date.fromisoformat)
    ap.add_argument("--automatico", action="store_true")
    a = ap.parse_args()
    out, c = generar_comentario_semanal(a.fecha, a.automatico)
    if not out:
        print("No corresponde comentario semanal en esta corrida.")
        sys.exit(0)
    print(out)
    print(json.dumps(c, ensure_ascii=False, indent=2))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"semanal={out.relative_to(RAIZ)}\n")
            fh.write(f"semanal_json={out.with_suffix('.json').relative_to(RAIZ)}\n")
