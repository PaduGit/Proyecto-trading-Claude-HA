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
    "hard_dollar": "Dólar",
    "tasa_variable": "Tasa $",
    "cuotas": "Tasa $",
}
ETIQUETAS = {
    "cedears": "CEDEARs", "acciones": "Acciones", "fci": "FCI",
    "otros": "Otros",
}


def base_de(tipo):
    return 100.0 if (tipo or "") in BASE_100 else 1.0


def _exposicion(t, bonos_cfg):
    """La moneda en la que rinde la posicion."""
    tipo = (t.get("tipo") or "otros").lower()
    if tipo == "moneda":
        return "Dólar" if t["simbolo"] in ("MEP", "CABLE") else "Tasa $"
    b = (bonos_cfg or {}).get(t["simbolo"])
    if b:
        ajuste = (b.get("ajuste") or "").lower()
        if ajuste in EXPOSICION:
            return EXPOSICION[ajuste]
        clase = (b.get("tipo") or "").lower()
        if clase in EXPOSICION:
            return EXPOSICION[clase]
        if (b.get("moneda") or "").upper() == "USD":
            return "Dólar"
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
