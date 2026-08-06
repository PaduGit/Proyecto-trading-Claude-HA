"""Cliente de la API de InvertirOnline."""

import logging
import threading
from datetime import datetime, timedelta

import requests

BASE = "https://api.invertironline.com"
log = logging.getLogger("iol")


class IOLError(Exception):
    pass


class IOL:
    """Maneja autenticacion, renovacion de token y consultas.

    El password se usa una sola vez y se descarta; despues vive el
    refresh_token, que se rota en cada renovacion.
    """

    def __init__(self, usuario, password):
        self._usuario = usuario
        self._password = password
        self._token = None
        self._refresh = None
        self._expira = datetime.min
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "ha-ratios/0.1"

    # -- auth ---------------------------------------------------------

    def _pedir_token(self, data):
        r = self.session.post(f"{BASE}/token", data=data, timeout=25)
        if r.status_code != 200:
            raise IOLError(f"auth {r.status_code}: {r.text[:180]}")
        d = r.json()
        self._token = d["access_token"]
        self._refresh = d.get("refresh_token", self._refresh)
        # IOL emite tokens de ~15 min; renovamos con margen
        self._expira = datetime.now() + timedelta(minutes=12)

    def login(self):
        with self._lock:
            self._pedir_token({
                "username": self._usuario,
                "password": self._password,
                "grant_type": "password",
            })
            self._password = None
            log.info("autenticado como %s", self._usuario)

    def _asegurar_token(self):
        if datetime.now() < self._expira:
            return
        with self._lock:
            if datetime.now() < self._expira:
                return
            if self._refresh:
                try:
                    self._pedir_token({
                        "refresh_token": self._refresh,
                        "grant_type": "refresh_token",
                    })
                    return
                except IOLError as e:
                    log.warning("refresh fallo (%s), reintento con password", e)
            if self._password:
                self._pedir_token({
                    "username": self._usuario,
                    "password": self._password,
                    "grant_type": "password",
                })
            else:
                raise IOLError(
                    "token vencido y sin refresh. Reinicia el add-on."
                )

    def _get(self, path, timeout=25):
        self._asegurar_token()
        r = self.session.get(
            f"{BASE}{path}",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=timeout,
        )
        if r.status_code == 401:
            # token rechazado: forzar renovacion y reintentar una vez
            self._expira = datetime.min
            self._asegurar_token()
            r = self.session.get(
                f"{BASE}{path}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=timeout,
            )
        if r.status_code != 200:
            raise IOLError(f"{path} -> {r.status_code}: {r.text[:180]}")
        return r.json()

    # -- datos --------------------------------------------------------

    def cotizacion(self, mercado, simbolo, plazo="t2"):
        """Cotizacion con book. Devuelve dict normalizado."""
        path = (
            f"/api/v2/{mercado}/Titulos/{simbolo}/CotizacionDetalleMobile"
            f"/{plazo}"
        )
        try:
            d = self._get(path)
        except IOLError:
            # fallback al endpoint clasico si el mobile no responde
            d = self._get(f"/api/v2/{mercado}/Titulos/{simbolo}/Cotizacion")
        return normalizar(d, simbolo)

    def serie(self, mercado, simbolo, desde, hasta, ajustada="sinAjustar"):
        path = (
            f"/api/v2/{mercado}/Titulos/{simbolo}/Cotizacion/seriehistorica/"
            f"{desde}/{hasta}/{ajustada}"
        )
        return self._get(path, timeout=60)


def _f(v):
    try:
        x = float(v)
        return x if x > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def normalizar(d, simbolo):
    """Extrae ultimo precio y mejor punta de la respuesta de IOL.

    La forma exacta varia entre endpoints e instrumentos, asi que
    tomamos lo que haya y dejamos en 0 lo que falte.
    """
    ultimo = _f(d.get("ultimoPrecio"))
    compra = venta = 0.0
    vol_compra = vol_venta = 0.0

    puntas = d.get("puntas")
    if isinstance(puntas, list) and puntas:
        p0 = puntas[0] or {}
        compra = _f(p0.get("precioCompra"))
        venta = _f(p0.get("precioVenta"))
        vol_compra = _f(p0.get("cantidadCompra"))
        vol_venta = _f(p0.get("cantidadVenta"))
    elif isinstance(puntas, dict):
        compra = _f(puntas.get("precioCompra"))
        venta = _f(puntas.get("precioVenta"))
        vol_compra = _f(puntas.get("cantidadCompra"))
        vol_venta = _f(puntas.get("cantidadVenta"))

    if not compra:
        compra = _f(d.get("precioCompra"))
    if not venta:
        venta = _f(d.get("precioVenta"))

    medio = (compra + venta) / 2 if compra and venta else 0.0

    return {
        "simbolo": simbolo,
        "ultimo": ultimo,
        "compra": compra,
        "venta": venta,
        "vol_compra": vol_compra,
        "vol_venta": vol_venta,
        "medio": medio,
        # precio de referencia: punta media si hay book, si no el ultimo
        "ref": medio or ultimo,
        "variacion": _f(d.get("variacionPorcentual")),
        "moneda": d.get("moneda") or "",
    }
