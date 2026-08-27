"""Costo de una pata, en un solo lugar.

Operar tiene tres componentes:

- **Arancel del agente**: lo que cobra el broker, libremente pactado.
- **Derechos de mercado**: los cobra BYMA y cambian por instrumento. No
  es un solo numero: las opciones sobre acciones privadas pagan 0,20%
  sobre la prima y los titulos publicos 0,01% sobre el monto.
- **IVA**: se suma sobre la suma de los dos anteriores, *salvo* en
  operaciones con valores negociables publicos y obligaciones
  negociables, que estan exentas.

Esa exencion es la razon por la que esto vive aca y no en cada modulo:
un mismo circuito puede tocar bonos soberanos (exentos) y acciones (no),
y aplicar el IVA parejo a todo inflaria el costo del Rulo.
"""

# Valores negociables publicos y ON: exentos de IVA.
EXENTOS_IVA = {"bonos", "letras", "on", "obligaciones", "publicos"}

# Si no se configuro un derecho para el instrumento, se usa el de su
# familia antes de caer en cero.
FAMILIA = {"acciones": "acciones", "cedears": "acciones",
           "opciones": "opciones", "bonos": "bonos", "letras": "letras",
           "cauciones": "cauciones", "on": "bonos"}


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def pct(comisiones, instrumento, derechos=None, iva_pct=0):
    """Costo de una pata en tanto por uno, IVA incluido si corresponde.

    `comisiones` y `derechos` son mapas instrumento -> porcentaje.
    """
    inst = (instrumento or "").strip().lower()
    com = comisiones or {}
    der = derechos or {}

    arancel = _num(com.get(inst, com.get("general")))
    derecho = _num(der.get(inst, der.get(FAMILIA.get(inst, ""))))

    total = arancel + derecho
    if inst not in EXENTOS_IVA:
        total *= 1 + _num(iva_pct) / 100.0
    return total / 100.0



def detalle(comisiones, instrumento, derechos=None, iva_pct=0):
    """Lo mismo, desglosado, para poder mostrarlo."""
    inst = (instrumento or "").strip().lower()
    com = comisiones or {}
    der = derechos or {}
    arancel = _num(com.get(inst, com.get("general")))
    derecho = _num(der.get(inst, der.get(FAMILIA.get(inst, ""))))
    exento = inst in EXENTOS_IVA
    iva = 0.0 if exento else (arancel + derecho) * _num(iva_pct) / 100.0
    return {"instrumento": inst, "arancel_pct": arancel,
            "derecho_pct": derecho, "iva_pct": 0 if exento else _num(iva_pct),
            "iva_monto_pct": round(iva, 6), "exento_iva": exento,
            "total_pct": round(arancel + derecho + iva, 6)}


# -- bonificacion intradiaria -----------------------------------------
#
# La cobra el broker sobre su propio arancel, no sobre los derechos de
# mercado, que son de BYMA y se pagan igual. Cada broker la define
# distinto y eso cambia que circuitos cierran:
#
# - IOL exige que la segunda operacion sea del MISMO simbolo, el mismo
#   dia, en igual plazo y moneda, y por cantidad igual o menor. En un
#   rulo desde pesos las cuatro patas son simbolos distintos, asi que no
#   bonifica nada. Si bonifica en los circuitos desde un bono propio,
#   que terminan recomprando la especie que se vendio.
# - Eco bonifica el lado menor entre especies distintas mientras
#   coincidan moneda y plazo, que es exactamente la forma de un rulo.
# - Veta Flat no tiene arancel marginal: cobra un abono mensual fijo, que
#   no es costo del circuito porque no depende de operarlo.

ESQUEMAS = {
    "iol":  {"nombre": "IOL", "regla": "simbolo", "pct": 100},
    "eco":  {"nombre": "Eco Valores", "regla": "moneda_plazo", "pct": 100},
    "veta": {"nombre": "Veta Flat", "regla": "sin_arancel", "pct": 100},
}


def esquema(cfg):
    b = (cfg.get("broker") or "iol").strip().lower()
    e = dict(ESQUEMAS.get(b) or ESQUEMAS["iol"])
    if cfg.get("bonificacion_pct") is not None:
        try:
            e["pct"] = float(cfg["bonificacion_pct"])
        except (TypeError, ValueError):
            pass
    if not cfg.get("bonificacion_intradiaria", True):
        e["pct"] = 0
    return e



def pct_circuito(comisiones, instrumento, derechos=None, iva_pct=0, esq=None):
    """Costo por pata dentro de un circuito, con la bonificacion del
    broker ya aplicada sobre el arancel."""
    inst = (instrumento or "").strip().lower()
    com = comisiones or {}
    der = derechos or {}
    arancel = _num(com.get(inst, com.get("general")))
    derecho = _num(der.get(inst, der.get(FAMILIA.get(inst, ""))))

    esq = esq or ESQUEMAS["iol"]
    factor = FACTOR_ARANCEL.get(esq.get("regla"), 1.0)
    pct = _num(esq.get("pct")) / 100.0
    # la bonificacion es parcial si el broker no perdona el 100%
    arancel *= 1 - (1 - factor) * pct

    total = arancel + derecho
    if inst not in EXENTOS_IVA:
        total *= 1 + _num(iva_pct) / 100.0
    return total / 100.0
