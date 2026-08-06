"""Screener web. Se sirve por Ingress, asi que todas las rutas son relativas."""

import logging
import statistics
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_from_directory

import db
from iol import IOLError

log = logging.getLogger("web")


def crear_app(monitor):
    app = Flask(__name__, static_folder="static", static_url_path="")

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/estado")
    def estado():
        with monitor.lock:
            filas = list(monitor.snapshot.values())
        filas.sort(key=lambda f: (
            0 if f.get("zona") in ("alta", "baja") else 1, f.get("alias", "")
        ))
        return jsonify({
            "pares": [_limpiar(f) for f in filas],
            "ciclo": monitor.ultimo_ciclo.isoformat(timespec="seconds")
            if monitor.ultimo_ciclo else None,
            "error": monitor.ultimo_error,
            "en_rueda": monitor._en_horario(),
        })

    @app.get("/api/serie")
    def serie():
        alias = request.args.get("alias", "")
        modo = request.args.get("modo", "diario")
        par = monitor.par_por_alias(alias)
        if not par:
            return jsonify({"error": "par desconocido"}), 404

        if modo == "intra":
            puntos = [
                {"x": ts, "y": v}
                for ts, v in db.serie_intradiaria(alias, 600)
            ]
        else:
            dias = int(request.args.get("dias", 180))
            desde = (datetime.now().date() - timedelta(days=dias)).isoformat()
            puntos = [
                {"x": f, "y": v}
                for f, v in db.serie_ratio_diaria(par["num"], par["den"], desde)
            ]

        return jsonify({
            "alias": alias,
            "puntos": puntos,
            "resistencia": par.get("resistencia") or 0,
            "soporte": par.get("soporte") or 0,
        })

    @app.get("/api/calc")
    def calc():
        """Ratio al vuelo entre dos especies cualquiera."""
        num = (request.args.get("num") or "").strip().upper()
        den = (request.args.get("den") or "").strip().upper()
        mercado = (request.args.get("mercado") or "bCBA").strip()
        plazo = (request.args.get("plazo") or "t2").strip()
        dias = int(request.args.get("dias", 180))

        if not num or not den:
            return jsonify({"error": "Indicá las dos especies."}), 400

        try:
            a = monitor.iol.cotizacion(mercado, num, plazo)
            b = monitor.iol.cotizacion(mercado, den, plazo)
        except IOLError as e:
            return jsonify({"error": str(e)}), 502

        if not a["ref"] or not b["ref"]:
            faltan = num if not a["ref"] else den
            return jsonify({
                "error": f"{faltan} no tiene precio ahora. "
                         "Revisá el ticker o el plazo."
            }), 404

        ratio = a["ref"] / b["ref"]

        # historico bajo demanda: solo si falta en la base
        for sim in (num, den):
            if not db.ultimo_cierre_guardado(sim):
                _traer_historico(monitor, mercado, sim, dias)

        desde = (datetime.now().date() - timedelta(days=dias)).isoformat()
        serie = db.serie_ratio_diaria(num, den, desde)
        valores = [v for _, v in serie]

        est = {"n": len(valores)}
        if len(valores) >= 5:
            est["media"] = statistics.mean(valores)
            est["desvio"] = statistics.pstdev(valores)
            est["min"] = min(valores)
            est["max"] = max(valores)
            if est["desvio"]:
                est["z"] = (ratio - est["media"]) / est["desvio"]

        return jsonify({
            "alias": f"{num}/{den}",
            "ratio": ratio,
            "num": _limpiar_precio(a),
            "den": _limpiar_precio(b),
            "est": est,
            "puntos": [{"x": f, "y": v} for f, v in serie],
        })

    # -- exploracion de la API ---------------------------------------

    @app.get("/api/explorar/instrumentos")
    def ex_instrumentos():
        pais = request.args.get("pais", "argentina")
        try:
            return jsonify(monitor.iol.instrumentos(pais))
        except IOLError as e:
            return jsonify({"error": str(e)}), 502

    @app.get("/api/explorar/paneles")
    def ex_paneles():
        pais = request.args.get("pais", "argentina")
        instrumento = request.args.get("instrumento", "Acciones")
        try:
            return jsonify(monitor.iol.paneles(instrumento, pais))
        except IOLError as e:
            return jsonify({"error": str(e)}), 502

    @app.get("/api/explorar/panel")
    def ex_panel():
        """Baja un panel entero y resume lo que interesa saber de él."""
        pais = request.args.get("pais", "argentina")
        instrumento = request.args.get("instrumento", "Bonos")
        panel = request.args.get("panel", "")
        if not panel:
            return jsonify({"error": "Elegí un panel."}), 400

        try:
            d = monitor.iol.cotizacion_panel(instrumento, panel, pais)
        except IOLError as e:
            return jsonify({"error": str(e)}), 502

        titulos = (d or {}).get("titulos") or []
        filas = []
        con_puntas = 0
        for t in titulos:
            p = t.get("puntas") or {}
            if isinstance(p, list):
                p = p[0] if p else {}
            compra = p.get("precioCompra") or 0
            venta = p.get("precioVenta") or 0
            if compra or venta:
                con_puntas += 1
            filas.append({
                "simbolo": t.get("simbolo"),
                "ultimo": t.get("ultimoPrecio") or 0,
                "compra": compra,
                "venta": venta,
                "cant_compra": p.get("cantidadCompra") or 0,
                "cant_venta": p.get("cantidadVenta") or 0,
                "moneda": t.get("moneda") or "",
                "plazo": t.get("plazo") or "",
                "fecha": (t.get("fecha") or "")[:19],
            })

        filas.sort(key=lambda f: f["simbolo"] or "")
        simbolos = [f["simbolo"] or "" for f in filas]

        return jsonify({
            "panel": panel,
            "instrumento": instrumento,
            "total": len(filas),
            "con_puntas": con_puntas,
            # lo que queremos averiguar: ¿están las especies D y C?
            "especies_d": [s for s in simbolos if s.endswith("D")],
            "especies_c": [s for s in simbolos if s.endswith("C")],
            "monedas": sorted({f["moneda"] for f in filas if f["moneda"]}),
            "plazos": sorted({f["plazo"] for f in filas if f["plazo"]}),
            "titulos": filas,
            # una muestra cruda, para ver campos que no estoy mapeando
            "muestra_cruda": titulos[0] if titulos else None,
        })

    @app.get("/api/explorar/raw")
    def ex_raw():
        """GET a cualquier ruta. Solo lectura: se rechaza todo lo que opere."""
        path = (request.args.get("path") or "").strip()
        if not path:
            return jsonify({"error": "Escribí una ruta."}), 400

        prohibido = ("operar", "comprar", "vender", "cancelar", "token")
        if any(p in path.lower() for p in prohibido):
            return jsonify({
                "error": "Esta pestaña es solo de lectura. "
                         "No se permiten rutas de operación."
            }), 403

        try:
            return jsonify({"path": path, "respuesta": monitor.iol.get(path)})
        except IOLError as e:
            return jsonify({"error": str(e)}), 502

    @app.get("/api/alertas")
    def alertas():
        filas = db.alertas_recientes(40)
        return jsonify([{
            "ts": f["ts"], "alias": f["alias"], "tipo": f["tipo"],
            "ratio": f["ratio"], "nivel": f["nivel"],
        } for f in filas])

    return app


