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


def desde_cfg(cfg, instrumento):
    """Atajo para cuando se tiene la configuracion entera a mano."""
    return pct(cfg.get("comisiones"), instrumento,
               cfg.get("derechos_mercado"), cfg.get("iva_pct"))


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
