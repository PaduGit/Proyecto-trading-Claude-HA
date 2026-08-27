"""Cliente de la API de InvertirOnline."""

import logging
import time
from contextlib import contextmanager
import threading
from datetime import datetime, timedelta
from urllib.parse import quote

import requests

import db

BASE = "https://api.invertironline.com"
log = logging.getLogger("iol")


class IOLError(Exception):
    pass


def _clasificar(path):
    p = path.lower()
    if "/token" in p:
        return "auth"
    if "cotizaciones-orleans" in p:
        return "panel"
    if "/cotizaciones/" in p:
        return "panel"
    if "seriehistorica" in p:
        return "historico"
    if "cotizacion" in p:
        return "cotizacion"
    if "opciones" in p:
        return "opciones"
    return "otros"


class IOL:
    """Autenticacion, renovacion de token y consultas."""

    def __init__(self, usuario, password):
        self._usuario = usuario
        self._password = password
        self._token = None
        self._refresh = None
        self._expira = datetime.min
        self._refresh_expira = datetime.max
        self._ultimo_fallo = None
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "ha-ratios/0.2"

    # -- auth ---------------------------------------------------------
        # Etiqueta de quien esta pidiendo: ciclo, pestania, boton. Se
        # guarda con cada llamada para poder ver de donde sale el consumo.
        self.origen = "ciclo"

    def _pedir_token(self, data):
        try:
            db.contar_request("auth")
        except Exception:
            pass
        r = self.session.post(BASE + "/token", data=data, timeout=25)
        if r.status_code != 200:
            raise IOLError("auth %s: %s" % (r.status_code, r.text[:180]))
        d = r.json()
        self._token = d["access_token"]
        self._refresh = d.get("refresh_token", self._refresh)

        # IOL informa cuánto vive el token; renovamos con dos minutos de
        # margen. Antes usábamos 12 minutos fijos, y como el refresh vence
        # antes, cada ciclo terminaba reautenticando desde cero con un
        # request extra.
        try:
            vida = int(d.get("expires_in") or 0)
        except (TypeError, ValueError):
            vida = 0
        seg = max(60, vida - 120) if vida else 12 * 60
        self._expira = datetime.now() + timedelta(seconds=seg)

        # el refresh de IOL vive poco: si lo dejamos vencer, la próxima
        # renovación falla y hay que reautenticar
        try:
            vida_r = int(d.get("refresh_expires_in") or 0)
        except (TypeError, ValueError):
            vida_r = 0
        if vida_r:
            self._refresh_expira = datetime.now() + timedelta(
                seconds=max(60, vida_r - 120))

    def login(self):
        with self._lock:
            self._pedir_token({
                "username": self._usuario,
                "password": self._password,
                "grant_type": "password",
            })
            log.info("autenticado como %s", self._usuario)

    def _asegurar_token(self):
        if datetime.now() < self._expira:
            return
        with self._lock:
            if datetime.now() < self._expira:
                return

            if self._ultimo_fallo and \
                    datetime.now() - self._ultimo_fallo < timedelta(seconds=60):
                raise IOLError("autenticacion fallo recien, esperando")

            if self._refresh and datetime.now() >= self._refresh_expira:
                log.info("el refresh también venció, reautenticando")
                self._refresh = None

            if self._refresh:
                try:
                    self._pedir_token({
                        "refresh_token": self._refresh,
                        "grant_type": "refresh_token",
                    })
                    self._ultimo_fallo = None
                    return
                except IOLError as e:
                    log.info("refresh vencido (%s), reautenticando", e)
                    self._refresh = None

            try:
                self._pedir_token({
                    "username": self._usuario,
                    "password": self._password,
                    "grant_type": "password",
                })
                self._ultimo_fallo = None
                log.info("reautenticado como %s", self._usuario)
            except IOLError:
                self._ultimo_fallo = datetime.now()
                raise

    def _get(self, path, timeout=30):
        self._asegurar_token()
        tipo = _clasificar(path)
        try:
            db.contar_request(tipo)
        except Exception:
            pass
        url = BASE + path
        cab = {"Authorization": "Bearer " + str(self._token)}
        t0 = time.monotonic()
        r = self.session.get(url, headers=cab, timeout=timeout)
        if r.status_code == 401:
            self._expira = datetime.min
            self._asegurar_token()
            cab = {"Authorization": "Bearer " + str(self._token)}
            r = self.session.get(url, headers=cab, timeout=timeout)
        # La direccion exacta queda registrada: el contador por tipo dice
        # cuantas llamadas hubo, no cuales ni desde donde.
        db.registrar_llamada(path, tipo, r.status_code,
                             int((time.monotonic() - t0) * 1000),
                             self.origen)
        if r.status_code == 429:
            raise IOLError("429: la API pidio frenar (limite de requests)")
        if r.status_code != 200:
            raise IOLError("%s -> %s: %s" % (path, r.status_code, r.text[:180]))
        return r.json()

    @contextmanager
    def como(self, origen):
        """Marca el origen de las llamadas hechas dentro del bloque."""
        previo = self.origen
        self.origen = origen
        try:
            yield self
        finally:
            self.origen = previo

    # -- datos --------------------------------------------------------

    def get(self, path, timeout=30):
        if not path.startswith("/"):
            path = "/" + path
        return self._get(path, timeout=timeout)




    def cotizacion(self, mercado, simbolo, plazo="t1"):
        path = ("/api/v2/%s/Titulos/%s/CotizacionDetalleMobile/%s"
                % (mercado, simbolo, plazo))
        try:
            d = self._get(path)
        except IOLError:
            d = self._get("/api/v2/%s/Titulos/%s/Cotizacion" % (mercado, simbolo))
        return normalizar(d, simbolo)

    def portafolio(self, pais="argentina"):
        """Tenencia de la cuenta configurada.

        Devuelve los titulos, no el efectivo: para el disponible por
        moneda hay otro endpoint. Las cantidades vienen en nominales.
        """
        return self._get("/api/v2/portafolio/%s" % pais, timeout=45)

    def panel_orleans(self, instrumento, pais="argentina", filtro="Operables"):
        """Un instrumento entero en un request, con puntas.

        Reemplaza a los paneles: cubre mas especies y evita el pedido
        suelto de las que no estaban en ninguno.
        """
        return self._get("/api/v2/cotizaciones-orleans-panel/%s/%s/%s"
                         % (instrumento, pais, filtro), timeout=60)

    def estado_cuenta(self):
        """Saldos por cuenta y moneda. El portafolio trae solo titulos."""
        return self._get("/api/v2/estadocuenta", timeout=45)

    def opciones_de(self, simbolo, mercado="bCBA"):
        """Series que corresponden a un subyacente.

        Hace falta porque el símbolo de la opción no arranca con el del
        subyacente: las de GGAL empiezan con GFG. Este endpoint da el
        mapeo; las puntas vienen del panel.
        """
        return self._get("/api/v2/%s/Titulos/%s/Opciones" % (mercado, simbolo),
                         timeout=45)

    def serie(self, mercado, simbolo, desde, hasta, ajustada="sinAjustar"):
        path = ("/api/v2/%s/Titulos/%s/Cotizacion/seriehistorica/%s/%s/%s"
                % (mercado, simbolo, desde, hasta, ajustada))
        return self._get(path, timeout=60)


