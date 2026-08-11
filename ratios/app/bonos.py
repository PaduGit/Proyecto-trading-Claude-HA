"""Tabla de bonos: TIR en cada punta, con conversión de pesos según el MEP.

El MEP no es un número único. Si comprás dólares pagás uno y si los vendés
cobrás otro, porque el spread del bono queda adentro. Para que la TIR sea
la que realmente conseguís, cada punta se convierte con el MEP que le toca.
"""

import logging
import os
from datetime import date

import yaml

import cer as CER
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
    for tk, cfg in bonos.items():
        out[tk] = {"cronograma": tk,
                   "moneda": "CER" if (cfg.get("ajuste") or "") == "cer" else "ARS"}
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


def factor_cer(cfg, cer_actual=0):
    """Cuánto se ajustó el capital desde la emisión.

    El precio en pesos dividido por este factor queda expresado en
    unidades CER, que es donde vive el flujo. Descontando ahí, la TIR
    que sale es real: la X de "CER + X%".

    La base sale del BCRA con la fecha de emisión. Si el YAML trae
    cer_base cargado a mano, ese manda.
    """
    if (cfg.get("ajuste") or "").lower() != "cer":
        return 1.0
    base = float(cfg.get("cer_base") or 0)
    if not base:
        try:
            base = CER.base_de(cfg.get("emision")) or 0
        except Exception as e:
            log.debug("CER base: %s", e)
            base = 0
    if not cer_actual:
        try:
            cer_actual = CER.vigente() or 0
        except Exception:
            cer_actual = 0
    if not base or not cer_actual:
        return 0.0
    return float(cer_actual) / base


def fila(simbolo, info, cot, mep, liq=None, cer_actual=0):
    """Una fila de la tabla, con TIR en cada punta."""
    liq = liq or date.today()
    bonos, _ = cargar()
    cfg = bonos.get(info["cronograma"])
    if not cfg:
        return None

    bid = cot.get("compra") or 0
    ask = cot.get("venta") or 0
    last = cot.get("ultimo") or 0

    es_cer = (cfg.get("ajuste") or "").lower() == "cer"

    if es_cer:
        f = factor_cer(cfg, cer_actual)
        if not f:
            return {
                "simbolo": simbolo, "moneda": "CER", "cronograma": info["cronograma"],
                "bid": bid, "ask": ask, "last": last,
                "bid_usd": 0, "ask_usd": 0,
                "q_bid": cot.get("vol_compra") or 0,
                "q_ask": cot.get("vol_venta") or 0,
                "tir_bid": None, "tir_ask": None, "tir_last": None,
                "md": None, "last_viejo": False,
                "falta_cer": True,
                "vencimiento": str(cfg["vencimiento"])[:10],
            }
        bid_usd, ask_usd, last_usd = bid / f, ask / f, last / f
    elif info["moneda"] == "USD":
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
        "moneda": "CER" if es_cer else info["moneda"],
        "falta_cer": False,
        "cronograma": info["cronograma"],
        "bid": bid, "ask": ask, "last": last,
        "bid_usd": bid_usd, "ask_usd": ask_usd,
        "q_bid": cot.get("vol_compra") or 0,
        "q_ask": cot.get("vol_venta") or 0,
        "tir_bid": tir_bid,
        "tir_ask": tir_ask,
        "tir_last": tir_last,
        "last_viejo": bool(cot.get("fecha") and str(cot["fecha"])[:10] <
                           liq.isoformat()),
        "md": md,
        "vencimiento": str(cfg["vencimiento"])[:10],
    }


def tabla(cot, liq=None, par_mep=("AL30", "AL30D"), cer_actual=0):
    """Todas las especies conocidas que tengan precio, ordenadas por MD."""
    liq = liq or date.today()
    mep = calcular_mep(cot, *par_mep)
    filas = []
    for sim, info in especies().items():
        c = cot.get(sim)
        if not c or not (c.get("compra") or c.get("venta") or c.get("ultimo")):
            continue
        try:
            f = fila(sim, info, c, mep, liq, cer_actual)
        except Exception as e:
            log.warning("%s: %s", sim, e)
            continue
        if f:
            filas.append(f)

    _brechas(filas)
    filas.sort(key=lambda f: (f["md"] is None, f["md"] or 0, f["simbolo"]))
    return {"mep": mep, "filas": filas,
            "cer_actual": cer_actual,
            "liquidacion": liq.isoformat(),
            "sin_precio": [s for s in especies() if s not in cot]}


