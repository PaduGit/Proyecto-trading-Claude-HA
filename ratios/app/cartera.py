"""Valuacion de la tenencia a precio de mercado.

No calcula rendimiento de rotacion: eso es posicion.py, que mide por
cuotapartes sobre los movimientos de un grupo. Aca se responde otra cosa,
cuanto vale hoy lo que hay y contra que costo, que es un agregado por
broker y no depende de haber cargado los movimientos.
"""

import logging

log = logging.getLogger("ratios.cartera")

# Los titulos de deuda cotizan por cada 100 nominales; las acciones,
# CEDEARs y cuotapartes por unidad. Confundirlos mete un factor de 100.
BASE_100 = ("bonos", "letras", "on", "bcra")

# Por que moneda rinde cada cosa, que no es la de cotizacion: un hard
# dollar que cotiza en pesos sigue siendo exposicion al dolar.
EXPOSICION = {
    "cer": "CER",
    "dolar_linked": "Dólar linked",
    "hard_dollar": "Hard dollar",
    "tasa_variable": "Tasa $",
    "cuotas": "Tasa $",
}
ETIQUETAS = {
    "cedears": "CEDEARs", "acciones": "Acciones", "fci": "FCI",
    "otros": "Otros",
}


def patron_valor(patron, f=None):
    """El indice contra el que se mide una estrategia, a una fecha.

    El tipo de cambio de entrada no se busca: lo carga el usuario al
    crear la estrategia, porque es el precio al que entro y no una serie
    publicada.
    """
    from datetime import date as _date
    f = f or _date.today()
    try:
        if patron == "cer":
            import cer as C
            return C.valor(f) if f != _date.today() else C.vigente()
        if patron == "dolar":
            import dolar as D
            return D.valor(f) if f != _date.today() else D.vigente()
        if patron == "badlar":
            import badlar as B
            return B.valor(f) if f != _date.today() else B.vigente()
    except Exception as e:
        log.debug("patrón %s al %s: %s", patron, f, e)
    return None


def medir(estrategias_, posiciones):
    """Cuanto rindio cada estrategia y como le fue contra su patron.

    El costo sale del PPC de las especies asignadas, asi que solo se mide
    la parte de la estrategia que lo tiene cargado. La fecha de
    referencia del patron es el alta de la estrategia: si se roto de un
    bono a otro, la especie nueva tiene fecha propia mas reciente pero la
    apuesta empezo antes, y es contra ese momento que hay que medirla.
    """
    por_estr = {}
    for p in posiciones:
        eid = p.get("estrategia_id")
        if eid:
            por_estr.setdefault(eid, []).append(p)

    salida = []
    for e in estrategias_:
        pos = por_estr.get(e["id"]) or []
        valor = sum(p["valor"] for p in pos if p["valor"])
        costo = sum(p["costo"] for p in pos
                    if p["costo"] and p["valor"] is not None)
        medido = sum(p["valor"] for p in pos
                     if p["costo"] and p["valor"] is not None)
        d = {"id": e["id"], "nombre": e["nombre"], "familia": e["familia"],
             "patron": e.get("patron"), "alta": e.get("alta"),
             "especies": len(pos), "valor": valor, "costo": costo or None,
             "rendimiento_pct": ((medido / costo - 1) * 100) if costo else None,
             "patron_pct": None, "contra_patron_pct": None, "nota": None}

        pat = e.get("patron")
        if pat and costo:
            if pat == "tc_entrada":
                # Cargado a mano: es el tipo de cambio al que se entro.
                base = e.get("patron_valor")
                hoy = patron_valor("dolar")
            else:
                base = patron_valor(pat, e.get("alta"))
                hoy = patron_valor(pat)
            if base and hoy:
                d["patron_pct"] = (hoy / base - 1) * 100
                # Lo unico que importa: si le gano o le perdio a la vara.
                d["contra_patron_pct"] = ((medido / costo) / (hoy / base) - 1) * 100
            else:
                d["nota"] = "sin valor del patrón para esa fecha"
        elif pat:
            d["nota"] = "sin PPC cargado en las especies"
        salida.append(d)
    salida.sort(key=lambda x: x["valor"] or 0, reverse=True)
    return salida


def base_de(tipo):
    return 100.0 if (tipo or "") in BASE_100 else 1.0