def _f(v):
    try:
        x = float(v)
        return x if x > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def normalizar(d, simbolo):
    """Extrae precio y mejor punta. La forma varia entre endpoints."""
    ultimo = _f(d.get("ultimoPrecio"))
    compra = venta = 0.0
    vol_compra = vol_venta = 0.0

    puntas = d.get("puntas")
    if isinstance(puntas, list) and puntas:
        p0 = puntas[0] or {}
    elif isinstance(puntas, dict):
        p0 = puntas
    else:
        p0 = {}

    compra = _f(p0.get("precioCompra")) or _f(d.get("precioCompra"))
    venta = _f(p0.get("precioVenta")) or _f(d.get("precioVenta"))
    vol_compra = _f(p0.get("cantidadCompra")) or _f(d.get("cantidadCompra"))
    vol_venta = _f(p0.get("cantidadVenta")) or _f(d.get("cantidadVenta"))

    medio = (compra + venta) / 2 if compra and venta else 0.0

    return {
        "simbolo": simbolo,
        "ultimo": ultimo,
        "compra": compra,
        "venta": venta,
        "vol_compra": vol_compra,
        "vol_venta": vol_venta,
        "medio": medio,
        "ref": medio or ultimo,
        "variacion": _f(d.get("variacionPorcentual")) or _f(d.get("variacion")),
        "volumen": _f(d.get("volumenNominal")) or _f(d.get("cantidadOperada")),
        "lote": _f(d.get("unitsPerLot")) or _f(d.get("laminaMinima")) or 0,
        "moneda": d.get("moneda") or "",
    }
