"""Reconstruye la historia de cada posicion desde las operaciones de IOL.

El portafolio da cantidades y nada mas: no dice desde cuando tenes cada
cosa. Eso solo esta en `/api/v2/operaciones`, y sin la fecha de alta el
ajuste por evento societario es un supuesto y una reserva de valor no se
puede medir desde el origen.

Lo que este modulo NO hace: escribir. Devuelve lo reconstruido y lo
compara contra la tenencia; que se guarda y que no lo decide quien
llama, y solo donde las cantidades cierran.
"""

import logging

log = logging.getLogger("operaciones")

# Los que mueven nominales. El resto -Pago de Renta, de Dividendos, de
# Amortizacion- son cobros: entra plata, la tenencia no cambia.
ENTRAN = ("compra", "suscripción fci", "suscripcion fci",
          "suscripción otc", "suscripcion otc")
SALEN = ("venta", "rescate fci")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def limpiar(o):
    """Una operacion en la forma que sirve, o None si no mueve nominales.

    Se usan `cantidadOperada`, `precioOperado` y `montoOperado` y no
    `cantidad`, `precio` ni `monto`: los primeros son lo ejecutado, los
    segundos son lo que se pidio y a veces vienen en pesos en vez de
    nominales. Una orden por importe deja `cantidad` en 4.948.920,85
    habiendo operado 263 nominales.
    """
    tipo = (o.get("tipo") or "").strip().lower()
    if tipo in ENTRAN:
        signo = 1
    elif tipo in SALEN:
        signo = -1
    else:
        return None
    cant = _num(o.get("cantidadOperada"))
    if not cant:
        return None
    fecha = str(o.get("fechaOperada") or o.get("fechaOrden") or "")[:10]
    if not fecha:
        return None
    return {
        "simbolo": str(o.get("simbolo") or "").strip().upper(),
        "fecha": fecha,
        "tipo": o.get("tipo"),
        "signo": signo,
        "cantidad": cant,
        "precio": _num(o.get("precioOperado")),
        "monto": _num(o.get("montoOperado")),
        "numero": o.get("numero"),
    }


def base_de(op):
    """1 o 100, deducido del propio importe del broker.

    `montoOperado` ya viene con la base aplicada, asi que el cociente
    contra cantidad por precio la delata. Es mejor que deducirla del tipo
    de tenencia, que puede faltar o estar mal cargado.
    """
    if not (op.get("precio") and op.get("monto") and op.get("cantidad")):
        return None
    bruto = op["cantidad"] * op["precio"]
    if not bruto:
        return None
    r = bruto / op["monto"]
    if abs(r - 1) < 0.02:
        return 1.0
    if abs(r - 100) < 2:
        return 100.0
    return None


def simbolo_base(sim, conocidos):
    """`AO29D` es el mismo bono que `AO29`, pero solo si `AO29` existe.

    La `D` final marca la especie que liquida en dolares y el broker la
    opera con ticker propio, aunque en la tenencia figure sumada: AO29
    daba 5.565 contra 5.471 reconstruidos, y la diferencia eran
    exactamente los 94 nominales de una compra de AO29D.

    No se corta la `D` a ciegas. `BDED` es un ticker entero y `BDE` no
    existe: se corta solo cuando lo que queda tambien aparece, en las
    operaciones o en la tenencia. Sacar una letra porque si es como se
    inventan especies que no estan.
    """
    sim = (sim or "").strip().upper()
    for suf in (" US$", " USD"):
        if sim.endswith(suf):
            sim = sim[:-len(suf)].strip()
    if len(sim) > 2 and sim.endswith("D") and sim[:-1] in conocidos:
        return sim[:-1]
    return sim


