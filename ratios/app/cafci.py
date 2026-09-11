"""Valor de cuotaparte de los fondos, via ArgentinaDatos.

Un FCI que no comercializa IOL no aparece en ningun panel ni en
`/api/v2/Titulos/FCI`: el fondo de ECO quedaba sin precio y su posicion
fuera del total de la cartera.

ArgentinaDatos republica en JSON la planilla diaria de CAFCI, sin clave y
sin token. La API REST propia de CAFCI se discontinuo en abril de 2026.

**El `vcp` viene por mil.** La ficha de CAFCI lo dice explicito: "Valor
por cada cuotaparte: 1,040522 (Valor por mil: 1.040,522)", y el JSON trae
1041,247. Usarlo tal cual deja la posicion mil veces mas grande. Es el
mismo problema de los bonos que cotizan por 100, con otro factor.
"""

import logging
from datetime import date

import red

log = logging.getLogger("ratios.cafci")

BASE = "https://api.argentinadatos.com/v1/finanzas/fci"

# Las cinco que publica. Se recorren todas porque un fondo puede estar en
# cualquiera y equivocarse de categoria es dejarlo sin precio sin aviso.
CATEGORIAS = ("rentaFija", "rentaVariable", "rentaMixta", "mercadoDinero",
              "otros")

# El JSON da el valor por mil.
POR_MIL = 1000.0


def bajar(categorias=None, origen="ciclo"):
    """Todos los fondos con su cuotaparte, por nombre exacto.

    La clave es el nombre completo con la clase incluida -"Adcap Gestion
    Estrategica III - Clase A"-, porque CAFCI no publica ticker.
    """
    out = {}
    for cat in (categorias or CATEGORIAS):
        url = "%s/%s/ultimo" % (BASE, cat)
        try:
            r = red.get(url, "cafci", origen=origen, timeout=30)
            r.raise_for_status()
            filas = r.json()
        except Exception as e:
            log.warning("cafci %s: %s", cat, e)
            continue
        if not isinstance(filas, list):
            continue
        for f in filas:
            nombre = (f.get("fondo") or "").strip()
            vcp = f.get("vcp")
            if not nombre or not vcp:
                continue
            out[nombre.lower()] = {
                "nombre": nombre,
                "categoria": cat,
                "fecha": str(f.get("fecha") or "")[:10],
                # Por cuotaparte, que es en lo que esta la tenencia.
                "vcp": float(vcp) / POR_MIL,
                "patrimonio": f.get("patrimonio"),
            }
    return out


def cotizacion(fondo, hoy=None):
    """Un fondo en la forma de una cotizacion, o None.

    Sin puntas ni volumen: la cuotaparte es el precio, y se suscribe y
    rescata a ese valor. `vieja` va siempre: el dato es del cierre
    anterior y conviene que la pantalla lo diga.
    """
    if not fondo:
        return None
    return {
        "simbolo": "", "ultimo": fondo["vcp"], "compra": 0.0, "venta": 0.0,
        "vol_compra": 0.0, "vol_venta": 0.0, "medio": 0.0,
        "ref": fondo["vcp"], "variacion": 0.0, "volumen": 0.0, "lote": 0.0,
        "moneda": "", "instrumento": "fci",
        "descripcion": fondo["nombre"],
        "vieja": (fondo["fecha"] or "") < (hoy or date.today().isoformat()),
        "ultima_operacion": fondo["fecha"],
    }


def buscar(texto, fondos=None):
    """Los nombres que contienen el texto, para poder elegir el correcto.

    Hay fondos con cuatro clases y nombres casi iguales; elegir mal la
    clase da un precio parecido y equivocado, que es peor que no tener
    ninguno.
    """
    t = (texto or "").strip().lower()
    if not t:
        return []
    fondos = fondos if fondos is not None else bajar(origen="boton")
    return sorted(
        ({"nombre": f["nombre"], "vcp": f["vcp"], "fecha": f["fecha"],
          "categoria": f["categoria"]}
         for k, f in fondos.items() if t in k),
        key=lambda x: x["nombre"])
