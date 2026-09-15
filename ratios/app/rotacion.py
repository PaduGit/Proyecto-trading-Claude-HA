"""De la señal a la orden: cuantos entran por cada uno que sale.

Un canje de curva y un par de ratios proponen lo mismo -salir de una
especie y entrar en otra- y hasta ahora los dos se quedaban en el
porcentaje. La cuenta que falta es siempre la misma, asi que vive en un
solo lugar y la usan las dos pantallas.

Tres cosas que no son obvias y son de donde salen los errores:

- **Se vende al bid y se compra al ask.** Son las dos puntas que se van
  a tocar. Usar el precio medio da una orden que no se puede ejecutar.
- **Las dos puntas se llevan a precio por unidad antes de dividir.** Un
  bono cotiza por cada 100 nominales y un CEDEAR por unidad: sin esto el
  resultado se va por un factor de 100, que es la trampa recurrente de
  este proyecto.
- **La comision de compra se paga sobre lo que se compra**, asi que no
  se descuenta del neto: se despeja. Con el neto N y el costo c, lo que
  entra es N / (precio x (1 + c)), no (N - N x c) / precio.

Lo que cotiza en dolares se pasa a pesos al MEP para poder comparar las
dos puntas con un solo numero. Si hace falta el MEP y no hay, no se
devuelve una orden a medias: se devuelve el motivo.
"""

import logging

log = logging.getLogger("rotacion")

# Los mismos tipos que cotizan por lamina en el resto de la app.
BASE_100 = ("bonos", "letras", "on", "bcra")

# El panel de cotizaciones nombra los instrumentos como los pide la API
# de IOL y la tenencia los guarda con los nombres de la app. Sin esta
# traduccion, un bono que todavia no se tiene queda sin tipo, cae en base
# 1 y el resultado se va por 100: es la trampa de siempre.
PANEL_A_TIPO = {
    "titulospublicos": "bonos",
    "letras": "letras",
    "obligacionesnegociables": "on",
    "acciones": "acciones",
    "cedears": "cedears",
    "opciones": "opciones",
    "cauciones": "cauciones",
    "fci": "fci",
}


def _base(tipo):
    return 100.0 if (tipo or "").lower() in BASE_100 else 1.0


def _es_usd(cot):
    return "dolar" in ((cot or {}).get("moneda") or "").lower() \
        or (cot or {}).get("moneda", "").upper() in ("USD", "US$")


def _tipo_de(simbolo, cot, tenencias):
    """El tipo de instrumento, de la tenencia primero y del panel despues.

    La tenencia lo tiene cargado para lo que se tiene; para la especie
    que entra -que por definicion todavia no se tiene- queda el que
    informa el panel de cotizaciones.
    """
    for t in tenencias or []:
        if (t.get("simbolo") or "").upper() == simbolo and t.get("tipo"):
            return (t["tipo"] or "").lower()
    inst = ((cot.get(simbolo) or {}).get("instrumento") or "").lower()
    if inst:
        return PANEL_A_TIPO.get(inst, inst)
    # Ultimo recurso: la foto historica de la tenencia, que es la que usa
    # el ledger para las especies que ya no estan.
    try:
        import db
        b = db.base_cotizacion(simbolo)
    except Exception:
        b = None
    return "bonos" if b == 100.0 else ("acciones" if b == 1.0 else None)


def saldo_de(simbolo, tenencias):
    """Cuanto hay de una especie y en que brokers."""
    total, brokers = 0.0, {}
    for t in tenencias or []:
        if (t.get("simbolo") or "").upper() != simbolo:
            continue
        c = t.get("cantidad") or 0
        total += c
        if c:
            brokers[t.get("broker")] = c
    return total, brokers