def factor_redondo(a, b):
    """Si una cantidad es un multiplo limpio de la otra, cual.

    Un 2 a 1 exacto no es una compra que falta: es un cambio de ratio del
    CEDEAR o un split. Se dice, no se aplica.
    """
    if not (a and b):
        return None
    grande, chico = (a, b) if abs(a) >= abs(b) else (b, a)
    if not chico:
        return None
    r = abs(grande / chico)
    for f in (2, 3, 4, 5, 6, 8, 10, 20, 25, 50, 100):
        if abs(r - f) < 0.005 * f:
            return f
    return None


def reconstruir(operaciones, conocidos=None, mep_de=None):
    """Por simbolo: cantidad, fecha de alta y PPC de la tenencia actual.

    La fecha de alta es el ultimo cruce de cero hacia arriba, no la
    primera compra de la historia: si vendiste todo en 2019 y volviste a
    comprar en 2024, la posicion de hoy empezo en 2024.

    El PPC se promedia solo sobre las compras de la tenencia vigente. Una
    venta baja la cantidad y no toca el costo unitario, que es la
    convencion del broker. **Va sin comisiones**: `montoOperado` es el
    bruto.
    """
    limpias = [c for c in (limpiar(o) for o in operaciones) if c]
    # Los simbolos que se sabe que existen: los de las operaciones mas
    # los de la tenencia. Es contra esto que se decide si una `D` final
    # es un sufijo o parte del nombre.
    vistos = {c["simbolo"] for c in limpias} | set(conocidos or ())
    porsim = {}
    for c in limpias:
        c["simbolo"] = simbolo_base(c["simbolo"], vistos)
        porsim.setdefault(c["simbolo"], []).append(c)

    salida = {}
    for sim, ops in porsim.items():
        # Por fecha y despues por numero: dos operaciones del mismo dia
        # tienen que aplicarse en el orden en que ocurrieron.
        ops.sort(key=lambda x: (x["fecha"], x["numero"] or 0))
        cant = 0.0
        alta = None
        costo = 0.0          # importe acumulado de la tenencia vigente
        nominales = 0.0      # nominales comprados de la tenencia vigente
        costo_usd = 0.0      # el mismo importe, al MEP del dia de cada compra
        nom_usd = 0.0        # nominales que si tuvieron MEP
        base = None
        desde_cero = True
        for o in ops:
            base = base_de(o) or base
            if o["signo"] > 0:
                if cant <= 1e-9:
                    # arranca una tenencia nueva
                    alta = o["fecha"]
                    costo, nominales = 0.0, 0.0
                    costo_usd, nom_usd = 0.0, 0.0
                    desde_cero = True
                cant += o["cantidad"]
                if o["monto"]:
                    costo += o["monto"]
                    nominales += o["cantidad"]
                    # Cada compra entro a su propio tipo de cambio: es la
                    # diferencia que se quiere medir. Las que no tienen
                    # MEP de ese dia quedan afuera del promedio en vez de
                    # entrar al de hoy, que no seria el que pagaste.
                    mep = mep_de(o["fecha"]) if mep_de else None
                    if mep:
                        costo_usd += o["monto"] / mep
                        nom_usd += o["cantidad"]
            else:
                cant -= o["cantidad"]
                if cant <= 1e-9:
                    cant = 0.0
                    alta = None
                    costo, nominales = 0.0, 0.0
                    costo_usd, nom_usd = 0.0, 0.0
        if cant <= 1e-9:
            continue
        salida[sim] = {
            "cantidad": round(cant, 6),
            "fecha_alta": alta,
            # Importe pagado dividido nominales, o sea **por unidad**. Va
            # con `ppc_base: 1` aunque el papel cotice por 100: la base
            # del PPC dice en que unidad esta el costo, no en cual cotiza
            # el mercado. Ponerle 100 aca haria una posicion cien veces
            # mas barata de lo que costo.
            "ppc": round(costo / nominales, 6) if nominales else None,
            "ppc_base": 1.0,
            # Solo si el MEP cubre todas las compras: un promedio armado
            # con la mitad de las compras no es el costo en dolares.
            "ppc_usd": (round(costo_usd / nom_usd, 8)
                        if nom_usd and abs(nom_usd - nominales) < 1e-6
                        else None),
            # Cuantos nominales quedaron sin MEP de su dia. Si son todos,
            # la serie no llega tan atras como la compra; si son algunos,
            # hay huecos. Sin esto, "no calculo el PPC en dolares" no
            # tiene explicacion en ningun lado.
            "nominales_sin_mep": round(nominales - nom_usd, 6),
            "primera_compra": ops[0]["fecha"] if ops else None,
            "base_cotizacion": base,
            "operaciones": len(ops),
            "desde_cero": desde_cero,
        }
    return salida


