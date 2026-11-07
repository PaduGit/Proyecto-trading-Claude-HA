import json
import logging
import os
import platform
import sys
import time

RUTA_OPCIONES = os.environ.get("INVENTARIO_OPTIONS", "/data/options.json")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("main")


def cargar_opciones():
    try:
        with open(RUTA_OPCIONES) as f:
            return json.load(f)
    except FileNotFoundError:
        log.error("No se encontró %s. ¿Se guardó la configuración?", RUTA_OPCIONES)
        sys.exit(1)
    except json.JSONDecodeError as e:
        log.error("Configuración inválida: %s", e)
        sys.exit(1)


def main():
    cfg = cargar_opciones()
    tz = (cfg.get("zona_horaria") or "").strip()
    if tz:
        os.environ["TZ"] = tz
        time.tzset()
    log.info("entorno: Python %s · token propio %s", platform.python_version(),
             "cargado" if (cfg.get("ha_token") or "").strip() else "vacío")

    from web import crear_app
    app = crear_app(cfg)
    try:
        from waitress import serve
        log.info("servidor listo en :8099")
        serve(app, host="0.0.0.0", port=8099, threads=4, channel_timeout=120, ident=None)
    except ImportError:
        log.warning("waitress no disponible, uso el servidor de Flask")
        app.run(host="0.0.0.0", port=8099, threaded=True)


if __name__ == "__main__":
    main()
