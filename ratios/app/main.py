"""Punto de entrada del add-on."""

import json
import logging
import os
import sys
import threading
import time

import cer
import dolar
import curva
import db
import historico
import respaldo
from iol import IOL
from monitor import Monitor
from notify import Notificador
from web import crear_app

RUTA_OPCIONES = os.environ.get("RATIOS_OPTIONS", "/data/options.json")

logging.basicConfig(
    level=logging.INFO,
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


def validar(cfg):
    faltan = [c for c in ("iol_user", "iol_pass") if not cfg.get(c)]
    if faltan:
        log.error("Faltan credenciales de IOL: %s", ", ".join(faltan))
        sys.exit(1)

    limpios = []
    vistos = set()
    for p in cfg.get("pares") or []:
        num = (p.get("num") or "").strip().upper()
        den = (p.get("den") or "").strip().upper()
        if not num or not den:
            log.warning("Par sin especies, se omite: %r", p)
            continue
        alias = (p.get("alias") or "").strip() or "%s/%s" % (num, den)
        if alias in vistos:
            log.warning("Alias repetido, se omite: %s", alias)
            continue
        vistos.add(alias)
        r = float(p.get("resistencia") or 0)
        s = float(p.get("soporte") or 0)
        if r and s and r <= s:
            log.warning("%s: resistencia (%.4f) no supera al soporte (%.4f). "
                        "Se ignoran los niveles.", alias, r, s)
            r = s = 0
        limpios.append({
            "alias": alias, "num": num, "den": den,
            "mercado": (p.get("mercado") or "bCBA").strip(),
            "plazo": (p.get("plazo") or "t1").strip(),
            "resistencia": r, "soporte": s,
            "factor": float(p.get("factor") or 0) or None,
            "alertas": bool(p.get("alertas", True)),
        })
    # Sin pares en la configuracion no pasa nada: viven en la base y se
    # crean desde la app. Esta lista solo alimenta la migracion inicial.
    cfg["pares"] = limpios

    # comisiones: de lista de dicts a mapa simple
    com = {}
    for c in cfg.get("comisiones") or []:
        if isinstance(c, dict) and c.get("instrumento"):
            try:
                com[c["instrumento"].strip().lower()] = float(c.get("pct") or 0)
            except (TypeError, ValueError):
                pass
    cfg["comisiones"] = com or {"acciones": 0.15, "bonos": 0.15,
                                "opciones": 0.5, "cauciones": 0.05}

    # Los derechos de mercado los cobra BYMA y no son un solo numero:
    # cambian por instrumento. Cargarlos como valor unico hacia que el
    # 0,20% de opciones se aplicara tambien a los bonos, que pagan 0,01%.
    der = {}
    for c in cfg.get("derechos_mercado") or []:
        if isinstance(c, dict) and c.get("instrumento"):
            try:
                der[c["instrumento"].strip().lower()] = float(c.get("pct") or 0)
            except (TypeError, ValueError):
                pass
    cfg["derechos_mercado"] = der
    try:
        cfg["iva_pct"] = float(cfg.get("iva_pct") or 0)
    except (TypeError, ValueError):
        cfg["iva_pct"] = 0.0

    cfg["arbitraje_tickers"] = [
        {"ticker": (t.get("ticker") or "").strip().upper(),
         "mercado": (t.get("mercado") or "bCBA").strip(),
         "tipo": (t.get("tipo") or "bonos").strip().lower()}
        for t in (cfg.get("arbitraje_tickers") or [])
        if (t.get("ticker") or "").strip()
    ]

    os.environ["TZ"] = cfg.get("timezone") or "America/Argentina/Buenos_Aires"
    try:
        time.tzset()
    except AttributeError:
        pass
    return cfg


def main():
    cfg = cargar_opciones()
    cfg, repuestos = respaldo.restaurar_si_vacio(cfg)
    if repuestos:
        log.warning("Se restauraron del respaldo: %s. Revisá la "
                    "configuración de la app.", ", ".join(repuestos))
    cfg = validar(cfg)
    db.init()
    db.init_posicion()
    db.init_opciones()
    db.init_api_log()
    db.init_alertas()
    # Los pares pasan de la configuracion a la base. Se hace una vez: a
    # partir de ahi se editan en la app.
    try:
        r = db.migrar_pares(cfg.get("pares"))
        if r.get("migrados"):
            log.info("pares migrados a la base: %d creados, %d completados",
                     len(r.get("creados") or []), len(r.get("completados") or []))
    except Exception as e:
        log.warning("migracion de pares: %s", e)
    cer.init()
    dolar.init()
    historico.init()
    curva.init()

    notif = Notificador(cfg)
    iol = IOL(cfg["iol_user"], cfg["iol_pass"])
    monitor = Monitor(cfg, iol, notif)

    log.info("%d pares, %d instrumentos, refresco cada %ss",
             len(monitor.pares), len(monitor.instrumentos_orleans()),
             cfg.get("poll_seconds", 600))

    def _sincronizar_cer():
        try:
            import bonos as BO
            bonos_cfg, _ = BO.cargar()
            faltan = cer.sincronizar(bonos_cfg)
            if faltan:
                log.warning("CER incompleto para: %s. Los bonos ajustables "
                            "van a aparecer sin TIR.", ", ".join(faltan))
            else:
                v = cer.vigente()
                log.info("CER vigente: %s", v)
        except Exception as e:
            log.warning("no se pudo sincronizar el CER: %s", e)

    respaldo.guardar_config(cfg)
    threading.Thread(target=_sincronizar_cer, daemon=True, name="cer").start()
    threading.Thread(target=monitor.loop, daemon=True, name="monitor").start()

    app = crear_app(monitor)
    try:
        from waitress import serve
        log.info("servidor listo en :8099")
        serve(app, host="0.0.0.0", port=8099, threads=8,
              channel_timeout=120, ident=None)
    except ImportError:
        log.warning("waitress no disponible, uso el servidor de Flask")
        app.run(host="0.0.0.0", port=8099, threaded=True)


if __name__ == "__main__":
    main()