def _traer_historico(monitor, mercado, simbolo, dias):
    hasta = datetime.now().date()
    desde = hasta - timedelta(days=max(dias, 400))
    try:
        datos = monitor.iol.serie(mercado, simbolo, desde.isoformat(), hasta.isoformat())
    except IOLError as e:
        log.warning("historico %s: %s", simbolo, e)
        return
    filas = []
    for p in datos or []:
        f = str(p.get("fechaHora") or "")[:10]
        c = p.get("ultimoPrecio") or p.get("cierreAnterior")
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if f and c > 0:
            filas.append((f, c))
    if filas:
        db.guardar_cierres(simbolo, filas)


def _limpiar_precio(p):
    return {k: p[k] for k in ("ultimo", "compra", "venta", "ref", "variacion")}


def _limpiar(f):
    if not f:
        return {}
    out = {
        "alias": f.get("alias"),
        "num": f.get("num"), "den": f.get("den"),
        "ratio": f.get("ratio"),
        "zona": f.get("zona"),
        "resistencia": f.get("resistencia"),
        "soporte": f.get("soporte"),
        "z": f.get("z"),
        "ts": f.get("ts"),
        "alertas": f.get("alertas"),
        "error": f.get("error"),
    }
    est = f.get("est") or {}
    out["est"] = {k: est.get(k) for k in ("n", "media", "desvio", "min", "max")}
    for lado in ("p_num", "p_den"):
        if f.get(lado):
            out[lado] = _limpiar_precio(f[lado])
    return out