def calcular(sale, entra, cantidad, cot, tenencias, comisiones=None,
             derechos=None, iva_pct=0, mep=None):
    """La orden concreta de una rotacion.

    `cantidad` en None significa toda la tenencia de la especie que sale.
    Devuelve un dict con la orden y su desglose, o con `error` si no se
    puede armar. Nunca devuelve una orden incompleta: media orden se
    ejecuta igual de mal que una equivocada.
    """
    import costos

    sale = (sale or "").strip().upper()
    entra = (entra or "").strip().upper()
    if not sale or not entra or sale == entra:
        return {"error": "Hacen falta dos especies distintas."}

    saldo, brokers = saldo_de(sale, tenencias)
    if cantidad in (None, ""):
        cantidad = saldo
    try:
        cantidad = float(cantidad)
    except (TypeError, ValueError):
        return {"error": "Cantidad inválida."}
    if cantidad <= 0:
        return {"error": "No hay nominales de %s para rotar." % sale}

    c_sale, c_entra = cot.get(sale) or {}, cot.get(entra) or {}
    p_sale = c_sale.get("compra") or 0      # se vende contra el bid
    p_entra = c_entra.get("venta") or 0     # se compra contra el ask
    if not p_sale:
        return {"error": "Sin punta compradora de %s: no hay a qué vender."
                % sale}
    if not p_entra:
        return {"error": "Sin punta vendedora de %s: no hay a qué comprar."
                % entra}

    t_sale = _tipo_de(sale, cot, tenencias)
    t_entra = _tipo_de(entra, cot, tenencias)
    # Nunca suponer la base: la pregunta de siempre con un precio nuevo
    # es en que unidad esta, y adivinarla es de donde salieron los
    # errores por 100 de este proyecto.
    for tk, tp in ((sale, t_sale), (entra, t_entra)):
        if not tp:
            return {"error": "No sé si %s cotiza por lámina o por unidad: "
                             "sin eso la cuenta se va por 100." % tk}
    b_sale, b_entra = _base(t_sale), _base(t_entra)

    # Las dos puntas a pesos por unidad. El MEP solo se exige si alguna
    # cotiza en dolares: pedirlo siempre rompe la rotacion en pesos los
    # dias en que el par del MEP no opera.
    usd_sale, usd_entra = _es_usd(c_sale), _es_usd(c_entra)
    if (usd_sale or usd_entra) and not mep:
        return {"error": "Una de las dos cotiza en dólares y no hay MEP "
                         "para llevarlas a la misma moneda."}
    u_sale = p_sale / b_sale * (mep if usd_sale else 1)
    u_entra = p_entra / b_entra * (mep if usd_entra else 1)

    cs = costos.pct(comisiones, t_sale, derechos, iva_pct)
    ce = costos.pct(comisiones, t_entra, derechos, iva_pct)

    bruto = cantidad * u_sale
    costo_venta = bruto * cs
    neto = bruto - costo_venta
    # La comision de compra se despeja, no se resta: se paga sobre lo
    # que efectivamente se compra.
    cant_entra = neto / (u_entra * (1 + ce))
    costo_compra = cant_entra * u_entra * ce
    # Al mas cercano, y en nominales enteros.
    cant_entra_r = float(round(cant_entra))

    avisos = []
    if not cant_entra_r:
        return {"error": "Con esa cantidad no entra ni un nominal de %s."
                % entra}
    if cantidad > saldo:
        avisos.append("Estás rotando %s nominales y tenés %s."
                      % (_ent(cantidad), _ent(saldo)))
    if not cs:
        avisos.append("Sin comisión configurada para %s: el costo de la "
                      "venta va en cero." % (t_sale or "ese instrumento"))
    if not ce:
        avisos.append("Sin comisión configurada para %s: el costo de la "
                      "compra va en cero." % (t_entra or "ese instrumento"))

    q_sale = c_sale.get("vol_compra") or 0
    q_entra = c_entra.get("vol_venta") or 0
    if q_sale and q_sale < cantidad:
        avisos.append("La punta compradora de %s tiene %s nominales: no "
                      "alcanza para vender %s de una."
                      % (sale, _ent(q_sale), _ent(cantidad)))
    if q_entra and q_entra < cant_entra_r:
        avisos.append("La punta vendedora de %s tiene %s nominales: no "
                      "alcanza para comprar %s de una."
                      % (entra, _ent(q_entra), _ent(cant_entra_r)))
    if c_sale.get("punta_vieja") is False or c_entra.get("punta_vieja") is False:
        avisos.append("Alguna punta es de antes del cierre: el precio no "
                      "es ejecutable ahora.")

    return {
        "sale": sale, "entra": entra,
        "cantidad_sale": cantidad,
        "cantidad_entra": cant_entra_r,
        "cantidad_entra_exacta": cant_entra,
        # Cuantos entran por cada uno que sale: es el mismo numero que
        # muestra el panel, para poder compararlo de un vistazo.
        "ratio": (cant_entra_r / cantidad) if cantidad else None,
        "saldo": saldo, "brokers": brokers,
        "precio_sale": p_sale, "precio_entra": p_entra,
        "base_sale": b_sale, "base_entra": b_entra,
        "tipo_sale": t_sale, "tipo_entra": t_entra,
        "moneda_sale": "USD" if usd_sale else "ARS",
        "moneda_entra": "USD" if usd_entra else "ARS",
        "mep": mep if (usd_sale or usd_entra) else None,
        "bruto": bruto,
        "costo_venta": costo_venta, "costo_compra": costo_compra,
        "costo_pct": (cs + ce) * 100,
        "neto": neto,
        "avisos": avisos,
    }


def _ent(v):
    try:
        return "{:,.0f}".format(float(v)).replace(",", ".")
    except (TypeError, ValueError):
        return str(v)
