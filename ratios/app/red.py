"""Pedidos HTTP a fuentes externas, con registro.

Las llamadas a IOL quedaban anotadas y las demas no, asi que el registro
mostraba una parte del consumo y parecia que el BCRA y BYMA no existieran.
Cada fuente se anota con su propio tipo, para que el resumen las separe:
el cupo que importa cuidar es el de IOL y mezclarlas lo haria ilegible.

No toca el contador de requests de IOL, que es otra tabla y sirve para
otra cosa.
"""

import logging
import time

import requests

log = logging.getLogger("ratios.red")


def _anotar(url, tipo, status, desde, origen):
    try:
        import db
        db.registrar_llamada(url[:300], tipo, status,
                             int((time.time() - desde) * 1000), origen)
    except Exception:
        pass       # el registro nunca debe romper una consulta


def _pedir(metodo, url, tipo, origen, session, etiqueta, kw):
    """`session` opcional: BYMA necesita conservar las cookies.

    `etiqueta` es lo que se guarda en el registro. Va aparte de la URL a
    proposito: agregarle un parametro a la direccion para que el registro
    quedara mas legible cambiaba el pedido de verdad.
    """
    cliente = session or requests
    desde = time.time()
    anotada = etiqueta or url
    try:
        r = getattr(cliente, metodo)(url, **kw)
    except requests.RequestException:
        _anotar(anotada, tipo, None, desde, origen)
        raise
    _anotar(anotada, tipo, r.status_code, desde, origen)
    return r


def get(url, tipo, origen="ciclo", session=None, etiqueta=None, **kw):
    return _pedir("get", url, tipo, origen, session, etiqueta, kw)


def post(url, tipo, origen="ciclo", session=None, etiqueta=None, **kw):
    return _pedir("post", url, tipo, origen, session, etiqueta, kw)
