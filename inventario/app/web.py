"""Página única servida por Ingress: todas las rutas son relativas."""
import logging
import os
import time

from flask import Flask, jsonify, request

import ha
import inventario

log = logging.getLogger("web")
CACHE_SEG = 20


def _version():
    for ruta in ("/config.yaml",
                 os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")):
        try:
            with open(ruta, encoding="utf-8") as f:
                for linea in f:
                    if linea.startswith("version:"):
                        return linea.split(":", 1)[1].strip().strip("\"'")
        except OSError:
            continue
    return ""


def crear_app(cfg):
    app = Flask(__name__, static_folder="static", static_url_path="")
    excluidos = [x.strip() for x in (cfg.get("dominios_excluidos") or "").split(",") if x.strip()]
    cache = {"t": 0, "datos": None, "sup": None}

    @app.after_request
    def sin_cache(resp):
        if resp.mimetype in ("text/html", "application/javascript"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/")
    def index():
        with open(os.path.join(app.static_folder, "index.html"), encoding="utf-8") as f:
            html = f.read()
        html = html.replace("<body>", '<body data-version="%s">' % _version(), 1)
        return app.response_class(html, mimetype="text/html")

    @app.get("/api/inventario")
    def api_inventario():
        forzar = request.args.get("forzar") == "1"
        try:
            if forzar or not cache["datos"] or time.time() - cache["t"] > CACHE_SEG:
                cache["datos"] = ha.leer_registros(cfg)
                cache["sup"] = ha.info_supervisor()
                cache["t"] = time.time()
        except Exception as e:
            log.error("lectura: %s", e)
            return jsonify({"error": str(e)}), 502
        md, resumen = inventario.generar(
            cache["datos"], cache["sup"],
            diag=request.args.get("diag") == "1",
            config=request.args.get("config", "1") == "1",
            deshab=request.args.get("deshab", "1") == "1",
            excluidos=excluidos)
        return jsonify({"markdown": md, "resumen": resumen})

    return app
