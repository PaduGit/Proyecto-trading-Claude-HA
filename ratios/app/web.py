"""Screener web. Se sirve por Ingress: todas las rutas son relativas."""

import logging
import statistics
import threading
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_from_directory

import db
import bonos as BO
import posicion as P
from iol import IOLError

log = logging.getLogger("web")


def crear_app(monitor):
    app = Flask(__name__, static_folder="static", static_url_path="")

    @app.after_request
    def sin_cache(resp):
        if resp.mimetype in ("text/html", "application/javascript"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/")
    def index():
        import os
        ruta = os.path.join(app.static_folder, "index.html")
        with open(ruta, encoding="utf-8") as f:
            html = f.read()
        slug = os.environ.get("HOSTNAME", "") or ""
        slug = slug.replace("-", "_") if slug else ""
        cfg_slug = (monitor.cfg.get("addon_slug") or slug or "").strip()
        html = html.replace("<body>", '<body data-slug="%s">' % cfg_slug, 1)
        return app.response_class(html, mimetype="text/html")

    # -- panel --------------------------------------------------------

    @app.get("/api/estado")
    def estado():
        with monitor.lock:
            filas = list(monitor.snapshot.values())
        filas.sort(key=lambda f: (
            0 if f.get("zona") in ("alta", "baja") else 1, f.get("alias", "")))
        return jsonify({
            "pares": [_limpiar(f) for f in filas],
            "ciclo": monitor.ultimo_ciclo.isoformat(timespec="seconds")
            if monitor.ultimo_ciclo else None,
            "hace_seg": monitor.segundos_desde_ciclo(),
            "poll_seconds": int(monitor.cfg.get("poll_seconds", 600)),
            "error": monitor.ultimo_error,
            "en_rueda": monitor._en_horario(),
            "hay_rueda": monitor.hay_rueda,
        })

    @app.post("/api/refrescar")
    def refrescar():
        ok, falta = monitor.ciclo_manual()
        if not ok and falta:
            return jsonify({"ok": False,
                            "mensaje": "Esperá %ds antes de volver a pedir."
                                       % falta}), 429
        if not ok:
            return jsonify({"ok": False,
                            "mensaje": "Ya hay un ciclo en curso."}), 409
        return jsonify({"ok": True,
                        "ciclo": monitor.ultimo_ciclo.isoformat(timespec="seconds")})

    @app.get("/api/serie")
    def serie():
        alias = request.args.get("alias", "")
        periodo = request.args.get("periodo", "3m")
        par = monitor.par_por_alias(alias)
        if not par:
            return jsonify({"error": "par desconocido"}), 404

        dias = {"hoy": 1, "5d": 5, "1m": 30, "3m": 90,
                "6m": 180, "1a": 365, "max": 5000}.get(periodo, 90)
        intradiario = periodo in ("hoy", "5d")

        if intradiario:
            desde = (datetime.now() - timedelta(days=dias)).isoformat()
            filas = db.conn().execute(
                "SELECT ts, ratio, p_num FROM lecturas WHERE alias=? AND ts>=? "
                "ORDER BY ts", (alias, desde)).fetchall()
            puntos = [{"x": f["ts"], "y": f["ratio"],
                       "f": "propia" if f["p_num"] else "iol"} for f in filas]
        else:
            desde = (datetime.now().date() - timedelta(days=dias)).isoformat()
            propia = dict(db.serie_propia_diaria(alias, desde))
            iol = dict(db.serie_ratio_diaria(par["num"], par["den"], desde))
            puntos = []
            for f in sorted(set(propia) | set(iol)):
                if f in propia:
                    puntos.append({"x": f, "y": propia[f], "f": "propia"})
                else:
                    puntos.append({"x": f, "y": iol[f], "f": "iol"})

        n_iol = sum(1 for p in puntos if p["f"] == "iol")
        return jsonify({
            "alias": alias, "puntos": puntos, "periodo": periodo,
            "n_iol": n_iol, "n_propia": len(puntos) - n_iol,
            "resistencia": par.get("resistencia") or 0,
            "soporte": par.get("soporte") or 0,
        })

    # -- calculadora --------------------------------------------------

    @app.get("/api/calc")
    def calc():
        num = (request.args.get("num") or "").strip().upper()
        den = (request.args.get("den") or "").strip().upper()
        mercado = (request.args.get("mercado") or "bCBA").strip()
        plazo = (request.args.get("plazo") or "t1").strip()
        dias = int(request.args.get("dias", 180))

        if not num or not den:
            return jsonify({"error": "Indicá las dos especies."}), 400

        cache = monitor.cotizaciones
        try:
            a = cache.get(num) or monitor.iol.cotizacion(mercado, num, plazo)
            b = cache.get(den) or monitor.iol.cotizacion(mercado, den, plazo)
        except IOLError as e:
            return jsonify({"error": str(e)}), 502

        if not a["ref"] or not b["ref"]:
            faltan = num if not a["ref"] else den
            return jsonify({"error": "%s no tiene precio ahora. "
                                     "Revisá el ticker o el plazo." % faltan}), 404

        ratio = a["ref"] / b["ref"]
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

        db.set_estado("ultimo_par", "%s/%s" % (num, den))
        _recordar_par(num, den, mercado, plazo)

        return jsonify({
            "alias": "%s/%s" % (num, den), "ratio": ratio,
            "num": _p(a), "den": _p(b), "est": est,
            "puntos": [{"x": f, "y": v} for f, v in serie],
        })

    @app.get("/api/recientes")
    def recientes():
        return jsonify({
            "tickers": _tickers_conocidos(),
            "pares": _pares_recientes(),
        })

    # -- arbitraje t0/t1 ----------------------------------------------

    @app.get("/api/arbitraje")
    def arbitraje():
        try:
            filas = monitor.evaluar_arbitraje()
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({
            "filas": filas,
            "tasa_caucion_anual": monitor.cfg.get("tasa_caucion_anual"),
            "ts": datetime.now().isoformat(timespec="seconds"),
        })

    # -- operaciones --------------------------------------------------

    @app.post("/api/operaciones")
    def nueva_operacion():
        d = request.get_json(silent=True) or {}
        alias = (d.get("alias") or "").strip()
        if not alias:
            return jsonify({"error": "Falta el par."}), 400
        try:
            cantidad = float(d.get("cantidad") or 0)
            pn = float(d.get("precio_num") or 0)
            pd = float(d.get("precio_den") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "Cantidad y precios tienen que ser números."}), 400
        if not pn or not pd:
            return jsonify({"error": "Cargá los dos precios efectivos."}), 400

        oid = db.registrar_operacion(
            alias, (d.get("lado") or "entrada"), cantidad, pn, pd,
            d.get("alerta_id"), (d.get("nota") or "").strip() or None)
        return jsonify({"ok": True, "id": oid, "ratio": pn / pd})

    @app.get("/api/operaciones")
    def listar_operaciones():
        filas = db.operaciones_recientes(60)
        return jsonify([{
            "id": f["id"], "ts": f["ts"], "alias": f["alias"],
            "lado": f["lado"], "cantidad": f["cantidad"],
            "precio_num": f["precio_num"], "precio_den": f["precio_den"],
            "ratio": f["ratio"], "nota": f["nota"],
        } for f in filas])

    # -- posicion -----------------------------------------------------

    def _precios_para(grupo):
        """Precio de referencia de cada ticker del grupo."""
        precios = {}
        cache = monitor.cotizaciones
        for tk in grupo["tickers"]:
            c = cache.get(tk)
            if not c:
                try:
                    c = monitor.iol.cotizacion(grupo.get("mercado") or "bCBA", tk)
                except IOLError:
                    continue
            if c and c.get("ref"):
                precios[tk] = c["ref"]
        return precios

    @app.get("/api/grupos")
    def listar_grupos():
        salida = []
        for g in db.listar_grupos():
            precios = _precios_para(g)
            r = P.resumen(g, precios)
            salida.append({
                "id": g["id"], "nombre": g["nombre"], "base": g["base"],
                "tickers": g["tickers"], "mercado": g["mercado"],
                "precios": precios,
                "equivalente": r["equivalente"],
                "base_ajustada": r["base_ajustada"],
                "rendimiento_pct": r["rendimiento_pct"],
                "ganancia_nominal": r["ganancia_nominal"],
                "valor_cuota": r["valor_cuota"],
                "faltan_precios": r["faltan_precios"],
                "tenencia": [
                    {"ticker": k, "cantidad": v["cantidad"],
                     "equivalente": v["equivalente"], "precio": v["precio"]}
                    for k, v in sorted(r["tenencia"].items())],
            })
        return jsonify(salida)

    @app.post("/api/grupos")
    def nuevo_grupo():
        d = request.get_json(silent=True) or {}
        nombre = (d.get("nombre") or "").strip()
        base = (d.get("base") or "").strip().upper()
        tickers = [t.strip().upper() for t in (d.get("tickers") or [])
                   if t and t.strip()]
        if not nombre:
            return jsonify({"error": "Poné un nombre al grupo."}), 400
        if len(tickers) < 2:
            return jsonify({"error": "Cargá al menos dos tickers."}), 400
        if base not in tickers:
            return jsonify({"error": "La base tiene que ser uno de los tickers."}), 400
        if any(g["nombre"].lower() == nombre.lower() for g in db.listar_grupos()):
            return jsonify({"error": "Ya existe un grupo con ese nombre."}), 400
        gid = db.crear_grupo(nombre, base, tickers,
                             (d.get("mercado") or "bCBA").strip())
        return jsonify({"ok": True, "id": gid})

    @app.delete("/api/grupos/<int:gid>")
    def eliminar_grupo(gid):
        db.borrar_grupo(gid)
        return jsonify({"ok": True})

    @app.get("/api/grupos/<int:gid>/movimientos")
    def listar_movimientos(gid):
        g = db.grupo_por_id(gid)
        if not g:
            return jsonify({"error": "grupo desconocido"}), 404
        filas = db.movimientos_de(gid)
        return jsonify({
            "movimientos": [{
                "id": m["id"], "ts": m["ts"], "tipo": m["tipo"],
                "ticker_de": m["ticker_de"], "cant_de": m["cant_de"],
                "ticker_a": m["ticker_a"], "cant_a": m["cant_a"],
                "ratio_base": m["ratio_base"], "nota": m["nota"],
            } for m in reversed(filas)],
            "curva": P.curva(g, _precios_para(g)),
        })

    @app.post("/api/grupos/<int:gid>/movimientos")
    def nuevo_movimiento(gid):
        g = db.grupo_por_id(gid)
        if not g:
            return jsonify({"error": "grupo desconocido"}), 404
        d = request.get_json(silent=True) or {}
        limpio, error = P.validar_movimiento(g, d)
        if error:
            return jsonify({"error": error}), 400

        antes = None
        if limpio["tipo"] in ("aporte", "retiro"):
            antes, _, _ = P.equivalente(g, P.tenencia(gid), _precios_para(g))

        mid = db.registrar_movimiento(gid, equiv_antes=antes, **limpio)
        r = P.resumen(g, _precios_para(g))
        return jsonify({"ok": True, "id": mid,
                        "equivalente": r["equivalente"],
                        "rendimiento_pct": r["rendimiento_pct"]})

    @app.delete("/api/movimientos/<int:mid>")
    def eliminar_movimiento(mid):
        db.borrar_movimiento(mid)
        return jsonify({"ok": True})

    @app.delete("/api/operaciones/<int:oid>")
    def eliminar_operacion(oid):
        db.borrar_operacion(oid)
        return jsonify({"ok": True})

    # -- bonos --------------------------------------------------------

    def _cot_bonos():
        """Cotizaciones de las especies con cronograma, desde el panel."""
        cache = dict(monitor.cotizaciones)
        faltan = [s for s in BO.especies() if s not in cache]
        for sim in faltan[:12]:      # tope, para no disparar decenas de requests
            try:
                cache[sim] = monitor.iol.cotizacion("bCBA", sim, "t1")
            except Exception:
                continue     # una especie sin precio no puede tumbar la tabla
        return cache

    @app.get("/api/bonos")
    def bonos_tabla():
        try:
            par = (monitor.cfg.get("mep_par_pesos") or "AL30",
                   monitor.cfg.get("mep_par_usd") or "AL30D")
            return jsonify(BO.tabla(_cot_bonos(), par_mep=par))
        except Exception as e:
            log.exception("tabla de bonos")
            return jsonify({"error": str(e)}), 500

    @app.get("/api/bonos/<simbolo>")
    def bono_detalle(simbolo):
        try:
            par = (monitor.cfg.get("mep_par_pesos") or "AL30",
                   monitor.cfg.get("mep_par_usd") or "AL30D")
            d = BO.detalle(simbolo.upper(), _cot_bonos(), par_mep=par)
        except Exception as e:
            log.exception("detalle de bono")
            return jsonify({"error": str(e)}), 500
        if not d:
            return jsonify({"error": "no tengo cronograma de %s" % simbolo}), 404
        return jsonify(d)

    @app.get("/api/rulo")
    def rulo_tabla():
        try:
            umbral = float(monitor.cfg.get("rulo_umbral_pct") or 0.6)
            return jsonify(BO.rulo(_cot_bonos(), umbral))
        except Exception as e:
            log.exception("rulo")
            return jsonify({"error": str(e)}), 500

    @app.get("/api/notificaciones/diagnostico")
    def notif_diag():
        return jsonify(monitor.notif.diagnostico())

    @app.post("/api/notificaciones/probar")
    def notif_probar():
        return jsonify(monitor.notif.probar())

    @app.get("/api/alertas")
    def alertas():
        filas = db.alertas_recientes(40)
        return jsonify([_fila(f, "id", "ts", "alias", "tipo", "ratio",
                              "nivel", "p_num", "p_den") for f in filas])

    # -- consumo ------------------------------------------------------

    @app.get("/api/requests")
    def requests_stats():
        return jsonify(db.resumen_requests(30))

    # -- exploracion --------------------------------------------------

    @app.get("/api/explorar/instrumentos")
    def ex_instrumentos():
        try:
            return jsonify(monitor.iol.instrumentos(
                request.args.get("pais", "argentina")))
        except IOLError as e:
            return jsonify({"error": str(e)}), 502

    @app.get("/api/explorar/paneles")
    def ex_paneles():
        try:
            return jsonify(monitor.iol.paneles(
                request.args.get("instrumento", "Acciones"),
                request.args.get("pais", "argentina")))
        except IOLError as e:
            return jsonify({"error": str(e)}), 502

    @app.get("/api/explorar/panel")
    def ex_panel():
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
                "compra": compra, "venta": venta,
                "cant_compra": p.get("cantidadCompra") or 0,
                "cant_venta": p.get("cantidadVenta") or 0,
                "moneda": t.get("moneda") or "",
                "plazo": t.get("plazo") or "",
            })
        filas.sort(key=lambda f: f["simbolo"] or "")
        simbolos = [f["simbolo"] or "" for f in filas]
        return jsonify({
            "panel": panel, "instrumento": instrumento,
            "total": len(filas), "con_puntas": con_puntas,
            "especies_d": [s for s in simbolos if s.endswith("D")],
            "especies_c": [s for s in simbolos if s.endswith("C")],
            "monedas": sorted({f["moneda"] for f in filas if f["moneda"]}),
            "plazos": sorted({f["plazo"] for f in filas if f["plazo"]}),
            "titulos": filas,
            "muestra_cruda": titulos[0] if titulos else None,
        })

    @app.get("/api/explorar/raw")
    def ex_raw():
        path = (request.args.get("path") or "").strip()
        if not path:
            return jsonify({"error": "Escribí una ruta."}), 400
        prohibido = ("operar", "comprar", "vender", "cancelar", "token")
        if any(p in path.lower() for p in prohibido):
            return jsonify({"error": "Esta pestaña es solo de lectura."}), 403
        try:
            return jsonify({"path": path, "respuesta": monitor.iol.get(path)})
        except IOLError as e:
            return jsonify({"error": str(e)}), 502

    return app


