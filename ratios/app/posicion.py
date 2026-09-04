"""Medicion por cuotapartes de una estrategia.

Dos cosas que antes estaban mezcladas y aca quedan separadas a proposito:

- **Las cantidades salen de `tenencia`**, que es el saldo real de cada
  broker. Nunca del ledger. Es lo que evita que la tarjeta muestre la
  posicion del dia en que se sembro el grupo y no se mueva mas.
- **El ledger (`estrategia_mov`) se lee solo para medir.** Los aportes y
  retiros emiten y rescatan cuotas al valor del momento; las rotaciones
  cambian la composicion y no el capital, asi que no tocan la cuota.

La vara es el `ticker_base` de la estrategia: cuantos nominales de ese
titulo equivale todo lo que hay. Si se rota TX28 -> TZXD8 -> TX31, la
medicion sigue siendo en TX28 aunque ya no se tenga.
"""

import logging
from datetime import datetime

import db
from cartera import base_de

log = logging.getLogger("posicion")

TIPOS = ("rotacion", "aporte", "retiro")

# Contra que se mide cada familia. No es una preferencia de pantalla: una
# rotacion de par gana nominales y no pesos, y una reserva de valor puede
# ganar 80% en pesos y aun asi haber perdido contra el dolar.
VARA = {
    "par": "nominales",
    "curva": "nominales",
    "reserva_renta_fija": "indice",
    "tecnica": "ppc",
    "opciones": "riesgo",
}


# -- saldos ------------------------------------------------------------

def saldos(eid):
    """Cantidad actual por especie, sumando los brokers.

    El detalle por broker va igual: la misma especie en dos cuentas es
    una sola posicion, pero para operar hay que saber donde esta.
    """
    por_sim = {}
    for f in db.tenencia_de_estrategia(eid):
        d = por_sim.setdefault(f["simbolo"], {
            "cantidad": 0.0, "tipo": f["tipo"], "brokers": {}})
        d["cantidad"] += f["cantidad"] or 0
        # El broker que quedo en cero no se lista: despues de transferir,
        # la fila sigue existiendo y ensuciaba la tarjeta con un "ECO 0".
        if f["cantidad"]:
            d["brokers"][f["broker"]] = f["cantidad"]
        if not d["tipo"]:
            d["tipo"] = f["tipo"]
    return {k: v for k, v in por_sim.items() if abs(v["cantidad"]) > 1e-9}


def _base_cot(tk, sal=None):
    """100 si cotiza por lamina, 1 si por unidad.

    El tipo de la tenencia ya viene en los saldos; solo se va a la base
    cuando la especie no esta mas, que pasa con el ticker base despues de
    rotar.
    """
    t = ((sal or {}).get(tk) or {}).get("tipo")
    if t:
        return base_de((t or "").lower())
    return db.base_cotizacion(tk) or 1.0


# -- equivalente en el ticker base -------------------------------------

def equivalente(base, sal, precios):
    """Toda la posicion llevada a nominales del base, con precios de hoy.

    Devuelve (equivalente, detalle por especie, faltantes). Un bono
    cotiza por cada 100 nominales y un CEDEAR por unidad: sin llevar los
    dos precios a la misma base el cociente se va por un factor de 100.
    """
    # Sin ticker base la vara es el peso: precio y base en 1 dejan la
    # cuenta en valor de mercado.
    p_base = precios.get(base) if base else 1.0
    if not p_base:
        return None, {}, [base]
    b_base = _base_cot(base, sal) if base else 1.0

    total, detalle, faltan = 0.0, {}, []
    for tk, d in sal.items():
        cant = d["cantidad"]
        if base and tk == base:
            eq = cant
        else:
            p = precios.get(tk)
            if not p:
                faltan.append(tk)
                detalle[tk] = {"cantidad": cant, "equivalente": None,
                               "precio": None, "brokers": d["brokers"]}
                continue
            eq = cant * (p / _base_cot(tk, sal)) / (p_base / b_base)
        detalle[tk] = {"cantidad": cant, "equivalente": eq,
                       "precio": precios.get(tk), "brokers": d["brokers"]}
        total += eq
    return total, detalle, faltan


def equiv_de(tk, cant, base, precios, sal=None):
    """Cuantos nominales del base equivale una cantidad de `tk`.

    Sirve para el `ratio_base` de un aporte o un retiro cargado a mano,
    que despues se puede corregir: el precio de hoy no siempre es el del
    dia en que entro la plata.
    """
    if not cant:
        return None
    if base and tk == base:
        return cant
    p = precios.get(tk)
    p_base = precios.get(base) if base else 1.0
    if not (p and p_base):
        return None
    b_base = _base_cot(base, sal) if base else 1.0
    return cant * (p / _base_cot(tk, sal)) / (p_base / b_base)


# -- cuotapartes -------------------------------------------------------