# Ni ARS ni MEP son titulos: son el saldo en moneda. Nunca van a tener
# operaciones y solo ensucian el informe.
SIN_OPERAR = ("moneda",)


def conciliar(reconstruido, tenencia, tolerancia=0.01):
    """Compara lo reconstruido contra lo que hay, sin escribir nada.

    Devuelve tres listas. `cierran` es lo unico que se puede escribir sin
    preguntar: la cantidad que sale de las operaciones es la que figura
    hoy, asi que la fecha de alta corresponde a esta posicion y no a otra.

    `difieren` son las que no cierran, con las dos cantidades. Pasa
    siempre en dos casos: lo que entro por transferencia desde otro
    broker no tiene compra, y donde hubo split el broker ajusto la
    cantidad pero las operaciones viejas siguen en la escala anterior.

    `sin_operaciones` son las que no aparecen en el rango pedido, que
    puede ser simplemente que se compraron antes.
    """
    cierran, difieren, sin_ops = [], [], []
    conocidos = set(reconstruido)
    # La tenencia trae AO29 y AO29D en una sola fila; las operaciones
    # vienen separadas. Se agrupa por simbolo base de los dos lados.
    juntas = {}
    for t in tenencia:
        if (t.get("tipo") or "").lower() in SIN_OPERAR:
            continue
        base = simbolo_base(t["simbolo"], conocidos)
        d = juntas.setdefault(base, {"simbolo": base, "cantidad": 0.0,
                                     "filas": []})
        d["cantidad"] += t.get("cantidad") or 0
        d["filas"].append(t["simbolo"])

    for t in juntas.values():
        sim = t["simbolo"]
        r = reconstruido.get(sim)
        actual = t.get("cantidad") or 0
        if not r:
            sin_ops.append({"simbolo": sim, "cantidad": actual})
            continue
        fila = {"simbolo": sim, "filas": t["filas"], "cantidad": actual,
                "reconstruida": r["cantidad"], "fecha_alta": r["fecha_alta"],
                "ppc": r["ppc"], "ppc_base": r["ppc_base"],
                "ppc_usd": r["ppc_usd"],
                "nominales_sin_mep": r["nominales_sin_mep"],
                "primera_compra": r["primera_compra"],
                "base_cotizacion": r["base_cotizacion"],
                "operaciones": r["operaciones"]}
        ref = max(abs(actual), abs(r["cantidad"]), 1.0)
        if abs(actual - r["cantidad"]) / ref <= tolerancia and r["fecha_alta"]:
            cierran.append(fila)
        else:
            f = factor_redondo(actual, r["cantidad"])
            if not r["fecha_alta"]:
                fila["motivo"] = "no se pudo ubicar el inicio"
            elif f:
                fila["motivo"] = ("parece un ajuste de %d a 1: split o "
                                  "cambio de ratio del CEDEAR" % f)
                fila["factor"] = f
            elif abs(r["cantidad"]) > abs(actual):
                fila["motivo"] = "las operaciones dan más de lo que hay"
            else:
                fila["motivo"] = "las operaciones dan menos de lo que hay"
            difieren.append(fila)
    return {"cierran": cierran, "difieren": difieren,
            "sin_operaciones": sin_ops}
