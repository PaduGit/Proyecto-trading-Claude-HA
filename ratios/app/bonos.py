"""Tabla de bonos: TIR en cada punta, con conversión de pesos según el MEP.

El MEP no es un número único. Si comprás dólares pagás uno y si los vendés
cobrás otro, porque el spread del bono queda adentro. Para que la TIR sea
la que realmente conseguís, cada punta se convierte con el MEP que le toca.
"""

import logging
import os
from datetime import date

import yaml

import renta_fija as RF

log = logging.getLogger("bonos")

RUTA = os.path.join(os.path.dirname(__file__), "datos", "bonos.yaml")

_cache = {"bonos": None, "equiv": None}


def cargar():
    if _cache["bonos"] is None:
        try:
            with open(RUTA) as f:
                d = yaml.safe_load(f) or {}
            _cache["bonos"] = d.get("bonos") or {}
            _cache["equiv"] = d.get("equivalencias") or {}
        except Exception as e:
            log.error("no se pudo leer bonos.yaml: %s", e)
            _cache["bonos"], _cache["equiv"] = {}, {}
    return _cache["bonos"], _cache["equiv"]


def especies():
    """Todas las especies con cronograma conocido: en pesos y dolarizadas."""
    bonos, equiv = cargar()
    out = {}
    for tk in bonos:
        out[tk] = {"cronograma": tk, "moneda": "ARS"}
    for esp, base in equiv.items():
        if base in bonos:
            out[esp] = {"cronograma": base,
                        "moneda": "USD" if esp.endswith(("D", "C")) else "ARS"}
    return out


# -- MEP ---------------------------------------------------------------

def calcular_mep(cot, par_pesos="AL30", par_usd="AL30D"):
    """Devuelve los dos tipos de cambio implícitos y el punto medio.

    - comprar_usd: pesos que te cuesta cada dólar (comprás el bono en pesos
      al ask y vendés la especie D al bid).
    - vender_usd: pesos que recibís por cada dólar (vendés en pesos al bid
      y recomprás la D al ask).
    """
    a = cot.get(par_pesos) or {}
    b = cot.get(par_usd) or {}
    ask_p, bid_p = a.get("venta") or 0, a.get("compra") or 0
    ask_d, bid_d = b.get("venta") or 0, b.get("compra") or 0

    comprar = (ask_p / bid_d) if (ask_p and bid_d) else 0
    vender = (bid_p / ask_d) if (bid_p and ask_d) else 0

    medio = 0
    if a.get("ref") and b.get("ref"):
        medio = a["ref"] / b["ref"]

    return {
        "par": "%s/%s" % (par_pesos, par_usd),
        "comprar_usd": comprar or medio,
        "vender_usd": vender or medio,
        "medio": medio,
        "completo": bool(comprar and vender),
    }


# -- tabla -------------------------------------------------------------

def _tir(esp_cfg, precio, liq, filas):
    if not precio:
        return None
    r = RF.tir(precio, esp_cfg, liq, filas)
    return r * 100 if r is not None else None


