"""Circuitos de arbitraje entre monedas y bonos.

Dos formas de cerrar un circuito:

- **Desde efectivo**: se arranca con pesos, MEP o cable, se pasa por dos
  bonos y se vuelve a la misma moneda. Lo que se gana es un porcentaje.

- **Desde un bono**: se vende lo que se tiene, se pasa por otro bono y se
  recompra el original. Lo que se gana son nominales del mismo bono, que
  es como Alejandro mide la posición.

Cada especie liquida en una moneda: el ticker pelado en pesos, el que
termina en D en dólar MEP y el que termina en C en cable. Un "salto" es
comprar una especie y vender otra del mismo bono, lo que convierte una
moneda en otra.
"""

import logging

log = logging.getLogger("circuitos")

MONEDAS = ("ARS", "MEP", "CABLE")
NOMBRE = {"ARS": "Pesos", "MEP": "MEP", "CABLE": "Cable"}


def _especie(bono, moneda):
    return bono if moneda == "ARS" else bono + ("D" if moneda == "MEP" else "C")


def _punta(cot, simbolo, lado):
    """(precio, cantidad) de la punta. lado: 'compra' vende contra el bid,
    'venta' compra contra el ask."""
    c = cot.get(simbolo) or {}
    if lado == "compra":
        return (c.get("compra") or 0), (c.get("vol_compra") or 0)
    return (c.get("venta") or 0), (c.get("vol_venta") or 0)


def _costo(comisiones, moneda):
    """Costo porcentual de una pata, en tanto por uno."""
    c = comisiones or {}
    base = c.get("bonos", c.get("general", 0)) or 0
    derechos = c.get("derechos_mercado", 0) or 0
    return (float(base) + float(derechos)) / 100.0


def _saltar(cot, bono, desde, hacia, comisiones):
    """Convierte una moneda en otra usando un bono.

    Compra la especie de la moneda de origen y vende la de destino. El
    resultado es cuántas unidades de destino salen por cada unidad de
    origen, y cuántos nominales admite el tramo.
    """
    compra = _especie(bono, desde)
    venta = _especie(bono, hacia)
    p_compra, q_compra = _punta(cot, compra, "venta")    # pago el ask
    p_venta, q_venta = _punta(cot, venta, "compra")      # cobro el bid
    if not (p_compra and p_venta and q_compra and q_venta):
        return None

    costo = _costo(comisiones, desde) + _costo(comisiones, hacia)
    # por cada unidad de la moneda de origen compro 1/p_compra nominales,
    # y cada nominal me da p_venta unidades de destino
    tasa = (p_venta / p_compra) * (1 - costo)
    nominales = min(q_compra, q_venta)
    return {"bono": bono, "compra": compra, "venta": venta,
            "p_compra": p_compra, "p_venta": p_venta,
            "tasa": tasa, "nominales": nominales,
            "limite": compra if q_compra <= q_venta else venta}


def _mejor_salto(cot, bonos, desde, hacia, comisiones, excluir=None):
    """El bono que mejor convierte una moneda en otra."""
    mejor = None
    for b in bonos:
        if excluir and b == excluir:
            continue
        s = _saltar(cot, b, desde, hacia, comisiones)
        if s and (not mejor or s["tasa"] > mejor["tasa"]):
            mejor = s
    return mejor


def desde_efectivo(cot, bonos, moneda, comisiones):
    """Circuitos que salen de una moneda y vuelven a ella.

    Devuelve uno por cada moneda intermedia posible.
    """
    out = []
    for medio in MONEDAS:
        if medio == moneda:
            continue
        ida = _mejor_salto(cot, bonos, moneda, medio, comisiones)
        if not ida:
            continue
        vuelta = _mejor_salto(cot, bonos, medio, moneda, comisiones,
                              excluir=ida["bono"])
        if not vuelta:
            continue

        tasa = ida["tasa"] * vuelta["tasa"]
        # cuántos nominales del primer bono admite el circuito entero:
        # la vuelta limita en su propia moneda, hay que traerlo a la ida
        tope_vuelta = vuelta["nominales"] * vuelta["p_compra"] / ida["p_venta"]
        nominales = min(ida["nominales"], tope_vuelta)
        limite = ida["limite"] if ida["nominales"] <= tope_vuelta \
            else vuelta["limite"]

        out.append({
            "tipo": "efectivo",
            "origen": moneda,
            "medio": medio,
            "resultado_pct": (tasa - 1) * 100,
            "nominales": nominales,
            "limite": limite,
            "patas": [ida, vuelta],
        })
    out.sort(key=lambda x: -x["resultado_pct"])
    return out