def _brechas(filas):
    """Diferencia de TIR entre la especie D y la C del mismo bono.

    D liquida en dólar MEP y C en cable, así que cada TIR está medida en
    una moneda distinta y no son directamente comparables. Lo que sí
    significa algo es cuánto se separan: es el spread MEP-cable visto
    desde el rendimiento. Cuando un bono se despega del resto, ahí hay algo.
    """
    por_bono = {}
    for f in filas:
        s = f["simbolo"]
        if s.endswith("D") or s.endswith("C"):
            por_bono.setdefault(s[:-1], {})[s[-1]] = f

    for base, par in por_bono.items():
        d, c = par.get("D"), par.get("C")
        if not d or not c:
            continue
        for a, b in ((d, c), (c, d)):
            a["par_dolarizado"] = b["simbolo"]
        # se compara punta contra punta del mismo lado
        if d.get("tir_ask") is not None and c.get("tir_ask") is not None:
            br = c["tir_ask"] - d["tir_ask"]
            d["brecha_cable"] = br
            c["brecha_cable"] = br
        if d.get("ask_usd") and c.get("ask_usd"):
            impl = (d["ask_usd"] / c["ask_usd"] - 1) * 100
            d["cable_pct"] = impl
            c["cable_pct"] = impl


def detalle(simbolo, cot, liq=None, par_mep=("AL30", "AL30D"), cer_actual=0):
    """Lo que se muestra al tocar el ticker."""
    liq = liq or date.today()
    esps = especies()
    info = esps.get(simbolo)
    if not info:
        return None
    bonos, _ = cargar()
    cfg = bonos[info["cronograma"]]

    mep = calcular_mep(cot, *par_mep)
    f = fila(simbolo, info, cot.get(simbolo) or {}, mep, liq, cer_actual)
    if not f:
        return None

    # la brecha necesita la especie hermana (D contra C)
    if simbolo.endswith(("D", "C")):
        otra = simbolo[:-1] + ("C" if simbolo.endswith("D") else "D")
        if otra in esps and cot.get(otra):
            g = fila(otra, esps[otra], cot[otra], mep, liq, cer_actual)
            if g:
                _brechas([f, g])

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
        "ajuste": cfg.get("ajuste"),
        "cer_base": cfg.get("cer_base"),
        "factor_cer": factor_cer(cfg, cer_actual) or None,
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


# =====================================================================
#  Rulo: tipos de cambio implícitos en cada bono
# =====================================================================

def _tc(pesos, dolarizada):
    """Los dos tipos de cambio que salen de un bono contra su especie D o C.

    - comprar: pesos por dólar si comprás el bono en pesos (ask) y vendés
      la especie dolarizada (bid).
    - vender: pesos que recibís por dólar si hacés el camino inverso.
    """
    ask_p = (pesos or {}).get("venta") or 0
    bid_p = (pesos or {}).get("compra") or 0
    ask_d = (dolarizada or {}).get("venta") or 0
    bid_d = (dolarizada or {}).get("compra") or 0
    return {
        "comprar": (ask_p / bid_d) if (ask_p and bid_d) else None,
        "vender": (bid_p / ask_d) if (bid_p and ask_d) else None,
        "q_comprar": min((pesos or {}).get("vol_venta") or 0,
                         (dolarizada or {}).get("vol_compra") or 0),
        "q_vender": min((pesos or {}).get("vol_compra") or 0,
                        (dolarizada or {}).get("vol_venta") or 0),
    }


def rulo(cot, umbral_pct=0.6):
    """Tipos de cambio implícitos por bono y el ciclo más conveniente.

    Si el bono más barato para comprar dólares está por debajo del más caro
    para venderlos, hay un rulo: comprás por uno y vendés por el otro.
    """
    bonos, _ = cargar()
    filas = []
    for base in bonos:
        p = cot.get(base)
        if not p:
            continue
        f = {"bono": base}
        for letra, clave in (("D", "mep"), ("C", "cable")):
            esp = base + letra
            if cot.get(esp):
                f[clave] = _tc(p, cot[esp])
                f[clave]["especie"] = esp
        if "mep" in f or "cable" in f:
            # brecha cable/mep del propio bono, con la punta de compra
            m = (f.get("mep") or {}).get("comprar")
            c = (f.get("cable") or {}).get("comprar")
            f["brecha_pct"] = ((c / m - 1) * 100) if (m and c) else None
            filas.append(f)

    def _mejor(clave, direccion, peor=False):
        cand = [(f[clave][direccion], f["bono"]) for f in filas
                if f.get(clave) and f[clave].get(direccion)]
        if not cand:
            return None, None
        return (max(cand) if peor else min(cand))

    ciclos = {}
    for clave in ("mep", "cable"):
        barato, b_bono = _mejor(clave, "comprar")
        caro, c_bono = _mejor(clave, "vender", peor=True)
        if barato and caro:
            ciclos[clave] = {
                "comprar_en": b_bono, "precio_compra": barato,
                "vender_en": c_bono, "precio_venta": caro,
                "diferencia_pct": (caro / barato - 1) * 100,
                "umbral_pct": umbral_pct,
                "hay_rulo": (caro / barato - 1) * 100 >= umbral_pct,
                "mismo_bono": b_bono == c_bono,
            }

    filas.sort(key=lambda f: ((f.get("mep") or {}).get("comprar") or 9e9))
    return {"filas": filas, "ciclos": ciclos}
