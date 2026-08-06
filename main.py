"""Punto de entrada del add-on."""

import json
import logging
import os
import sys
import threading

import db
from iol import IOL
from monitor import Monitor
from telegram import Telegram
from web import crear_app

RUTA_OPCIONES = os.environ.get("RATIOS_OPTIONS", "/data/options.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("main")


def cargar_opciones():
    try:
        with open(RUTA_OPCIONES) as f:
            return json.load(f)
    except FileNotFoundError:
        log.error("No se encontró %s. ¿Se guardó la configuración del add-on?",
                  RUTA_OPCIONES)
        sys.exit(1)
    except json.JSONDecodeError as e:
        log.error("Configuración inválida: %s", e)
        sys.exit(1)


def validar(cfg):
    faltan = [c for c in ("iol_user", "iol_pass") if not cfg.get(c)]
    if faltan:
        log.error("Faltan credenciales de IOL: %s. "
                  "Cargalas en la pestaña Configuración del add-on.",
                  ", ".join(faltan))
        sys.exit(1)

    pares = cfg.get("pares") or []
    if not pares:
        log.error("No hay pares configurados.")
        sys.exit(1)

    vistos = set()
    limpios = []
    for p in pares:
        alias = (p.get("alias") or "").strip()
        num = (p.get("num") or "").strip().upper()
        den = (p.get("den") or "").strip().upper()
        if not num or not den:
            log.warning("Par sin especies, se omite: %r", p)
            continue
        alias = alias or f"{num}/{den}"
        if alias in vistos:
            log.warning("Alias repetido, se omite: %s", alias)
            continue
        vistos.add(alias)
        limpios.append({
            "alias": alias, "num": num, "den": den,
            "mercado": (p.get("mercado") or "bCBA").strip(),
            "plazo": (p.get("plazo") or "t2").strip(),
            "resistencia": float(p.get("resistencia") or 0),
            "soporte": float(p.get("soporte") or 0),
            "alertas": bool(p.get("alertas", True)),
        })

        r, s = limpios[-1]["resistencia"], limpios[-1]["soporte"]
        if r and s and r <= s:
            log.warning("%s: la resistencia (%.4f) no es mayor al soporte (%.4f). "
                        "Se ignoran los niveles.", alias, r, s)
            limpios[-1]["resistencia"] = limpios[-1]["soporte"] = 0

    cfg["pares"] = limpios
    os.environ["TZ"] = cfg.get("timezone") or "America/Argentina/Buenos_Aires"
    try:
        import time
        time.tzset()
    except AttributeError:
        pass
    return cfg


def main():
    cfg = validar(cargar_opciones())
    db.init()

    tg = Telegram(cfg.get("telegram_token"), cfg.get("telegram_chat_id"))
    iol = IOL(cfg["iol_user"], cfg["iol_pass"])
    monitor = Monitor(cfg, iol, tg)

    log.info("%d pares configurados, refresco cada %ss",
             len(cfg["pares"]), cfg.get("poll_seconds", 180))

    hilo = threading.Thread(target=monitor.loop, daemon=True, name="monitor")
    hilo.start()

    app = crear_app(monitor)
    app.run(host="0.0.0.0", port=8099, threaded=True)


if __name__ == "__main__":
    main()
