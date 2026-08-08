"""Contabilidad en nominales de grupos de tickers rotables.

La idea: si rotás entre ALUA y TXAR, lo que importa no son los pesos sino
cuántos nominales del activo base terminás teniendo. Los aportes y retiros
mueven la marca de referencia para que no se confundan con resultado.
"""

import logging
from datetime import datetime

import db

log = logging.getLogger("posicion")

TIPOS = ("rotacion", "aporte", "retiro")


def tenencia(grupo_id):
    """Cantidad actual por ticker, derivada de los movimientos."""
    saldos = {}
    for m in db.movimientos_de(grupo_id):
        if m["tipo"] == "rotacion":
            if m["ticker_de"]:
                saldos[m["ticker_de"]] = saldos.get(m["ticker_de"], 0.0) - (m["cant_de"] or 0)
            if m["ticker_a"]:
                saldos[m["ticker_a"]] = saldos.get(m["ticker_a"], 0.0) + (m["cant_a"] or 0)
        elif m["tipo"] == "aporte":
            if m["ticker_a"]:
                saldos[m["ticker_a"]] = saldos.get(m["ticker_a"], 0.0) + (m["cant_a"] or 0)
        elif m["tipo"] == "retiro":
            if m["ticker_a"]:
                saldos[m["ticker_a"]] = saldos.get(m["ticker_a"], 0.0) - (m["cant_a"] or 0)
    return {k: v for k, v in saldos.items() if abs(v) > 1e-9}


def base_ajustada(grupo_id):
    """Capital aportado neto, en unidades base. Referencia simple."""
    total = 0.0
    for m in db.movimientos_de(grupo_id):
        if m["tipo"] == "aporte":
            total += (m["ratio_base"] or 0)
        elif m["tipo"] == "retiro":
            total -= (m["ratio_base"] or 0)
    return total


def cuotapartes(grupo_id):
    """Contabilidad por cuotapartes, como un fondo.

    Los aportes emiten cuotas al valor del momento y los retiros las
    rescatan, asi que el valor de la cuota solo se mueve por tus rotaciones.
    Es el numero honesto: no se diluye cuando entra plata nueva.
    """
    cuotas = 0.0
    valor = 1.0
    for m in db.movimientos_de(grupo_id):
        if m["tipo"] not in ("aporte", "retiro"):
            continue
        eq = m["ratio_base"] or 0
        if not eq:
            continue
        antes = m["equiv_antes"]
        if cuotas > 0 and antes:
            valor = antes / cuotas
        if m["tipo"] == "aporte":
            cuotas += eq / valor
        else:
            cuotas -= eq / valor
    return cuotas, valor


def equivalente(grupo, saldos, precios):
    """Convierte toda la tenencia a la unidad base con los precios de hoy.

    precios: dict ticker -> precio de referencia.
    Devuelve (equivalente, detalle_por_ticker, faltantes).
    """
    base = grupo["base"]
    p_base = precios.get(base)
    if not p_base:
        return None, {}, [base]

    total = 0.0
    detalle = {}
    faltan = []
    for tk, cant in saldos.items():
        if tk == base:
            eq = cant
        else:
            p = precios.get(tk)
            if not p:
                faltan.append(tk)
                continue
            eq = cant * p / p_base
        detalle[tk] = {"cantidad": cant, "equivalente": eq,
                       "precio": precios.get(tk)}
        total += eq
    return total, detalle, faltan


def resumen(grupo, precios):
    saldos = tenencia(grupo["id"])
    base_aj = base_ajustada(grupo["id"])
    eq, detalle, faltan = equivalente(grupo, saldos, precios)
    cuotas, _ = cuotapartes(grupo["id"])

    # rendimiento real: valor de la cuota hoy contra el inicial (1.0)
    rend = None
    if eq is not None and cuotas > 0:
        rend = (eq / cuotas - 1) * 100

    return {
        "grupo": grupo,
        "tenencia": detalle,
        "faltan_precios": faltan,
        "equivalente": eq,
        "base_ajustada": base_aj,
        "cuotas": cuotas,
        "valor_cuota": (eq / cuotas) if (eq is not None and cuotas > 0) else None,
        "rendimiento_pct": rend,
        "ganancia_nominal": (eq - base_aj) if eq is not None else None,
    }


