"""Detección de bonos desalineados respecto de su curva.

La idea: ajustar una curva de TIR contra duration con los demás bonos de
la familia y medir cuánto se despega cada uno. Un residuo positivo
significa que rinde más de lo que su plazo justifica, o sea que está
barato.

Dos precisiones que salieron del backtest:

- El bono se excluye del ajuste que lo mide. Si no, uno muy barato tira
  la curva hacia abajo y subestima su propia baratura.
- Lo que importa no es el residuo sino cuánto se aleja de SU PROPIA
  historia. Hay bonos estructuralmente baratos que estarían en rojo todos
  los días sin que haya nada que hacer.
"""

import logging
import math
import statistics
from datetime import date, timedelta

import db

log = logging.getLogger("curva")

VENTANA = 120        # días de historia para el z-score del residuo
MIN_PUNTOS = 5       # bonos mínimos en la familia para ajustar
MIN_HISTORIA = 40    # días mínimos para que el z-score signifique algo


def _ajuste(puntos):
    """Recta sobre log(duration). La curva real es cóncava: en lineal
    los extremos quedan siempre mal medidos."""
    n = len(puntos)
    if n < 3:
        return None
    xs = [math.log(max(md, 0.05)) for md, _ in puntos]
    ys = [tir for _, tir in puntos]
    sx, sy = sum(xs), sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    den = n * sxx - sx * sx
    if abs(den) < 1e-9:
        return None
    b = (n * sxy - sx * sy) / den
    a = (sy - b * sx) / n
    return lambda md: a + b * math.log(max(md, 0.05))


def residuos(filas, campo="tir_last"):
    """Residuo en puntos básicos de cada bono contra su familia.

    filas: las de la tabla de bonos, con familia, md y tir.
    """
    por_fam = {}
    for f in filas:
        md, tir = f.get("md"), f.get(campo)
        if md is None or tir is None:
            continue
        por_fam.setdefault(f.get("familia"), []).append((f["simbolo"], md, tir))

    out = {}
    for fam, pts in por_fam.items():
        if len(pts) < MIN_PUNTOS:
            continue
        for i, (sim, md, tir) in enumerate(pts):
            otros = [(m, t) for j, (_, m, t) in enumerate(pts) if j != i]
            fit = _ajuste(otros)
            if not fit:
                continue
            out[sim] = {
                "residuo": (tir - fit(md)) * 100,   # puntos básicos
                "curva": fit(md),
                "familia": fam,
                "n_familia": len(pts),
            }
    return out


# -- historia del residuo ---------------------------------------------

ESQUEMA = """
CREATE TABLE IF NOT EXISTS residuo_hist (
    simbolo  TEXT NOT NULL,
    fecha    TEXT NOT NULL,
    residuo  REAL NOT NULL,
    PRIMARY KEY (simbolo, fecha)
);
CREATE INDEX IF NOT EXISTS ix_rh ON residuo_hist(simbolo, fecha);
"""


def init():
    c = db.conn()
    c.executescript(ESQUEMA)
    c.commit()


def guardar(res, f=None):
    f = (f or date.today()).isoformat()
    c = db.conn()
    c.executemany(
        "INSERT OR REPLACE INTO residuo_hist (simbolo, fecha, residuo) "
        "VALUES (?,?,?)",
        [(s, f, d["residuo"]) for s, d in res.items()])
    c.commit()
    return len(res)


def reconstruir(desde=None):
    """Calcula el residuo de cada día pasado con la serie histórica.

    Es lo que permite tener z-score desde el primer momento en vez de
    esperar cuatro meses a juntar historia.
    """
    init()
    desde = (desde or (date.today() - timedelta(days=900))).isoformat()

    filas = db.conn().execute(
        "SELECT simbolo, fecha, tir, md FROM bono_hist "
        "WHERE fecha >= ? AND tir IS NOT NULL AND md IS NOT NULL "
        "ORDER BY fecha", (desde,)).fetchall()

    import bonos as BO
    esps = BO.especies()
    bonos_cfg, _ = BO.cargar()

    por_fecha = {}
    for r in filas:
        info = esps.get(r["simbolo"])
        if not info:
            continue
        cfg = bonos_cfg.get(info["cronograma"])
        if not cfg:
            continue
        fam = BO._familia(cfg, info, r["simbolo"])
        por_fecha.setdefault(r["fecha"], []).append(
            {"simbolo": r["simbolo"], "familia": fam,
             "md": r["md"], "tir_last": r["tir"]})

    total = 0
    for f, filas_dia in sorted(por_fecha.items()):
        res = residuos(filas_dia)
        if res:
            total += guardar(res, date.fromisoformat(f))
    log.info("residuos reconstruidos: %d puntos en %d fechas",
             total, len(por_fecha))
    return total


def zscore(simbolo, residuo_hoy):
    """Cuánto se aleja el residuo de hoy de su propia historia."""
    filas = db.conn().execute(
        "SELECT residuo FROM residuo_hist WHERE simbolo=? "
        "ORDER BY fecha DESC LIMIT ?", (simbolo, VENTANA)).fetchall()
    if len(filas) < MIN_HISTORIA:
        return None
    hist = [f["residuo"] for f in filas]
    m = statistics.mean(hist)
    sd = statistics.pstdev(hist)
    if sd < 1e-6:
        return None
    return {"z": (residuo_hoy - m) / sd, "media": m, "desvio": sd,
            "n": len(hist)}


def analizar(filas):
    """Residuo, z-score y el vecino contra el que conviene rotar."""
    res = residuos(filas)
    por_sim = {f["simbolo"]: f for f in filas}
    salida = {}

    for sim, d in res.items():
        z = zscore(sim, d["residuo"])
        f = por_sim[sim]

        # vecino: mismo grupo, duration parecida, para rotar
        vecino = None
        mejor = 9e9
        for otro in filas:
            if otro["simbolo"] == sim or otro.get("familia") != d["familia"]:
                continue
            if otro.get("md") is None:
                continue
            dif = abs(otro["md"] - f["md"])
            if dif < mejor:
                mejor, vecino = dif, otro["simbolo"]

        salida[sim] = {
            "residuo": d["residuo"],
            "curva": d["curva"],
            "n_familia": d["n_familia"],
            "z": z["z"] if z else None,
            "z_n": z["n"] if z else 0,
            "media_hist": z["media"] if z else None,
            "vecino": vecino if mejor < (f["md"] or 1) * 0.5 else None,
        }
    return salida
