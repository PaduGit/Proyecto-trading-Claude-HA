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
VN = 100.0          # los bonos cotizan por lámina de 100 nominales
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


def _costo(comisiones):
    """Costo porcentual de una pata, en tanto por uno.

    Los circuitos saltan por bonos, que son valores publicos: pagan
    derecho de mercado bajo y estan exentos de IVA. Los derechos y el
    IVA viajan dentro del propio mapa para no arrastrar dos parametros
    mas por cada funcion interna.

    No recibe la moneda: todas las patas son bonos y el costo es el
    mismo. Lo recibia y lo ignoraba, que es peor que no tenerlo: el dia
    que un circuito toque acciones el llamador va a creer que ya estaba
    contemplado.
    """
    import costos
    c = comisiones or {}
    return costos.pct_circuito(c, "bonos", c.get("_derechos"),
                               c.get("_iva_pct"), c.get("_esquema"))


def _monto(nominales, precio, moneda, mep):
    """Plata de una punta llevada a pesos, para poder compararla."""
    m = nominales * precio / VN
    if moneda == "ARS":
        return m
    return m * mep if mep else None


def _chico(comisiones, n1, p1, m1, n2, p2, m2):
    """True si alguna de las dos puntas no llega al mínimo configurado.

    Sin MEP no se puede pasar a pesos una punta en dólares: en ese caso
    no se descarta. No saber cuánto hay no es lo mismo que saber que hay
    poco.
    """
    minimo = (comisiones or {}).get("_min_monto") or 0
    if not minimo:
        return False
    mep = (comisiones or {}).get("_mep")
    for n, p, mon in ((n1, p1, m1), (n2, p2, m2)):
        v = _monto(n, p, mon, mep)
        if v is not None and v < minimo:
            return True
    return False


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
    # Una punta de dos láminas da un ratio que no existe cuando se manda
    # la orden. Es la fuente principal de rulos fantasma.
    if _chico(comisiones, q_compra, p_compra, desde, q_venta, p_venta, hacia):
        return None

    costo = _costo(comisiones) * 2      # una pata de compra y una de venta
    # por cada unidad de la moneda de origen compro 1/p_compra nominales,
    # y cada nominal me da p_venta unidades de destino
    tasa = (p_venta / p_compra) * (1 - costo)
    nominales = min(q_compra, q_venta)
    return {"bono": bono, "compra": compra, "venta": venta,
            "p_compra": p_compra, "p_venta": p_venta,
            "tasa": tasa, "nominales": nominales,
            "limite": compra if q_compra <= q_venta else venta}



def _efectivo(nominales, precio):
    """Plata que mueve una orden. El precio es por lámina de 100 VN."""
    return nominales * precio / VN


def _moneda_de(especie, bono):
    """La moneda en que liquida una especie, por su sufijo."""
    if especie == bono:
        return "ARS"
    return "MEP" if especie.endswith("D") else "CABLE"


def _paso(accion, especie, nominales, precio, moneda):
    """Una orden concreta: qué, cuánto, a qué precio y por cuánta plata."""
    n = int(nominales)          # el mercado no admite fracciones
    return {"accion": accion, "especie": especie, "nominales": n,
            "precio": precio, "importe": _efectivo(n, precio),
            "moneda": moneda}


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

        # desglose sobre el máximo ejecutable: cada pata arranca con lo
        # que salió neto de la anterior. Se redondea hacia abajo desde el
        # primer paso, así el importe inicial es el que se va a operar.
        n1 = int(nominales)
        e0 = _efectivo(n1, ida["p_compra"])
        e1 = e0 * ida["tasa"]
        n2 = int(e1 * VN / vuelta["p_compra"]) if vuelta["p_compra"] else 0
        e2 = _efectivo(n2, vuelta["p_venta"]) * (
            1 - _costo(comisiones) * 2)
        pasos = [
            _paso("Comprar", ida["compra"], n1, ida["p_compra"], moneda),
            _paso("Vender", ida["venta"], n1, ida["p_venta"], medio),
            _paso("Comprar", vuelta["compra"], n2, vuelta["p_compra"], medio),
            _paso("Vender", vuelta["venta"], n2, vuelta["p_venta"], moneda),
        ]

        out.append({
            "tipo": "efectivo",
            "origen": moneda,
            "medio": medio,
            "resultado_pct": (tasa - 1) * 100,
            "nominales": nominales,
            "limite": limite,
            "patas": [ida, vuelta],
            "pasos": pasos,
            "inicial": e0,
            "final": e2,
            "unidad": moneda,
        })
    out.sort(key=lambda x: -x["resultado_pct"])
    return out