def curva(grupo, precios_actuales):
    """Serie del equivalente a lo largo del tiempo.

    Reconstruye la tenencia movimiento a movimiento y la valúa con el ratio
    vigente en ese momento (el que quedó guardado). El último punto usa los
    precios de hoy.
    """
    base = grupo["base"]
    saldos = {}
    puntos = []
    base_aj = 0.0

    for m in db.movimientos_de(grupo["id"]):
        if m["tipo"] == "rotacion":
            if m["ticker_de"]:
                saldos[m["ticker_de"]] = saldos.get(m["ticker_de"], 0.0) - (m["cant_de"] or 0)
            if m["ticker_a"]:
                saldos[m["ticker_a"]] = saldos.get(m["ticker_a"], 0.0) + (m["cant_a"] or 0)
        elif m["tipo"] == "aporte":
            saldos[m["ticker_a"]] = saldos.get(m["ticker_a"], 0.0) + (m["cant_a"] or 0)
            base_aj += (m["ratio_base"] or 0)
        elif m["tipo"] == "retiro":
            saldos[m["ticker_a"]] = saldos.get(m["ticker_a"], 0.0) - (m["cant_a"] or 0)
            base_aj -= (m["ratio_base"] or 0)

        # equivalente al momento del movimiento: usamos el ratio guardado
        # cuando se puede, si no queda pendiente para el punto final
        eq = _equiv_con_movimiento(m, saldos, base)
        puntos.append({
            "x": m["ts"], "y": eq, "base": base_aj, "tipo": m["tipo"],
        })

    eq_hoy, _, _ = equivalente(grupo, tenencia(grupo["id"]), precios_actuales)
    if eq_hoy is not None:
        puntos.append({"x": datetime.now().isoformat(timespec="seconds"),
                       "y": eq_hoy, "base": base_aj, "tipo": "hoy"})
    return [p for p in puntos if p["y"] is not None]


def _equiv_con_movimiento(m, saldos, base):
    """Equivalente aproximado usando el ratio implicito del movimiento."""
    if m["tipo"] == "rotacion" and m["cant_de"] and m["cant_a"]:
        de, a = m["ticker_de"], m["ticker_a"]
        # ratio de -> a implicito en la operacion
        r = m["cant_de"] / m["cant_a"] if m["cant_a"] else None
        if not r:
            return None
        total = 0.0
        for tk, cant in saldos.items():
            if tk == base:
                total += cant
            elif tk == a and de == base:
                total += cant * r
            elif tk == de and a == base:
                total += cant / r
            else:
                return None
        return total
    if m["ratio_base"] is not None:
        # aporte/retiro: sabemos el equivalente que entro o salio, pero no
        # el precio del resto; solo sirve si hay un unico ticker
        if len(saldos) == 1:
            tk = next(iter(saldos))
            if tk == base:
                return saldos[tk]
    return None


def validar_movimiento(grupo, d):
    """Devuelve (datos_limpios, error)."""
    tipo = (d.get("tipo") or "").strip().lower()
    if tipo not in TIPOS:
        return None, "Tipo inválido. Usá rotacion, aporte o retiro."

    tickers = set(grupo["tickers"])

    def _num(v):
        try:
            x = float(v)
            return x if x > 0 else None
        except (TypeError, ValueError):
            return None

    if tipo == "rotacion":
        de = (d.get("ticker_de") or "").strip().upper()
        a = (d.get("ticker_a") or "").strip().upper()
        if de not in tickers or a not in tickers:
            return None, "Los dos tickers tienen que estar en el grupo."
        if de == a:
            return None, "Origen y destino no pueden ser el mismo ticker."
        cd, ca = _num(d.get("cant_de")), _num(d.get("cant_a"))
        if not cd or not ca:
            return None, "Cargá las dos cantidades."
        saldos = tenencia(grupo["id"])
        if saldos.get(de, 0) + 1e-9 < cd:
            return None, ("No tenés %s suficientes: hay %s."
                          % (de, _fmt(saldos.get(de, 0))))
        return {"tipo": tipo, "ticker_de": de, "cant_de": cd,
                "ticker_a": a, "cant_a": ca, "ratio_base": None,
                "nota": (d.get("nota") or "").strip() or None}, None

    # aporte / retiro
    tk = (d.get("ticker_a") or "").strip().upper()
    if tk not in tickers:
        return None, "El ticker tiene que estar en el grupo."
    cant = _num(d.get("cant_a"))
    if not cant:
        return None, "Cargá la cantidad."

    eq = _num(d.get("ratio_base"))
    if not eq:
        return None, ("Indicá a cuántos %s equivale, para ajustar la base."
                      % grupo["base"])
    if tipo == "retiro":
        saldos = tenencia(grupo["id"])
        if saldos.get(tk, 0) + 1e-9 < cant:
            return None, ("No tenés %s suficientes: hay %s."
                          % (tk, _fmt(saldos.get(tk, 0))))
    return {"tipo": tipo, "ticker_de": None, "cant_de": None,
            "ticker_a": tk, "cant_a": cant, "ratio_base": eq,
            "nota": (d.get("nota") or "").strip() or None}, None


def _fmt(v):
    return "{:,.0f}".format(v or 0).replace(",", ".")
