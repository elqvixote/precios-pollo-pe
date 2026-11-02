#!/usr/bin/env python3
"""
Genera la imagen diaria de CADA boletín nuevo que aún no tiene imagen, en orden cronológico
(p. ej. cuando MIDAGRI publica un boletín atrasado junto con el del día).
Reutiliza imagen_diaria.generar() sin modificarlo.

Solo mira los boletines de los últimos 14 días, para no rehacer el histórico.
Escribe la lista de imágenes generadas en imagenes/pendientes.txt (una ruta por línea).
"""
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imagen_diaria as diario

VENTANA_DIAS = 14


def main():
    m = pd.read_csv(diario.DATA / "manifest.csv")
    m = m[m.estado == "ok"]
    desde = (date.today() - timedelta(days=VENTANA_DIAS)).isoformat()
    fechas = sorted(set(m.fecha[m.fecha >= desde]))
    s = pd.read_csv(diario.DATA / "serie_diaria.csv")
    con_precio = set(s[(s.region == "Lima") & (s.serie == "pollo_vivo_mayorista")].fecha)
    nuevas = []
    for f in fechas:
        if f not in con_precio or (diario.SALIDA / f"{f}.png").exists():
            continue
        out = diario.generar(date.fromisoformat(f))     # también actualiza ultima.png
        nuevas.append(out.relative_to(diario.RAIZ).as_posix())
        print(f"Imagen generada: {out}")
    if nuevas:
        # ultima.png siempre es el boletín más reciente, aunque se haya rellenado uno atrasado
        fechadas = sorted(p for p in diario.SALIDA.glob("????-??-??.png"))
        shutil.copyfile(fechadas[-1], diario.SALIDA / "ultima.png")
    lista = diario.SALIDA / "pendientes.txt"
    lista.write_text("\n".join(nuevas))
    if not nuevas:
        print("Sin boletines nuevos sin imagen.")


if __name__ == "__main__":
    main()