def desde_bono(cot, bonos, bono, comisiones):
    """Circuitos que venden un bono, pasan por otro y lo recompran.

    Lo que se gana son nominales del bono original.
    """
    out = []
    for vender_en in MONEDAS:
        for volver_en in MONEDAS:
            esp_venta = _especie(bono, vender_en)
            esp_compra = _especie(bono, volver_en)
            p_venta, q_venta = _punta(cot, esp_venta, "compra")
            p_compra, q_compra = _punta(cot, esp_compra, "venta")
            if not (p_venta and p_compra and q_venta and q_compra):
                continue

            # el intermedio convierte la moneda de venta en la de recompra
            if vender_en == volver_en:
                # mismo destino: el intermedio tiene que dar la vuelta
                # completa por otra moneda, si no no hay nada que ganar
                mejores = []
                for medio in MONEDAS:
                    if medio == vender_en:
                        continue
                    a = _mejor_salto(cot, bonos, vender_en, medio,
                                     comisiones, excluir=bono)
                    b = _mejor_salto(cot, bonos, medio, volver_en,
                                     comisiones, excluir=bono)
                    if a and b:
                        mejores.append((a["tasa"] * b["tasa"], [a, b]))
                if not mejores:
                    continue
                tasa_medio, patas_medio = max(mejores, key=lambda x: x[0])
            else:
                s = _mejor_salto(cot, bonos, vender_en, volver_en,
                                 comisiones, excluir=bono)
                if not s:
                    continue
                tasa_medio, patas_medio = s["tasa"], [s]

            costo = _costo(comisiones, vender_en) + _costo(comisiones, volver_en)
            # 1 nominal -> p_venta de moneda -> intermedio -> recompra
            nominales_finales = (p_venta * tasa_medio / p_compra) * (1 - costo)
            ganancia = (nominales_finales - 1) * 100
            if ganancia <= -50:      # ruido de puntas rotas
                continue

            # cuántos nominales del bono original admite el circuito:
            # se arrastra la cantidad de una pata a la siguiente
            tope = q_venta
            moneda_actual = p_venta          # unidades por nominal original
            for p in patas_medio:
                # el tramo admite p["nominales"] del bono intermedio, que
                # equivalen a p["nominales"]*p_compra unidades de entrada
                cabe = p["nominales"] * p["p_compra"] / moneda_actual
                tope = min(tope, cabe)
                moneda_actual *= p["tasa"]
            tope = min(tope, q_compra * p_compra / moneda_actual)

            out.append({
                "tipo": "bono",
                "bono": bono,
                "vender_en": vender_en,
                "volver_en": volver_en,
                "resultado_pct": ganancia,
                "nominales": tope,
                "limite": esp_venta if q_venta <= q_compra else esp_compra,
                "patas": [{"bono": bono, "venta": esp_venta,
                           "p_venta": p_venta, "nominales": q_venta}] +
                         patas_medio +
                         [{"bono": bono, "compra": esp_compra,
                           "p_compra": p_compra, "nominales": q_compra}],
            })
    out.sort(key=lambda x: -x["resultado_pct"])
    return out


def analizar(cot, bonos, tengo, comisiones, umbral_pct=0.0):
    """Todos los circuitos ejecutables con lo que hay declarado.

    tengo: {"monedas": ["ARS", "MEP"], "bonos": ["AO29"]}
    """
    monedas = [m for m in (tengo or {}).get("monedas", []) if m in MONEDAS]
    # un bono propio entra aunque no tenga las tres especies: los saltos
    # que necesiten la que falta se descartan solos al no haber punta
    mis_bonos = [b for b in (tengo or {}).get("bonos", []) if b]

    grupos = []
    for m in monedas:
        c = desde_efectivo(cot, bonos, m, comisiones)
        if c:
            grupos.append({"desde": NOMBRE[m], "clave": m,
                           "es_bono": False, "circuitos": c})
    for b in mis_bonos:
        c = desde_bono(cot, bonos, b, comisiones)
        if c:
            grupos.append({"desde": b, "clave": b,
                           "es_bono": True, "circuitos": c[:4]})

    hay = any(x["resultado_pct"] >= umbral_pct
              for g in grupos for x in g["circuitos"])
    return {"grupos": grupos, "hay_oportunidad": hay,
            "umbral_pct": umbral_pct,
            "sin_comisiones": not _costo(comisiones, "ARS")}
