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


def monto_punta(f, lado, mep=None):
    """Plata que hay en una punta, llevada a pesos.

    Los bonos cotizan por cada 100 nominales, asi que el monto es
    cantidad x precio / 100. Las especies D y C liquidan en dolares y se
    pasan a pesos por el MEP para poder compararlas con las de pesos con
    un solo numero.

    Devuelve None si no hay con que calcularlo: sin dato no se descarta
    nada, porque no es lo mismo "no opero" que "no se cuanto opero".
    """
    q = f.get("q_ask") if lado == "ask" else f.get("q_bid")
    p = f.get("ask") if lado == "ask" else f.get("bid")
    if not q or not p:
        return None
    monto = q * p / 100.0
    if (f.get("moneda_cotiza") or "ARS") != "ARS":
        if not mep:
            return None
        monto *= mep
    return monto


def canjes(filas, an, tenidos, costo_pct=0.5, min_ganancia=1.0,
           max_dif_md=0.35, min_z=1.0, min_monto=0, mep=None):
    """Contra que bono conviene rotar cada uno de los que se tienen.

    La cuenta no es "cual rinde mas" sino cuanto se espera que cada uno
    se mueva hacia su propio residuo medio. Un bono estructuralmente
    barato esta barato todos los dias y no por eso va a converger: lo que
    revierte es el desvio contra la propia historia, que es lo que mide
    el z-score.

    Con el residuo en puntos basicos y la duration modificada en anios,
    el precio esperado se mueve MD x (residuo - media) / 100 por ciento.
    La ganancia del canje es la diferencia entre las dos puntas, menos lo
    que cuesta salir y entrar.

    Se compara solo dentro de la misma familia y con duration parecida:
    pasar de un tramo corto a uno largo puede dar mas nominales y dejar
    otra cartera, y eso ya no es la misma estrategia.

    `min_monto` descarta las puntas que no alcanzan esa plata en pesos.
    Una punta suelta de dos laminas da un precio que no se puede operar y
    con el un canje que no existe. Se mide el bid del que sale y el ask
    del que entra, que son las dos que se van a tocar. El ajuste de la
    curva NO se filtra: `reconstruir` trabaja sobre `bono_hist`, que no
    guarda cantidades, y un filtro que valga hoy y no en la historia
    ensucia el z-score, que es justamente lo que decide el canje.
    """
    por_sim = {f["simbolo"]: f for f in filas}

    def recorrido(sim):
        d = an.get(sim) or {}
        f = por_sim.get(sim) or {}
        if d.get("media_hist") is None or f.get("md") is None:
            return None
        return f["md"] * (d["residuo"] - d["media_hist"]) / 100.0

    salida = []
    for sim in tenidos:
        f = por_sim.get(sim)
        d = an.get(sim)
        if not f or not d or f.get("md") is None:
            continue
        rec_a = recorrido(sim)
        if rec_a is None:
            continue
        if min_monto:
            m = monto_punta(f, "bid", mep)
            if m is not None and m < min_monto:
                continue
        mejor = None
        for otro in filas:
            osim = otro["simbolo"]
            if osim == sim or otro.get("familia") != f.get("familia"):
                continue
            if otro.get("md") is None or not otro.get("ask"):
                continue
            if min_monto:
                m = monto_punta(otro, "ask", mep)
                if m is not None and m < min_monto:
                    continue
            # Duration parecida, en proporcion: medio anio de diferencia
            # es mucho en un bono corto y poco en uno largo.
            if abs(otro["md"] - f["md"]) > max_dif_md * max(f["md"], 0.5):
                continue
            od = an.get(osim) or {}
            if od.get("z") is None or od["z"] < min_z:
                continue
            rec_b = recorrido(osim)
            if rec_b is None:
                continue
            gana = rec_b - rec_a - costo_pct
            if gana < min_ganancia:
                continue
            if not mejor or gana > mejor["ganancia_pct"]:
                mejor = {
                    "hacia": osim, "ganancia_pct": gana,
                    "z_hacia": od["z"], "residuo_hacia": od["residuo"],
                    "md_hacia": otro["md"], "tir_hacia": otro.get("tir_last"),
                    "recorrido_hacia": rec_b,
                    "monto_hacia": monto_punta(otro, "ask", mep),
                }
        if mejor:
            mejor.update({
                "desde": sim, "z_desde": d.get("z"),
                "residuo_desde": d["residuo"], "md_desde": f["md"],
                "tir_desde": f.get("tir_last"), "recorrido_desde": rec_a,
                "familia": f.get("familia"), "costo_pct": costo_pct,
                "monto_desde": monto_punta(f, "bid", mep),
            })
            salida.append(mejor)
    salida.sort(key=lambda x: x["ganancia_pct"], reverse=True)
    return salida


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