# -- auxiliares -------------------------------------------------------

def _recordar_par(num, den, mercado, plazo):
    import json
    try:
        prev = json.loads(db.get_estado("pares_usados") or "[]")
    except ValueError:
        prev = []
    entrada = {"num": num, "den": den, "mercado": mercado, "plazo": plazo}
    prev = [p for p in prev
            if not (p.get("num") == num and p.get("den") == den)]
    prev.insert(0, entrada)
    db.set_estado("pares_usados", json.dumps(prev[:20]))


def _pares_recientes():
    import json
    try:
        return json.loads(db.get_estado("pares_usados") or "[]")
    except ValueError:
        return []


def _tickers_conocidos():
    filas = db.conn().execute(
        "SELECT DISTINCT simbolo FROM cierres ORDER BY simbolo").fetchall()
    return [f["simbolo"] for f in filas]


def _traer_historico(monitor, mercado, simbolo, dias):
    hasta = datetime.now().date()
    desde = hasta - timedelta(days=max(dias, 400))
    try:
        datos = monitor.iol.serie(mercado, simbolo, desde.isoformat(),
                                  hasta.isoformat())
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


def _fila(f, *campos):
    """Lee solo las columnas que existan: tolera bases de versiones viejas."""
    try:
        presentes = set(f.keys())
    except Exception:
        presentes = set()
    return {c: (f[c] if c in presentes else None) for c in campos}


def _p(p):
    return {k: p.get(k) for k in
            ("ultimo", "compra", "venta", "ref", "variacion",
             "vol_compra", "vol_venta")}


def _limpiar(f):
    if not f:
        return {}
    out = {k: f.get(k) for k in
           ("alias", "num", "den", "ratio", "zona", "resistencia", "soporte",
            "z", "ts", "alertas", "error", "alerta_id", "origen", "cerca")}
    est = f.get("est") or {}
    out["est"] = {k: est.get(k) for k in
                  ("n", "media", "desvio", "min", "max", "fuente", "aviso")}
    for lado in ("p_num", "p_den"):
        if f.get(lado):
            out[lado] = _p(f[lado])
    return out
