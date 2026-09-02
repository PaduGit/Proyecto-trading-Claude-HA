"""Precios de Open BYMA Data, como respaldo cuando el panel de IOL cae.

Trae paneles enteros en una llamada, con puntas y volumen, sin
credenciales y sin gastar cupo de IOL. A cambio llega con veinte minutos
de retraso, asi que sirve para valuar la cartera y armar la curva pero no
para operar un rulo.

No reemplaza a IOL: se enciende cuando el panel Orleans falla y se apaga
solo cuando vuelve.
"""

import logging

import requests

import red

log = logging.getLogger("ratios.byma")

PORTAL = "https://open.bymadata.com.ar"
BASE = PORTAL + "/vanoms-be-core/rest/api/bymadata/free"

# Un panel por endpoint, igual que Orleans. El nombre de la izquierda es
# el que usa la configuracion de instrumentos.
PANELES = {
    "titulosPublicos": "/public-bonds",
    "letras": "/lebacs",
    "obligacionesNegociables": "/negociable-obligations",
    "acciones": "/leading-equity",
    "panelGeneral": "/general-equity",
    "cedears": "/cedears",
}

# El `settlementType` de BYMA no es el numero de dias: verificado contra
# IOL, AL30D con settlementType 2 coincide en punta, cierre, volumen y
# hora con el t1 de IOL. Asi que 1 es contado inmediato y 2 es 24 horas.
# No hay filas de 48.
PLAZO = {"t0": "1", "t1": "2"}
PLAZO_INV = {v: k for k, v in PLAZO.items()}

# Sin cuerpo devuelve todo. Con `excludeZeroPxAndQty`, en cualquier
# valor, contesta 200 con la lista vacia: parece un panel sin datos y en
# realidad es el filtro.
PAGINAS_MAX = 12


class BymaError(Exception):
    pass


class Byma:
    def __init__(self, verificar_ssl=False, timeout=45):
        self.timeout = timeout
        self.verificar_ssl = verificar_ssl
        self.ses = None

    def _sesion(self):
        if self.ses is not None:
            return self.ses
        s = requests.Session()
        s.headers.update({
            "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0 Safari/537.36"),
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": PORTAL,
            "Referer": PORTAL + "/",
        })
        # La home deja las cookies; sin ellas la API contesta 401.
        try:
            red.get(PORTAL + "/", "byma", session=s, timeout=self.timeout,
                    verify=self.verificar_ssl)
        except requests.RequestException as e:
            raise BymaError("no se pudo abrir el portal: %s" % e)
        self.ses = s
        return s

    def panel(self, instrumento, plazo=None):
        """Un panel entero, paginado. Sin plazo devuelve los dos."""
        ruta = PANELES.get(instrumento)
        if not ruta:
            raise BymaError("panel desconocido: %s" % instrumento)
        s = self._sesion()
        filas, pagina = [], 1
        while pagina <= PAGINAS_MAX:
            try:
                r = red.post(BASE + ruta + "?page=%s" % pagina, "byma",
                             json={"page_number": pagina},
                             timeout=self.timeout, verify=self.verificar_ssl,
                             session=s)
            except requests.RequestException as e:
                raise BymaError("%s: %s" % (instrumento, e))
            if r.status_code == 401:
                # La sesion vencio: se rearma una vez y se reintenta.
                self.ses = None
                if pagina == 1:
                    s = self._sesion()
                    continue
                raise BymaError("%s: 401" % instrumento)
            if r.status_code != 200:
                raise BymaError("%s -> %s" % (instrumento, r.status_code))
            try:
                d = r.json()
            except ValueError:
                raise BymaError("%s: respuesta no es JSON" % instrumento)
            lote = d.get("data") or []
            filas += lote
            total = (d.get("content") or {}).get("page_count") or 0
            if not lote or pagina >= total:
                break
            pagina += 1

        if not plazo:
            return filas
        buscado = PLAZO.get(plazo, "2")
        return [f for f in filas
                if str(f.get("settlementType") or "") == buscado]


def normalizar(f):
    """Lleva una fila de BYMA a la misma forma que la de IOL.

    Los precios ya vienen por lamina de 100, que es como cotiza el
    mercado y como los espera el resto de la aplicacion.
    """
    def num(k):
        try:
            v = f.get(k)
            return float(v) if v not in (None, "") else 0.0
        except (TypeError, ValueError):
            return 0.0

    compra, venta = num("bidPrice"), num("offerPrice")
    ultimo = num("closingPrice") or num("trade") or num("settlementPrice")
    medio = (compra + venta) / 2 if compra and venta else 0.0
    return {
        "simbolo": (f.get("symbol") or "").strip().upper(),
        "ultimo": ultimo,
        "compra": compra,
        "venta": venta,
        "vol_compra": num("quantityBid"),
        "vol_venta": num("quantityOffer"),
        "medio": medio,
        "ref": medio or ultimo,
        "variacion": 0.0,
        "volumen": num("volume") or num("tradeVolume"),
        "lote": 0,
        "moneda": f.get("denominationCcy") or "",
        # Propios de esta fuente, para poder filtrar por liquidez y saber
        # de cuando es el dato.
        "ordenes": num("numberOfOrders"),
        "hora": f.get("tradeHour") or "",
        "fuente": "byma",
    }


def mapa(instrumentos, verificar_ssl=False):
    """Simbolo -> cotizacion, por plazo, para los paneles que se pidan.

    Los dos plazos vienen en la misma respuesta, asi que se separan aca:
    pedirlos por turno seria bajar todo dos veces. Un panel que falla no
    impide los demas.
    """
    cli = Byma(verificar_ssl=verificar_ssl)
    salida = {"t0": {}, "t1": {}}
    fallas = []
    for inst in instrumentos:
        try:
            filas = cli.panel(inst)
        except BymaError as e:
            fallas.append(str(e))
            log.warning("byma %s: %s", inst, e)
            continue
        for f in filas:
            plazo = PLAZO_INV.get(str(f.get("settlementType") or ""))
            if not plazo:
                continue
            c = normalizar(f)
            if c["simbolo"] and c["ref"]:
                salida[plazo][c["simbolo"]] = c
    return salida, fallas
