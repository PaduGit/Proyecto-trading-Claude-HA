"""Screener web. Se sirve por Ingress: todas las rutas son relativas."""

import logging
import statistics
import threading
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_from_directory

import db
import bonos as BO
import cer as CER
import circuitos as CI
import costos as CO
import curva as CU
import historico as H
import opciones as OP
import posicion as P
import respaldo
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
        html = html.replace(
            "<body>",
            '<body data-slug="%s" data-version="%s">' % (cfg_slug, _version()), 1)
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
            "snapshot_desde": getattr(monitor, "snapshot_desde", None),
        })

    @app.post("/api/refrescar")
    def refrescar():
        with monitor.iol.como("boton"):
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
            with monitor.iol.como("pestania"):
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
        """Precio de referencia de cada ticker del grupo.

        Fuera de rueda no se pide nada: con el mercado cerrado el ticker
        que falta va a seguir faltando, y pedirlo uno por uno en cada
        visita a Posicion era de lo que mas consumia.
        """
        precios = {}
        cache = monitor.cotizaciones_vigentes()
        abierto = monitor._en_horario()
        for tk in grupo["tickers"]:
            c = cache.get(tk)
            if not c and abierto:
                try:
                    with monitor.iol.como("pestania"):
                        c = monitor.iol.cotizacion(
                            grupo.get("mercado") or "bCBA", tk)
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

    _cache_bonos = {"ts": None, "datos": None}
    VIDA_CACHE = 20          # segundos
    _sin_precio = set()      # especies que IOL no cotiza: no insistir

    def _cot_bonos():
        """Cotizaciones de las especies con cronograma.

        Casi todo viene del panel del último ciclo. Lo que no vino se pide
        suelto, con dos cuidados: se cachea unos segundos —entre dos
        aperturas seguidas los precios no cambiaron— y se deja de insistir
        con las que IOL no cotiza.
        """
        ahora = datetime.now()
        c = _cache_bonos
        if c["datos"] is not None and c["ts"] and \
                (ahora - c["ts"]).total_seconds() < VIDA_CACHE:
            return c["datos"]

        # Con la rueda cerrada no se pide nada: los precios no se mueven
        # y cada consulta gasta cupo mensual de la API. Se responde con lo
        # ultimo guardado, marcado como viejo.
        if not monitor._en_horario():
            datos = monitor.cotizaciones_vigentes()
            c["datos"], c["ts"] = datos, ahora
            return datos

        cache = dict(monitor.cotizaciones)
        faltan = [s for s in BO.especies()
                  if s not in cache and s not in _sin_precio]
        # Los paneles cubren los dolarizados y los cinco del canje 2005.
        # Los BONCER sueltos (TZX*, TX28, TX31, X30S6, PBA28) no estan en
        # ningun panel y hay que pedirlos de a uno: el tope tiene que
        # alcanzarlos a todos o los ultimos nunca aparecen.
        for sim in faltan[:30]:
            try:
                with monitor.iol.como("pestania"):
                    cache[sim] = monitor.iol.cotizacion("bCBA", sim, "t1")
            except Exception:
                _sin_precio.add(sim)
                continue     # una especie sin precio no puede tumbar la tabla

        c["ts"], c["datos"] = ahora, cache
        return cache

    @app.post("/api/bonos/reintentar")
    def bonos_reintentar():
        """Vuelve a intentar las especies que quedaron sin precio."""
        n = len(_sin_precio)
        _sin_precio.clear()
        _cache_bonos["datos"] = None
        return jsonify({"reintentadas": n})

    @app.get("/api/bonos")
    def bonos_tabla():
        try:
            par = (monitor.cfg.get("mep_par_pesos") or "AL30",
                   monitor.cfg.get("mep_par_usd") or "AL30D")
            cer = float(monitor.cfg.get("cer_actual") or 0)
            t = BO.tabla(_cot_bonos(), par_mep=par, cer_actual=cer)
            try:
                an = CU.analizar(t["filas"])
                for f in t["filas"]:
                    f.update(an.get(f["simbolo"]) or {})
            except Exception as e:
                log.warning("curva: %s", e)
            return jsonify(t)
        except Exception as e:
            log.exception("tabla de bonos")
            return jsonify({"error": str(e)}), 500

    @app.get("/api/bonos/<simbolo>")
    def bono_detalle(simbolo):
        try:
            par = (monitor.cfg.get("mep_par_pesos") or "AL30",
                   monitor.cfg.get("mep_par_usd") or "AL30D")
            cer = float(monitor.cfg.get("cer_actual") or 0)
            cot = _cot_bonos()
            d = BO.detalle(simbolo.upper(), cot, par_mep=par, cer_actual=cer)
            if d:
                try:
                    t = BO.tabla(cot, par_mep=par, cer_actual=cer)
                    an = CU.analizar(t["filas"])
                    d["fila"].update(an.get(simbolo.upper()) or {})
                except Exception as e:
                    log.debug("curva en detalle: %s", e)
        except Exception as e:
            log.exception("detalle de bono")
            return jsonify({"error": str(e)}), 500
        if not d:
            return jsonify({"error": "no tengo cronograma de %s" % simbolo}), 404
        return jsonify(d)

    @app.get("/api/circuitos")
    def circuitos_ver():
        try:
            cot = _cot_bonos()
            bonos_cfg, _ = BO.cargar()
            esps = BO.especies()
            # Un bono sirve, como origen y como puente, si cotiza en pesos
            # y en MEP. Sin las dos puntas no hay salto posible: el PARP
            # solo cotiza en pesos, así que venderlo y recomprarlo paga su
            # propio spread sin convertir nada.
            puentes = [b for b in bonos_cfg if (b + "D") in esps]
            tengo = db.get_estado("rulo_tengo")
            import json as _j
            tengo = _j.loads(tengo) if tengo else {"monedas": [], "bonos": []}
            # los bonos declarados se suman al universo aunque les falte
            # alguna especie: pueden ser origen aunque no sean intermedios
            universo = sorted(set(puentes) | set(tengo.get("bonos") or []))
            # El ciclo ya lo calculo: recalcular aca solo repetiria
            # trabajo sobre las mismas cotizaciones.
            with monitor.lock:
                previo = dict(monitor.circuitos or {})
            if previo and not monitor._en_horario():
                r = previo
            else:
                r = CI.analizar(cot, universo, tengo,
                                monitor.cfg.get("comisiones") or {},
                                float(monitor.cfg.get("rulo_umbral_pct") or 0),
                                monitor.cfg.get("derechos_mercado") or {},
                                monitor.cfg.get("iva_pct") or 0,
                                CO.esquema(monitor.cfg))
            r["tengo"] = tengo
            r["candidatos"] = sorted(puentes)
            return jsonify(r)
        except Exception as e:
            log.exception("circuitos")
            return jsonify({"error": str(e)}), 500

    @app.post("/api/circuitos/tengo")
    def circuitos_tengo():
        d = request.get_json(silent=True) or {}
        import json as _j
        tengo = {"monedas": [m for m in (d.get("monedas") or [])
                             if m in CI.MONEDAS],
                 "bonos": [str(b).upper() for b in (d.get("bonos") or [])]}
        db.set_estado("rulo_tengo", _j.dumps(tengo))
        return jsonify(tengo)

    @app.get("/api/rulo")
    def rulo_tabla():
        try:
            umbral = float(monitor.cfg.get("rulo_umbral_pct") or 0.6)
            return jsonify(BO.rulo(_cot_bonos(), umbral))
        except Exception as e:
            log.exception("rulo")
            return jsonify({"error": str(e)}), 500

    def _cierres_subyacente(sim, mercado="bCBA"):
        """Cierres para las medias. Se rellenan desde IOL una vez por día."""
        from datetime import date, timedelta
        desde = (date.today() - timedelta(days=90)).isoformat()
        ultimo = db.ultimo_cierre_guardado(sim)
        if monitor._en_horario() and (
                not ultimo
                or ultimo < (date.today() - timedelta(days=1)).isoformat()):
            try:
                with monitor.iol.como("pestania"):
                    serie = monitor.iol.serie(mercado, sim, desde,
                                              date.today().isoformat())
                filas = []
                for p in serie or []:
                    f = str(p.get("fechaHora") or "")[:10]
                    c = p.get("ultimoPrecio") or p.get("cierre")
                    if f and c:
                        filas.append((f, float(c)))
                if filas:
                    db.guardar_cierres(sim, filas)
            except Exception as e:
                log.debug("cierres de %s: %s", sim, e)
        return [(r["fecha"], r["cierre"]) for r in db.cierres_de(sim, desde)]

    @app.get("/api/opciones")
    def opciones_tabla():
        try:
            cfg = monitor.cfg
            series, spots, diag, viejo, desde = monitor.cadena_opciones()
            par = monitor.parametros_opciones()
            cierres = {s: _cierres_subyacente(s) for s in spots}
            r = OP.analizar(series, spots, par,
                            cfg.get("comisiones") or {}, cierres,
                            cfg.get("derechos_mercado") or {},
                            cfg.get("iva_pct") or 0)
            marcas = db.opc_marcas()
            abiertas = {p["combo"] for p in db.opc_posiciones(abiertas=True)}
            for f in r["filas"]:
                m = marcas.get(f["id"]) or {}
                f["seguida"] = bool(m)
                f["silenciada"] = bool(m.get("silenciada"))
                f["con_posicion"] = f["id"] in abiertas
            r["diagnostico"] = {k: v for k, v in diag.items() if k != "muestra"}
            r["parametros"] = par
            r["viejo"] = viejo
            r["desde"] = desde
            r["sin_puntas"] = diag["con_puntas"] == 0
            r["nunca_hubo"] = viejo is False and diag["con_puntas"] == 0
            r["hay_rueda"] = monitor.hay_rueda
            return jsonify(r)
        except Exception as e:
            log.exception("opciones")
            return jsonify({"error": str(e)}), 500

    @app.get("/api/opciones/historico/<combo>")
    def opciones_historico(combo):
        return jsonify(db.opc_serie(combo))

    @app.post("/api/opciones/marcar/<combo>")
    def opciones_marcar(combo):
        d = request.get_json(silent=True) or {}
        if "seguir" in d:
            db.opc_seguir(combo, bool(d["seguir"]))
        if "silenciar" in d:
            db.opc_silenciar(combo, bool(d["silenciar"]))
        return jsonify((db.opc_marcas().get(combo) or {"combo": combo}))

    @app.get("/api/opciones/posiciones")
    def opciones_posiciones():
        try:
            series, spots, _, viejo, desde = monitor.cadena_opciones()
            par = monitor.parametros_opciones()
        except Exception:
            series, spots, viejo, desde = [], {}, True, None
            par = monitor.parametros_opciones()
        salida = []
        for p in db.opc_posiciones():
            v = OP.valuar(p, series) if not p["cerrada_el"] else None
            p["valuacion"] = v
            if not p["cerrada_el"]:
                p["motivos"] = OP.motivos_desarme(
                    p, v, spots.get(p["subyacente"]), par)
                p["spot"] = spots.get(p["subyacente"])
            salida.append(p)
        return jsonify({"posiciones": salida, "viejo": viejo, "desde": desde})

    @app.post("/api/opciones/posiciones")
    def opciones_crear():
        d = request.get_json(silent=True) or {}
        faltan = [k for k in ("combo", "subyacente", "estructura",
                              "vencimiento", "base_compra", "base_venta",
                              "riesgo", "ancho") if d.get(k) is None]
        if faltan:
            return jsonify({"error": "faltan datos: %s" % ", ".join(faltan)}), 400
        try:
            pid = db.opc_crear_posicion(d)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"id": pid})

    @app.post("/api/opciones/posiciones/<int:pid>")
    def opciones_editar(pid):
        d = request.get_json(silent=True) or {}
        return jsonify({"cambiados": db.opc_actualizar_posicion(pid, d)})

    @app.post("/api/opciones/posiciones/<int:pid>/cerrar")
    def opciones_cerrar(pid):
        d = request.get_json(silent=True) or {}
        if d.get("precio_salida") is None:
            return jsonify({"error": "falta el precio de salida"}), 400
        try:
            salida = float(d["precio_salida"])
        except (TypeError, ValueError):
            return jsonify({"error": "precio de salida invalido"}), 400
        pos = next((p for p in db.opc_posiciones() if p["id"] == pid), None)
        if not pos:
            return jsonify({"error": "no existe"}), 404
        # el resultado sale del precio realmente ejecutado, no del teorico
        if pos["estructura"] == "BEAR_CALL":
            gan = (pos["ancho"] - pos["riesgo"]) + salida
        else:
            gan = salida - pos["riesgo"]
        total = round(gan * OP.LOTE * (pos["lotes"] or 1), 2)
        db.opc_cerrar_posicion(pid, salida, total)
        return jsonify({"id": pid, "resultado": total})

    @app.post("/api/opciones/posiciones/<int:pid>/borrar")
    def opciones_borrar(pid):
        return jsonify({"borradas": db.opc_borrar_posicion(pid)})

    @app.get("/api/opciones/crudo")
    def opciones_crudo():
        """Una serie tal cual la manda IOL, para ver qué campos trae."""
        try:
            subs = [s.strip().upper()
                    for s in (monitor.cfg.get("opc_subyacentes")
                              or "GGAL").split(",") if s.strip()]
            _, diag = OP.cadena(
                monitor.iol, subs,
                panel=monitor.cfg.get("opc_panel") or "De Acciones")
            return jsonify(diag)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/api/cer")
    def cer_estado():
        try:
            bonos_cfg, _ = BO.cargar()
            actual = CER.vigente()
            det = []
            for tk, cfg in bonos_cfg.items():
                if (cfg.get("ajuste") or "").lower() != "cer":
                    continue
                base = cfg.get("cer_base") or CER.base_de(cfg.get("emision"))
                det.append({
                    "ticker": tk, "emision": str(cfg.get("emision"))[:10],
                    "cer_base": base,
                    "factor": (actual / base) if (base and actual) else None,
                })
            return jsonify({"vigente": actual,
                            "rezago_habiles": CER.REZAGO_HABILES,
                            "ultimo_error": CER.ultimo_error,
                            "bonos": det})
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    @app.post("/api/cer/probar")
    def cer_probar():
        """Fuerza una consulta al BCRA y devuelve el error si falla."""
        from datetime import date as _d, timedelta as _t
        CER.reintentar_ya()
        hoy = _d.today()
        n = CER.descargar((hoy - _t(days=30)).isoformat(), hoy.isoformat())
        bonos_cfg, _ = BO.cargar()
        act = CER.vigente()
        det = []
        for tk, cfg in bonos_cfg.items():
            if (cfg.get("ajuste") or "").lower() != "cer":
                continue
            emi = str(cfg.get("emision"))[:10]
            base = cfg.get("cer_base") or CER.base_de(emi)
            det.append("%s emi %s base %s factor %s" % (
                tk, emi, round(base, 2) if base else "?",
                round(act / base, 4) if (base and act) else "?"))
        rango = db.conn().execute(
            "SELECT MIN(fecha) a, MAX(fecha) b, COUNT(*) n FROM cer").fetchone()
        return jsonify({"dias_traidos": n, "vigente": act,
                        "error": CER.ultimo_error,
                        "respuesta": CER.ultima_respuesta,
                        "rango": "%s a %s (%s días)" % (
                            rango["a"], rango["b"], rango["n"]),
                        "bonos": det})

    @app.get("/api/bonos/<simbolo>/historico")
    def bono_historico(simbolo):
        periodo = request.args.get("periodo", "1a")
        dias = {"3m": 90, "6m": 180, "1a": 365, "2a": 730,
                "max": 5000}.get(periodo, 365)
        desde = (datetime.now().date() - timedelta(days=dias)).isoformat()
        try:
            puntos = H.serie(simbolo.upper(), desde)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"simbolo": simbolo.upper(), "periodo": periodo,
                        "puntos": puntos})

    @app.post("/api/curva/reconstruir")
    def curva_reconstruir():
        try:
            n = CU.reconstruir()
        except Exception as e:
            log.exception("residuos")
            return jsonify({"error": str(e)}), 500
        r = db.conn().execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT simbolo) esp, "
            "MIN(fecha) a, MAX(fecha) b FROM residuo_hist").fetchone()
        return jsonify({"puntos": n, "total": r["n"], "especies": r["esp"],
                        "desde": r["a"], "hasta": r["b"]})

    @app.get("/api/historico/exportar")
    def historico_exportar():
        """Serie completa en CSV, para analizarla afuera."""
        desde = request.args.get("desde") or "2023-01-01"
        sims = (request.args.get("simbolos") or "").upper()
        q = ("SELECT simbolo, fecha, precio, tir, md, duration, residual, cer "
             "FROM bono_hist WHERE fecha >= ?")
        args = [desde]
        if sims:
            lista = [x.strip() for x in sims.split(",") if x.strip()]
            q += " AND simbolo IN (%s)" % ",".join("?" * len(lista))
            args += lista
        q += " ORDER BY simbolo, fecha"

        filas = db.conn().execute(q, args).fetchall()
        salida = ["simbolo,fecha,precio,tir,md,duration,residual,cer"]
        for f in filas:
            salida.append(",".join(
                "" if f[c] is None else
                ("%.6f" % f[c] if isinstance(f[c], float) else str(f[c]))
                for c in ("simbolo", "fecha", "precio", "tir", "md",
                          "duration", "residual", "cer")))
        texto = "\n".join(salida)
        return app.response_class(
            texto, mimetype="text/csv",
            headers={"Content-Disposition":
                     "attachment; filename=historico_tir.csv"})

    @app.get("/api/historico/estado")
    def historico_estado():
        r = H.resumen()
        try:
            r["sin_serie"] = H.sin_serie()
        except Exception:
            r["sin_serie"] = []
        return jsonify(r)

    @app.post("/api/historico/reconstruir")
    def historico_reconstruir():
        sim = (request.args.get("simbolo") or "").upper() or None
        forzar = request.args.get("forzar") in ("1", "true", "si")
        try:
            n = H.reconstruir(monitor.iol, sim, forzar=forzar)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"puntos": n, "forzado": forzar,
                        "estado": H.resumen()})

    @app.get("/api/posicion/exportar")
    def exportar_posicion():
        try:
            return jsonify(respaldo.exportar_posicion())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.post("/api/posicion/importar")
    def importar_posicion():
        d = request.get_json(silent=True) or {}
        try:
            r = respaldo.importar_posicion(
                d.get("datos"), bool(d.get("reemplazar")))
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(r)

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

    @app.post("/api/requests/log/borrar")
    def requests_log_borrar():
        return jsonify({"borradas": db.borrar_api_log()})

    @app.get("/api/requests/log")
    def requests_log():
        return jsonify({
            "resumen": db.api_log_resumen(int(request.args.get("dias", 7))),
            "ultimas": db.api_log(int(request.args.get("limite", 200)),
                                  ruta=request.args.get("ruta") or None),
            "retencion_dias": db.RETENCION_API_LOG,
        })

    # -- exploracion --------------------------------------------------

    # La lista de instrumentos y la de paneles son catalogo: cambian
    # cuando BYMA agrega o saca un panel, no todos los dias. Pedirlas en
    # cada visita a Explorar gastaba dos requests por vez.
    HORAS_CATALOGO = 24 * 7

    @app.get("/api/explorar/instrumentos")
    def ex_instrumentos():
        pais = request.args.get("pais", "argentina")
        clave = "instrumentos:%s" % pais
        if request.args.get("recargar") != "1":
            v = db.cache_get(clave, HORAS_CATALOGO)
            if v is not None:
                return jsonify(v)
        try:
            with monitor.iol.como("pestania"):
                v = monitor.iol.instrumentos(pais)
        except IOLError as e:
            return jsonify({"error": str(e)}), 502
        db.cache_set(clave, v)
        return jsonify(v)

    @app.get("/api/explorar/paneles")
    def ex_paneles():
        inst = request.args.get("instrumento", "Acciones")
        pais = request.args.get("pais", "argentina")
        clave = "paneles:%s:%s" % (pais, inst)
        if request.args.get("recargar") != "1":
            v = db.cache_get(clave, HORAS_CATALOGO)
            if v is not None:
                return jsonify(v)
        try:
            with monitor.iol.como("pestania"):
                v = monitor.iol.paneles(inst, pais)
        except IOLError as e:
            return jsonify({"error": str(e)}), 502
        db.cache_set(clave, v)
        return jsonify(v)

    @app.post("/api/explorar/recargar-catalogo")
    def ex_recargar():
        return jsonify({"borradas": db.cache_borrar("")})

    @app.get("/api/explorar/panel")
    def ex_panel():
        pais = request.args.get("pais", "argentina")
        instrumento = request.args.get("instrumento", "Bonos")
        panel = request.args.get("panel", "")
        if not panel:
            return jsonify({"error": "Elegí un panel."}), 400
        try:
            with monitor.iol.como("pestania"):
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

def _version():
    """Lee la versión del config.yaml del add-on: una sola fuente de verdad."""
    import os
    candidatas = [
        "/config.yaml",                                    # copiado por el Dockerfile
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml"),
    ]
    for ruta in candidatas:
        try:
            with open(ruta, encoding="utf-8") as f:
                for linea in f:
                    if linea.startswith("version:"):
                        return linea.split(":", 1)[1].strip().strip('"\'')
        except Exception:
            continue
    return ""


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
        with monitor.iol.como("pestania"):
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