def _exposicion(t, bonos_cfg):
    """La moneda en la que rinde la posicion."""
    tipo = (t.get("tipo") or "otros").lower()
    if tipo == "moneda":
        return "Hard dollar" if t["simbolo"] in ("MEP", "CABLE") \
            else "Tasa $"
    b = (bonos_cfg or {}).get(t["simbolo"])
    if b:
        ajuste = (b.get("ajuste") or "").lower()
        if ajuste in EXPOSICION:
            return EXPOSICION[ajuste]
        clase = (b.get("tipo") or "").lower()
        if clase in EXPOSICION:
            return EXPOSICION[clase]
        if (b.get("moneda") or "").upper() == "USD":
            return "Hard dollar"
    return ETIQUETAS.get(tipo, "Sin clasificar")


def valuar(tenencias, precios, mep=None, bonos_cfg=None):
    """Arma la cartera valuada.

    `precios` es simbolo -> precio de referencia, en la misma base en la
    que cotiza el instrumento. Una posicion sin precio se informa igual,
    con valor nulo: es preferible a dejarla afuera y mostrar un total que
    parece completo y no lo es.
    """
    filas, faltan = [], []
    for t in tenencias or []:
        tipo = (t.get("tipo") or "otros").lower()
        sim = t["simbolo"]
        cant = float(t.get("cantidad") or 0)
        base = base_de(tipo)
        if tipo == "moneda":
            if sim in ("MEP", "CABLE"):
                valor = cant * mep if mep else None
            else:
                valor = cant
            precio = None
        else:
            precio = precios.get(sim)
            valor = cant * precio / base if precio else None
        if valor is None and tipo != "moneda":
            faltan.append(sim)

        # El PPC puede venir en otra base que el precio: la planilla de un
        # broker suele darlo por unidad y el mercado cotiza por 100.
        ppc = t.get("ppc_ajustado")
        if ppc is None:
            ppc = t.get("ppc")
        ppc_base = t.get("ppc_base") or base
        costo = cant * ppc / ppc_base if ppc else None
        res = (valor - costo) if (valor is not None and costo) else None

        filas.append({
            "broker": t.get("broker"), "simbolo": sim, "tipo": tipo,
            "cantidad": cant, "precio": precio, "valor": valor,
            "ppc": ppc, "costo": costo, "resultado": res,
            "resultado_pct": (res / costo * 100) if (res is not None and costo)
                             else None,
            "exposicion": _exposicion(t, bonos_cfg),
            "estrategia_id": t.get("estrategia_id"),
            "estrategia": t.get("estrategia"),
            "extranjero": t.get("extranjero"),
            "ajuste_supuesto": t.get("ajuste_supuesto"),
        })

    total = sum(f["valor"] for f in filas if f["valor"])
    for f in filas:
        f["peso_pct"] = (f["valor"] / total * 100) if (total and f["valor"]) \
                        else None
    filas.sort(key=lambda f: f["valor"] or 0, reverse=True)

    costo_total = sum(f["costo"] for f in filas
                      if f["costo"] and f["valor"] is not None)
    valor_medido = sum(f["valor"] for f in filas
                       if f["costo"] and f["valor"] is not None)
    return {
        "posiciones": filas,
        "total": total,
        "total_usd": (total / mep) if mep else None,
        "mep": mep,
        # El resultado se mide solo sobre lo que tiene costo cargado y
        # precio: mezclarlo con el resto daria un porcentaje sin sentido.
        "costo_con_dato": costo_total,
        "resultado": (valor_medido - costo_total) if costo_total else None,
        "resultado_pct": ((valor_medido / costo_total - 1) * 100)
                         if costo_total else None,
        "cubierto_pct": (valor_medido / total * 100) if total else None,
        "sin_precio": sorted(set(faltan)),
        "por_exposicion": _agrupar(filas, "exposicion", total),
        "por_broker": _agrupar(filas, "broker", total),
    }


def _agrupar(filas, campo, total):
    acum = {}
    for f in filas:
        if not f["valor"]:
            continue
        acum[f[campo]] = acum.get(f[campo], 0) + f["valor"]
    salida = [{"nombre": k, "valor": v,
               "pct": (v / total * 100) if total else 0}
              for k, v in acum.items()]
    salida.sort(key=lambda x: x["valor"], reverse=True)
    return salida
