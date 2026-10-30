"""Cálculo del comentario semanal (viernes) a partir de serie_diaria.csv.
Formato largo: region, serie, unidad, fecha, valor. Solo usa Lima."""
import numpy as np
import pandas as pd

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _soles(x):
    return f"S/ {x:,.2f}"


def calcular_comentario(ruta_csv="serie_diaria.csv", hasta=None):
    raw = pd.read_csv(ruta_csv, parse_dates=["fecha"])
    L = (raw[raw.region == "Lima"]
         .pivot_table(index="fecha", columns="serie", values="valor").sort_index())
    if hasta is not None:
        L = L.loc[:pd.Timestamp(hasta)]
    p = L["pollo_vivo_mayorista"].dropna()
    hoy = p.index[-1]
    precio = p.iloc[-1]
    out = {"fecha": hoy}

    # 1) Semáforo: precio vs media de 365 días y bandas p20/p80 históricas
    ma = p.rolling("365D", min_periods=200).mean()
    z = np.log(p / ma).dropna()
    q20, q80 = z.quantile(0.20), z.quantile(0.80)
    b_baja, b_alta, media = ma.iloc[-1] * np.exp(q20), ma.iloc[-1] * np.exp(q80), ma.iloc[-1]
    if precio < b_baja * 1.05:
        color, titulo = "verde", "Barato para el año"
    elif precio > b_alta * 0.95:
        color, titulo = "rojo", "Caro para el año"
    else:
        color, titulo = "amarillo", "Precio normal para el año"
    out["semaforo"] = {"color": color, "titulo": titulo,
                       "detalle": f"Hoy {_soles(precio)}. Lo normal en el último año: entre {_soles(b_baja)} y {_soles(b_alta)}."}

    # 2) Qué suele pasar después: casos parecidos (misma zona del año + mismo movimiento de 2 semanas)
    r10 = np.log(p / p.shift(10))
    fwd = np.log(p.shift(-20) / p)
    D = pd.DataFrame({"z": z, "r10": r10, "fwd": fwd}).dropna()
    zq = pd.qcut(z, 5, labels=False)
    D["zq"] = zq.reindex(D.index)
    bucket = lambda r: 1 if r > 0.10 else (-1 if r < -0.10 else 0)
    D["rb"] = D["r10"].map(bucket)
    zq_hoy, rb_hoy = zq.iloc[-1], bucket(r10.iloc[-1])
    an = D[(D.zq == zq_hoy) & (D.rb == rb_hoy)]
    if len(an) < 30:
        an = D[D.zq == zq_hoy]
    med = an["fwd"].median()
    if med > 0.05:
        tend = "en las 4 semanas siguientes siguió subiendo"
    elif med < -0.05:
        tend = "en las 4 semanas siguientes bajó"
    else:
        tend = "en las 4 semanas siguientes se quedó más o menos igual"
    p_baja10, p_sube10 = (an.fwd < -.10).mean(), (an.fwd > .10).mean()
    if p_baja10 >= 0.35 and med >= -0.05:
        tend += f", aunque {round(p_baja10 * 10)} de cada 10 veces bajó más de 10%"
    elif p_sube10 >= 0.35 and med <= 0.05:
        tend += f", aunque {round(p_sube10 * 10)} de cada 10 veces subió más de 10%"
    cambio = precio - p.iloc[-11]
    mov = (f"Ya subió {_soles(abs(cambio))} en 2 semanas." if rb_hoy == 1 else
           f"Ya bajó {_soles(abs(cambio))} en 2 semanas." if rb_hoy == -1 else
           "Estuvo estable las últimas 2 semanas.")
    out["despues"] = {"titulo": "Lo que suele pasar después",
                      "detalle": f"{mov} Las veces que pasó algo parecido, {tend}.",
                      "_n_casos": len(an), "_mediana_%": round(med * 100, 1),
                      "_p_sube10": round((an.fwd > .10).mean(), 2), "_p_baja10": round((an.fwd < -.10).mean(), 2)}

    # 3) Calendario: el mes de la semana que viene
    mes = (hoy + pd.Timedelta(days=7)).month
    mm = p.resample("MS").mean()
    var = mm.pct_change().dropna()
    vm = var[var.index.month == mes]
    sube, n, prom = int((vm > 0).sum()), len(vm), vm.mean() * 100
    fuerza = "poco" if abs(prom) < 5 else "bastante"
    if sube >= n - 1:
        frase = f"{MESES[mes-1].capitalize()} subió {sube} de {n} años desde 2020, en promedio {fuerza} ({prom:+.0f}%)."
    elif sube <= 1:
        frase = f"{MESES[mes-1].capitalize()} bajó {n - sube} de {n} años desde 2020, en promedio {prom:+.0f}%."
    else:
        frase = f"{MESES[mes-1].capitalize()} no tiene un patrón fijo: subió {sube} de {n} años, bajó los demás."
    out["calendario"] = {"titulo": f"Qué pasa normalmente en {MESES[mes-1]}", "detalle": frase}

    # 4) Granjas: oferta (t) y peso por ave, últimos 7 días vs 7 anteriores
    def sem(serie):
        s = L.get(serie, pd.Series(dtype=float)).dropna()
        a = s.loc[hoy - pd.Timedelta(days=6):hoy].mean()
        b = s.loc[hoy - pd.Timedelta(days=13):hoy - pd.Timedelta(days=7)].mean()
        return a, b
    of_a, of_b = sem("oferta_pollo_vivo")
    pe_a, pe_b = sem("peso_promedio_pollo_vivo")
    d_of = (of_a / of_b - 1) if pd.notna(of_a) and pd.notna(of_b) else np.nan
    d_pe = pe_a - pe_b
    of_baja, of_sube = pd.notna(d_of) and d_of < -0.02, pd.notna(d_of) and d_of > 0.02
    pe_baja, pe_sube = d_pe < -0.02, d_pe > 0.02
    menos = int(of_baja) + int(pe_baja)
    mas = int(of_sube) + int(pe_sube)
    partes = []
    if of_baja: partes.append("entra menos pollo a Lima")
    if of_sube: partes.append("entra más pollo a Lima")
    if pe_baja: partes.append("el pollo viene más liviano")
    if pe_sube: partes.append("el pollo viene más pesado")
    if menos and not mas:
        g = " y ".join(partes).capitalize() + ": hay menos pollo disponible. No se espera que baje esta semana."
    elif mas and not menos:
        g = " y ".join(partes).capitalize() + ": las granjas tienen pollo guardado. El precio podría ceder."
    else:
        g = "La llegada de pollo a Lima está normal. Sin señal clara por este lado."
    det_of = f"{of_a:,.0f} t/día" if pd.notna(of_a) else "s/d"
    out["granjas"] = {"titulo": "Cómo viene el pollo de las granjas",
                      "detalle": f"{g} ({det_of}, {pe_a:.2f} kg por ave)",
                      "_var_oferta_%": round(d_of * 100, 1) if pd.notna(d_of) else None, "_var_peso_kg": round(d_pe, 3)}

    # 5) Margen de reventa: mayorista − granja vs rango normal (p25–p75 del último año)
    g_ = L["pollo_vivo_granja"].dropna()
    sp = (p - g_).dropna()
    sp_hoy = sp.iloc[-1]
    ult = sp.loc[hoy - pd.Timedelta(days=365):]
    lo, hi = ult.quantile(.25), ult.quantile(.75)
    estado = ("por debajo de lo normal: margen ajustado para revender" if sp_hoy < lo else
              "por encima de lo normal: buen margen para revender" if sp_hoy > hi else "dentro de lo normal")
    out["margen"] = {"titulo": "Margen de reventa",
                     "detalle": f"Granja {_soles(g_.iloc[-1])}, mayorista {_soles(precio)}: diferencia {_soles(sp_hoy)}, "
                                f"{estado} ({_soles(lo)} a {_soles(hi)})."}
    return out


if __name__ == "__main__":
    import json, sys
    r = calcular_comentario(sys.argv[1] if len(sys.argv) > 1 else "serie_diaria.csv")
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