def _serie_cuota(eid):
    """Valor de la cuota en cada momento en que se lo puede conocer.

    Solo los aportes y los retiros dejan medido cuanto valia la posicion
    justo antes (`equiv_antes`), que es a lo que se emiten o rescatan las
    cuotas. Entre dos de ellos no hay dato: el valor de la cuota se mueve
    con el mercado y con las rotaciones, y eso se ve recien en el punto
    de hoy, que se calcula con los precios vigentes.

    Un movimiento sin `ratio_base` no se puede contabilizar y se cuenta
    aparte en vez de descartarse en silencio: era de donde salia el
    "aportado 0" con la tenencia ya sembrada.
    """
    cuotas, valor, sin_medir = 0.0, 1.0, []
    puntos = []
    for m in db.movimientos_estrategia(eid):
        if m["tipo"] not in ("aporte", "retiro"):
            continue
        eq = m["ratio_base"] or 0
        if not eq:
            sin_medir.append(m["id"])
            continue
        antes = m["equiv_antes"]
        if cuotas > 0:
            if antes:
                valor = antes / cuotas
            else:
                # No se puede revaluar la cuota: se emite al ultimo valor
                # conocido, que es un supuesto, y queda avisado.
                sin_medir.append(m["id"])
        puntos.append({"x": m["ts"], "y": valor, "tipo": m["tipo"],
                       "cuotas_antes": cuotas})
        cuotas += (eq / valor) if m["tipo"] == "aporte" else -(eq / valor)
    return cuotas, valor, sin_medir, puntos


def cuotapartes(eid):
    """(cuotas emitidas, ultimo valor conocido, movimientos sin medir)."""
    cuotas, valor, sin_medir, _ = _serie_cuota(eid)
    return cuotas, valor, sin_medir


def aportado(eid):
    """Capital neto puesto, en nominales del ticker base."""
    total = 0.0
    for m in db.movimientos_estrategia(eid):
        if m["tipo"] == "aporte":
            total += m["ratio_base"] or 0
        elif m["tipo"] == "retiro":
            total -= m["ratio_base"] or 0
    return total


# -- resumen y serie ---------------------------------------------------

def resumen(estrategia, precios):
    """Como viene la estrategia: saldo, aportado y rendimiento real.

    El rendimiento es el valor de la cuota contra el inicial, que es 1.
    No se diluye cuando entra plata nueva, que es justo el numero que se
    quiere: mide las rotaciones, no los aportes.
    """
    eid = estrategia["id"]
    base = estrategia.get("ticker_base")
    sal = saldos(eid)
    eq, detalle, faltan = equivalente(base, sal, precios)
    cuotas, valor, sin_medir = cuotapartes(eid)
    ap = aportado(eid)

    # Una rotacion sin confirmar no ensucia nada porque no mueve la
    # cuota. Un aporte o un retiro sin confirmar si: el saldo ya subio o
    # bajo y el capital todavia no.
    pend = [p for p in db.movimientos_propuestos("pendiente", eid)
            if p["tipo"] in ("aporte", "retiro")]

    valor_hoy = (eq / cuotas) if (eq is not None and cuotas > 0) else None
    vara = VARA.get(estrategia.get("familia") or "", "nominales")
    extra = {}
    if vara == "indice":
        extra = _contra_indice(estrategia, valor_hoy, precios)
    elif vara == "ppc":
        extra = _contra_ppc(eid, precios)

    return {
        "estrategia_id": eid,
        "vara": vara,
        "ticker_base": base,
        "tenencia": detalle,
        "faltan_precios": faltan,
        "equivalente": eq,
        "aportado": ap,
        "cuotas": cuotas,
        "valor_cuota": valor_hoy,
        "rendimiento_pct": ((valor_hoy - 1) * 100)
                           if valor_hoy is not None else None,
        "ganancia_nominal": (eq - ap) if eq is not None else None,
        "sin_punto_de_partida": cuotas <= 0,
        "sin_medir": sin_medir,
        "pendientes": len(pend),
        **extra,
    }


def _contra_indice(estrategia, valor_cuota, precios):
    """Cuanto rindio contra el dolar, el CER, la BADLAR o el S&P.

    Ganar 80% en pesos no dice nada si el dolar hizo 95%. Lo unico que
    importa es el cociente: por eso el numero que va grande en la tarjeta
    es `contra_patron_pct` y no el rendimiento propio.
    """
    from cartera import factor_patron
    pat = estrategia.get("patron")
    if not pat:
        return {"patron": None, "nota_patron": "sin patrón declarado"}
    factor, nota = factor_patron(pat, estrategia, precios)
    out = {"patron": pat, "patron_pct": ((factor - 1) * 100) if factor else None,
           "contra_patron_pct": None, "nota_patron": nota}
    if factor and valor_cuota is not None:
        out["contra_patron_pct"] = (valor_cuota / factor - 1) * 100
    return out