def desde_bono(cot, bonos, bono, comisiones):
    """Circuitos de cuatro patas que vuelven al mismo bono.

    Cada especie cotiza en una sola moneda, asi que el propio bono es
    uno de los dos puentes: se lo vende en una moneda, un segundo bono
    trae el importe de vuelta a la otra, y se lo recompra alli.

    Ejemplo: vender AO29D contra dolares, comprar AL30D, vender AL30 en
    pesos, recomprar AO29 en pesos. Lo que se gana son nominales de
    AO29.
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
            if _chico(comisiones, q_venta, p_venta, vender_en,
                      q_compra, p_compra, volver_en):
                continue

            # Vender y recomprar en la misma moneda no es un circuito:
            # es liquidar el bono, hacer un rulo desde esa moneda y
            # volver a entrar. Las dos patas del bono no aportan nada y
            # solo suman comisiones. El bono de origen tiene que ser uno
            # de los dos puentes, no algo que se liquida primero.
            if vender_en == volver_en:
                continue

            s = _mejor_salto(cot, bonos, vender_en, volver_en,
                             comisiones, excluir=bono)
            if not s:
                continue
            tasa_medio, patas_medio = s["tasa"], [s]

            costo = _costo(comisiones) * 2
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

            # desglose sobre el máximo ejecutable
            n0 = int(tope)
            efectivo = _efectivo(n0, p_venta) * (1 - costo)
            pasos = [_paso("Vender", esp_venta, n0, p_venta, vender_en)]
            mon = vender_en
            for p in patas_medio:
                ni = int(efectivo * VN / p["p_compra"]) if p["p_compra"] else 0
                pasos.append(_paso("Comprar", p["compra"], ni,
                                   p["p_compra"], mon))
                mon = _moneda_de(p["venta"], p["bono"])
                pasos.append(_paso("Vender", p["venta"], ni,
                                   p["p_venta"], mon))
                efectivo = _efectivo(ni, p["p_venta"]) * (
                    1 - _costo(comisiones) * 2)
            n_final = int(efectivo * VN / p_compra) if p_compra else 0
            pasos.append(_paso("Comprar", esp_compra, n_final,
                               p_compra, volver_en))

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
                "pasos": pasos,
                "inicial": n0,
                "final": n_final,
                "unidad": bono,
            })
    out.sort(key=lambda x: -x["resultado_pct"])
    return out


def analizar(cot, bonos, tengo, comisiones, umbral_pct=0.0,
             derechos=None, iva_pct=0, esquema=None,
             min_monto=0, mep=None):
    """Todos los circuitos ejecutables con lo que hay declarado.

    tengo: {"monedas": ["ARS", "MEP"], "bonos": ["AO29"]}

    `min_monto` descarta los tramos cuya punta no llegue a esa plata en
    pesos. Un circuito armado sobre una punta de dos láminas se ve en la
    pantalla y no se puede mandar.
    """
    comisiones = dict(comisiones or {})
    comisiones["_derechos"] = derechos or {}
    comisiones["_iva_pct"] = iva_pct
    comisiones["_esquema"] = esquema
    comisiones["_min_monto"] = min_monto or 0
    comisiones["_mep"] = mep

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
            "sin_comisiones": not _costo(comisiones)}