def fila(simbolo, info, cot, mep, liq=None):
    """Una fila de la tabla, con TIR en cada punta."""
    liq = liq or date.today()
    bonos, _ = cargar()
    cfg = bonos.get(info["cronograma"])
    if not cfg:
        return None

    bid = cot.get("compra") or 0
    ask = cot.get("venta") or 0
    last = cot.get("ultimo") or 0

    if info["moneda"] == "USD":
        bid_usd, ask_usd, last_usd = bid, ask, last
        tc_bid = tc_ask = 1.0
    else:
        # el bid lo cobrás en pesos: para llevarlo a dólares tenés que comprarlos
        tc_bid = mep.get("comprar_usd") or 0
        # el ask lo pagás en pesos: los conseguiste vendiendo dólares
        tc_ask = mep.get("vender_usd") or 0
        tc_med = mep.get("medio") or 0
        bid_usd = bid / tc_bid if tc_bid else 0
        ask_usd = ask / tc_ask if tc_ask else 0
        last_usd = last / tc_med if tc_med else 0

    filas_flujo = RF.flujo(cfg, liq)
    tir_bid = _tir(cfg, bid_usd, liq, filas_flujo)
    tir_ask = _tir(cfg, ask_usd, liq, filas_flujo)
    tir_last = _tir(cfg, last_usd, liq, filas_flujo)

    # la MD ordena la tabla: se calcula con el last, que es mas estable
    ref = tir_last if tir_last is not None else (
        tir_ask if tir_ask is not None else tir_bid)
    md = None
    if ref is not None:
        precio_ref = last_usd or ask_usd or bid_usd
        _, md = RF.duration(precio_ref, cfg, liq, ref / 100.0, filas_flujo)

    return {
        "simbolo": simbolo,
        "moneda": info["moneda"],
        "cronograma": info["cronograma"],
        "bid": bid, "ask": ask, "last": last,
        "bid_usd": bid_usd, "ask_usd": ask_usd,
        "q_bid": cot.get("vol_compra") or 0,
        "q_ask": cot.get("vol_venta") or 0,
        "tir_bid": tir_bid,
        "tir_ask": tir_ask,
        "tir_last": tir_last,
        "md": md,
        "vencimiento": str(cfg["vencimiento"])[:10],
    }


def tabla(cot, liq=None, par_mep=("AL30", "AL30D")):
    """Todas las especies conocidas que tengan precio, ordenadas por MD."""
    liq = liq or date.today()
    mep = calcular_mep(cot, *par_mep)
    filas = []
    for sim, info in especies().items():
        c = cot.get(sim)
        if not c or not (c.get("compra") or c.get("venta") or c.get("ultimo")):
            continue
        try:
            f = fila(sim, info, c, mep, liq)
        except Exception as e:
            log.warning("%s: %s", sim, e)
            continue
        if f:
            filas.append(f)

    filas.sort(key=lambda f: (f["md"] is None, f["md"] or 0, f["simbolo"]))
    return {"mep": mep, "filas": filas,
            "liquidacion": liq.isoformat(),
            "sin_precio": [s for s in especies() if s not in cot]}


def detalle(simbolo, cot, liq=None, par_mep=("AL30", "AL30D")):
    """Lo que se muestra al tocar el ticker."""
    liq = liq or date.today()
    esps = especies()
    info = esps.get(simbolo)
    if not info:
        return None
    bonos, _ = cargar()
    cfg = bonos[info["cronograma"]]

    mep = calcular_mep(cot, *par_mep)
    f = fila(simbolo, info, cot.get(simbolo) or {}, mep, liq)
    if not f:
        return None

    precio_usd = f["ask_usd"] or f["bid_usd"] or 0
    m = RF.metricas(cfg, precio_usd, liq) if precio_usd else {}
    flujo = RF.flujo(cfg, liq)

    residual = m.get("residual") or RF.residual(cfg, liq)
    corrido = m.get("interes_corrido") or RF.interes_corrido(cfg, liq)
    tecnico = residual + corrido
    cupon = m.get("cupon_vigente") or 0

    return {
        "simbolo": simbolo,
        "nombre": cfg.get("nombre"),
        "ley": cfg.get("ley"),
        "moneda_flujo": cfg.get("moneda"),
        "aviso": cfg.get("verificar"),
        "fila": f,
        "vencimiento": str(cfg["vencimiento"])[:10],
        "proximo_pago": m.get("proximo_pago"),
        "residual": residual,
        "interes_corrido": corrido,
        "valor_tecnico": tecnico,
        "paridad": (precio_usd / tecnico * 100) if tecnico else None,
        "cupon_vigente": cupon,
        "current_yield": (residual * cupon / 100.0 / precio_usd * 100)
                         if precio_usd else None,
        "duration": m.get("duration"),
        "md": f["md"],
        "años_al_vto": m.get("años_al_vto"),
        "spread_tir": (f["tir_bid"] - f["tir_ask"])
                      if (f["tir_bid"] is not None and f["tir_ask"] is not None)
                      else None,
        "flujo": [{
            "fecha": x["fecha"].isoformat(),
            "renta": x["renta"],
            "amortizacion": x["amortizacion"],
            "total": x["total"],
            "residual": x["residual_previo"],
        } for x in flujo],
    }