def _contra_ppc(eid, precios):
    """Rendimiento contra lo que costo, especie por especie.

    Es la vara de una entrada tecnica: se entro a un precio con un stop y
    un objetivo, y la pregunta es si va ganando, no cuantos nominales de
    otra cosa equivale. Solo mide la parte que tiene PPC cargado.
    """
    valor = costo = 0.0
    sin_ppc = []
    for f in db.tenencia_de_estrategia(eid):
        cant = f["cantidad"] or 0
        if not cant:
            continue
        p = precios.get(f["simbolo"])
        b = base_de((f["tipo"] or "").lower())
        v = cant * p / b if p else None
        ppc = f["ppc"]
        c = cant * ppc / (f["ppc_base"] or b) if ppc else None
        if v is None or not c:
            if not ppc:
                sin_ppc.append(f["simbolo"])
            continue
        valor += v
        costo += c
    return {
        "costo": costo or None,
        "valor": valor or None,
        "resultado_pct": ((valor / costo - 1) * 100) if costo else None,
        "sin_ppc": sorted(set(sin_ppc)),
    }


def curva(estrategia, precios):
    """Serie del valor de la cuota, con el punto de hoy al final."""
    _, _, _, puntos = _serie_cuota(estrategia["id"])
    salida = [{"x": p["x"], "y": p["y"], "tipo": p["tipo"]}
              for p in puntos if p["y"] is not None]
    r = resumen(estrategia, precios)
    if r["valor_cuota"] is not None:
        salida.append({"x": datetime.now().isoformat(timespec="seconds"),
                       "y": r["valor_cuota"], "tipo": "hoy"})
    return salida


# -- carga a mano ------------------------------------------------------

def validar_movimiento(estrategia, d, precios=None):
    """Devuelve (datos_limpios, error).

    Las especies validas son las asignadas a la estrategia, no las del
    grupo: una estrategia puede rotar a un ticker que el grupo no lista,
    y en ese caso se pregunta antes de asignarlo.

    `equiv_antes` se calcula con los precios de ahora, que es lo unico
    que hay para un movimiento cargado a mano.
    """
    precios = precios or {}
    tipo = (d.get("tipo") or "").strip().lower()
    if tipo not in TIPOS:
        return None, "Tipo inválido. Usá rotacion, aporte o retiro."

    base = estrategia.get("ticker_base")
    sal = saldos(estrategia["id"])
    asignadas = set(db.especies_de(estrategia["id"]))

    def _num(v):
        try:
            x = float(v)
            return x if x > 0 else None
        except (TypeError, ValueError):
            return None

    antes, _, _ = equivalente(base, sal, precios)

    if tipo == "rotacion":
        de = (d.get("ticker_de") or "").strip().upper()
        a = (d.get("ticker_a") or "").strip().upper()
        if de not in asignadas:
            return None, "%s no está en esta estrategia." % (de or "El origen")
        if de == a:
            return None, "Origen y destino no pueden ser el mismo ticker."
        cd, ca = _num(d.get("cant_de")), _num(d.get("cant_a"))
        if not cd or not ca:
            return None, "Cargá las dos cantidades."
        hay = (sal.get(de) or {}).get("cantidad", 0)
        if hay + 1e-9 < cd:
            return None, "No tenés %s suficientes: hay %s." % (de, _fmt(hay))
        return {"tipo": tipo, "ticker_de": de, "cant_de": cd,
                "ticker_a": a, "cant_a": ca, "ratio_base": None,
                "equiv_antes": antes,
                "nota": (d.get("nota") or "").strip() or None}, None

    # aporte / retiro
    tk = (d.get("ticker_a") or "").strip().upper()
    if not tk:
        return None, "Falta el ticker."
    cant = _num(d.get("cant_a"))
    if not cant:
        return None, "Cargá la cantidad."
    if tipo == "retiro":
        hay = (sal.get(tk) or {}).get("cantidad", 0)
        if hay + 1e-9 < cant:
            return None, "No tenés %s suficientes: hay %s." % (tk, _fmt(hay))

    # El equivalente propuesto sale del precio de ahora y se puede
    # corregir: la plata pudo haber entrado otro dia.
    eq = _num(d.get("ratio_base")) or equiv_de(tk, cant, base, precios, sal)
    if not eq:
        if not base:
            return None, ("La estrategia no tiene ticker base: sin eso no "
                          "hay en qué medir el aporte.")
        return None, ("Indicá a cuántos %s equivale: falta el precio para "
                      "calcularlo." % base)
    return {"tipo": tipo, "ticker_de": None, "cant_de": None,
            "ticker_a": tk, "cant_a": cant, "ratio_base": eq,
            "equiv_antes": antes,
            "nota": (d.get("nota") or "").strip() or None}, None


def _fmt(v):
    return "{:,.0f}".format(v or 0).replace(",", ".")
