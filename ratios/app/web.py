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

        # La posicion NO va aca. Este panel es de alertas: un par puede
        # tener sus dos puntas en estrategias distintas o en ninguna, y
        # el mismo numero en dos pantallas se desincroniza. Vive en el
        # panel de la estrategia y en ningun otro lado.

        salida = []
        for f in filas:
            salida.append(_limpiar(f))

        return jsonify({
            "pares": salida,
            "ciclo": monitor.ultimo_ciclo.isoformat(timespec="seconds")
            if monitor.ultimo_ciclo else None,
            "hace_seg": monitor.segundos_desde_ciclo(),
            "poll_seconds": int(monitor.cfg.get("poll_seconds", 600)),
            "error": monitor.ultimo_error,
            "en_rueda": monitor._en_horario(),
            "hay_rueda": monitor.hay_rueda,
            "snapshot_desde": getattr(monitor, "snapshot_desde", None),
            "sin_cotizacion": getattr(monitor, "sin_cotizacion", []),
            "orleans_fallas": getattr(monitor, "orleans_fallas", []),
            "orleans_descartados": getattr(monitor, "orleans_descartados", []),
            "fuente": getattr(monitor, "fuente", "iol"),
            "fuente_elegida": monitor.fuente_elegida(),
            "canjes": len(getattr(monitor, "canjes", [])),
            "byma_fallas": getattr(monitor, "byma_fallas", []),
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
            with monitor.lock:
                previo = list(monitor.plazos or [])
            if not monitor._en_horario():
                # Fuera de rueda no se pide nunca, aunque no haya previo:
                # el t0 con el mercado cerrado no existe, asi que pedirlo
                # solo gasta cupo para devolver lo mismo.
                filas = previo
            else:
                with monitor.iol.como("pestania"):
                    filas = monitor.evaluar_arbitraje()
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        tasa, origen_tasa = monitor.tasa_caucion()
        return jsonify({
            "filas": filas,
            "hay_rueda": monitor._en_horario(),
            "tasa_origen": origen_tasa,
            "tasa_caucion_anual": tasa,
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

    def _precios_vigentes():
        """Precio de referencia de todo lo que ya esta en cache.

        No pide nada: se usa al guardar la tenencia, para que el diff
        registre el precio del momento de la foto, y para valuar.
        """
        return {s: c["ref"] for s, c in monitor.cotizaciones_vigentes().items()
                if c.get("ref")}

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
        # Un grupo es la definicion de un par para alertar: num, den y los
        # umbrales. Nada de posicion, que es de la estrategia.
        salida = []
        for g in db.listar_grupos():
            salida.append({
                "id": g["id"], "nombre": g["nombre"], "base": g["base"],
                "tickers": g["tickers"], "mercado": g["mercado"],
                "num": g.get("num"), "den": g.get("den"),
                "plazo": g.get("plazo"), "resistencia": g.get("resistencia"),
                "soporte": g.get("soporte"), "factor": g.get("factor"),
                "alertas": bool(g.get("alertas", 1)),
                "precios": _precios_para(g),
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
        if len(tickers) != 2:
            return jsonify({"error": "Un par tiene exactamente dos tickers."}), 400
        if base not in tickers:
            return jsonify({"error": "La base tiene que ser uno de los tickers."}), 400
        if any(g["nombre"].lower() == nombre.lower() for g in db.listar_grupos()):
            return jsonify({"error": "Ya existe un par con ese nombre."}), 400
        gid = db.crear_grupo(nombre, base, tickers,
                             (d.get("mercado") or "bCBA").strip())
        db.actualizar_par(gid, _campos_par(d, tickers))
        return jsonify({"ok": True, "id": gid})

    def _campos_par(d, tickers):
        """Numerador, denominador y zonas. Por defecto el ratio va en el
        orden en que se cargaron los tickers."""
        num = (d.get("num") or tickers[0]).strip().upper()
        den = (d.get("den") or tickers[1]).strip().upper()
        def _f(k):
            try:
                v = float(d.get(k))
                return v or None
            except (TypeError, ValueError):
                return None
        res, sop = _f("resistencia"), _f("soporte")
        if res and sop and res <= sop:
            res = sop = None      # niveles invertidos: no sirven
        return {"num": num, "den": den,
                "plazo": (d.get("plazo") or "t1").strip(),
                "resistencia": res, "soporte": sop,
                "factor": _f("factor"),
                "alertas": 1 if d.get("alertas", True) else 0}

    @app.post("/api/grupos/<int:gid>")
    def editar_grupo(gid):
        d = request.get_json(silent=True) or {}
        g = db.grupo_por_id(gid)
        if not g:
            return jsonify({"error": "No existe."}), 404
        tickers = [t.strip().upper() for t in (d.get("tickers") or g["tickers"])
                   if t and t.strip()]
        if len(tickers) != 2:
            return jsonify({"error": "Un par tiene exactamente dos tickers."}), 400
        campos = _campos_par(d, tickers)
        if d.get("nombre"):
            campos["nombre"] = d["nombre"].strip()
        base = (d.get("base") or g["base"]).strip().upper()
        if base not in tickers:
            return jsonify({"error": "La base tiene que ser uno de los tickers."}), 400
        campos["base"] = base
        if d.get("mercado"):
            campos["mercado"] = d["mercado"].strip()
        db.actualizar_par(gid, campos)
        if tickers != g["tickers"]:
            db.actualizar_tickers(gid, tickers)
        return jsonify({"ok": True})

    @app.delete("/api/grupos/<int:gid>")
    def eliminar_grupo(gid):
        db.borrar_grupo(gid)
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
            tengo = monitor.tengo_actual()
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
                                CO.esquema(monitor.cfg),
                                min_monto=monitor._min_monto(),
                                mep=monitor._mep(cot))
            r["tengo"] = tengo
            r["candidatos"] = sorted(puentes)
            return jsonify(r)
        except Exception as e:
            log.exception("circuitos")
            return jsonify({"error": str(e)}), 500

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
            _, diag = OP.cadena(monitor.iol, subs)
            return jsonify(diag)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # -- alertas de precio y tenencias --------------------------------

    @app.get("/api/alertas-precio")
    def alertas_precio_listar():
        cot = monitor.cotizaciones_vigentes()
        out = []
        for a in db.alertas_precio():
            a["estado"] = monitor.evaluar_alerta(a, cot)
            out.append(a)
        return jsonify({"alertas": out, "hay_rueda": monitor._en_horario()})

    @app.post("/api/alertas-precio")
    def alertas_precio_crear():
        d = request.get_json(silent=True) or {}
        if not (d.get("condiciones") or []):
            return jsonify({"error": "hace falta al menos una condición"}), 400
        return jsonify({"id": db.guardar_alerta_precio(d, d.get("id"))})

    @app.post("/api/alertas-precio/<int:aid>/activar")
    def alertas_precio_activar(aid):
        d = request.get_json(silent=True) or {}
        db.activar_alerta_precio(aid, bool(d.get("activa", True)))
        monitor._precio_avisado.discard(aid)
        return jsonify({"id": aid, "activa": bool(d.get("activa", True))})

    @app.post("/api/alertas-precio/<int:aid>/borrar")
    def alertas_precio_borrar(aid):
        monitor._precio_avisado.discard(aid)
        return jsonify({"borradas": db.borrar_alerta_precio(aid)})

    @app.get("/api/alertas-fecha")
    def alertas_fecha_listar():
        from datetime import date as _d
        hoy = _d.today()
        out = []
        for a in db.alertas_fecha():
            try:
                f = _d.fromisoformat(str(a["fecha"])[:10])
                a["dias"] = (f - hoy).days
            except ValueError:
                a["dias"] = None
            out.append(a)
        return jsonify({"alertas": out})

    @app.post("/api/alertas-fecha")
    def alertas_fecha_crear():
        d = request.get_json(silent=True) or {}
        if not str(d.get("fecha") or "").strip():
            return jsonify({"error": "falta la fecha"}), 400
        return jsonify({"id": db.guardar_alerta_fecha(d, d.get("id"))})

    @app.post("/api/alertas-fecha/<int:aid>/activar")
    def alertas_fecha_activar(aid):
        d = request.get_json(silent=True) or {}
        db.activar_alerta_fecha(aid, bool(d.get("activa", True)))
        return jsonify({"id": aid})

    @app.post("/api/alertas-fecha/<int:aid>/borrar")
    def alertas_fecha_borrar(aid):
        return jsonify({"borradas": db.borrar_alerta_fecha(aid)})

    @app.get("/api/tenencias")
    def tenencias_listar():
        fuera = monitor.brokers_extranjeros()
        filas = db.tenencias()
        for f in filas:
            f["extranjero"] = f["broker"].upper() in fuera
        return jsonify({
            "tenencias": filas,
            "brokers_extranjeros": sorted(fuera),
            "en_rulo": monitor.tengo_actual(),
        })

    @app.post("/api/tenencias")
    def tenencias_cargar():
        d = request.get_json(silent=True) or {}
        filas = d.get("tenencias")
        if not isinstance(filas, list):
            return jsonify({"error": "falta la lista 'tenencias'"}), 400
        n = db.guardar_tenencias(filas, d.get("reemplazar") or "todo",
                                 _precios_vigentes())
        return jsonify({"cargadas": n, "en_rulo": monitor.tengo_actual()})

    @app.post("/api/tenencias/una")
    def tenencia_editar():
        d = request.get_json(silent=True) or {}
        br, sim = (d.get("broker") or "").strip(), (d.get("simbolo") or "").strip()
        if not br or not sim:
            return jsonify({"error": "faltan el broker o el símbolo"}), 400
        campos = d.get("campos") or {}
        try:
            n = db.actualizar_tenencia(br, sim, campos)
        except (TypeError, ValueError) as e:
            return jsonify({"error": str(e)}), 400
        if not n:
            return jsonify({"error": "no se encontró esa posición"}), 404

        # Alta de estrategia en el mismo paso. La fecha de alta es la de
        # la compra y no la de hoy: de ahi sale el valor del patron
        # contra el que se va a medir.
        nueva = d.get("estrategia_nueva")
        eid = None
        if nueva and (nueva.get("nombre") or "").strip():
            datos = dict(nueva)
            datos.setdefault("origen", "cargada desde %s" % sim)
            try:
                eid = db.guardar_estrategia(datos)
            except (TypeError, ValueError) as e:
                return jsonify({"error": str(e), "guardada": True}), 400
            if campos.get("fecha_alta"):
                db.fijar_alta(eid, campos["fecha_alta"])
            db.asignar(sim, eid)
        return jsonify({"actualizadas": n, "estrategia_id": eid,
                        "en_rulo": monitor.tengo_actual()})

    @app.delete("/api/tenencias/una")
    def tenencia_borrar():
        br = (request.args.get("broker") or "").strip()
        sim = (request.args.get("simbolo") or "").strip()
        if not br or not sim:
            return jsonify({"error": "faltan el broker o el símbolo"}), 400
        return jsonify({"borradas": db.borrar_tenencia(br, sim),
                        "en_rulo": monitor.tengo_actual()})

    @app.get("/api/movimientos-propuestos")
    def propuestos_listar():
        eid = request.args.get("estrategia_id")
        return jsonify({"propuestos": db.movimientos_propuestos(
            request.args.get("estado") or "pendiente",
            int(eid) if (eid or "").isdigit() else None)})

    @app.get("/api/movimientos-propuestos/<int:mid>/candidatos")
    def propuestos_candidatos(mid):
        """Con que otra propuesta se puede unir esta.

        Una rotacion hecha en dos cuentas -vende en una, compra en la
        otra- sale como un retiro y un aporte sueltos. Unirlas es lo que
        evita que la cuota se mueva por una operacion que no cambio el
        capital.
        """
        return jsonify({"candidatos": db.candidatos_a_unir(mid)})

    @app.post("/api/movimientos-propuestos/<int:mid>")
    def propuestos_resolver(mid):
        d = request.get_json(silent=True) or {}
        unir = d.get("unir_con")
        try:
            r = db.resolver_propuesto(
                mid, d.get("accion") or "confirmar",
                d.get("editado"), int(unir) if unir else None)
        except (TypeError, ValueError) as e:
            return jsonify({"error": str(e)}), 400
        if not r:
            return jsonify({"error": "no existe"}), 404
        return jsonify({"estado": r})

    @app.get("/api/estrategias")
    def estrategias_listar():
        # La posicion viaja adentro de cada estrategia y en ningun otro
        # endpoint. Los precios salen del cache: esto no pide nada.
        precios = _precios_vigentes()
        lista = db.estrategias(
            incluir_cerradas=request.args.get("cerradas") == "1",
            familia=request.args.get("familia") or None)
        for e in lista:
            try:
                e["posicion"] = P.resumen(e, precios)
            except Exception as ex:
                log.debug("posicion de %s: %s", e["id"], ex)
                e["posicion"] = None
        return jsonify({
            "estrategias": lista,
            # El patron dejo de depender de la familia, asi que la clave
            # ya no existe y esto reventaba con KeyError. En su lugar van
            # la pestaña y los tipos esperados, que es lo que el front
            # necesita para armar la tarjeta y avisar la familia cruzada.
            "familias": [{"id": k, "nombre": v["nombre"],
                          "pestana": v["pestana"],
                          "tipos": list(v["tipos"]),
                          "campos": list(v["campos"])}
                         for k, v in db.FAMILIAS.items()],
            "patrones": list(db.PATRONES),
            "grupos": [{"id": g["id"], "nombre": g["nombre"]}
                       for g in db.listar_grupos()],
        })

    @app.post("/api/estrategias")
    def estrategias_guardar():
        d = request.get_json(silent=True) or {}
        try:
            eid = db.guardar_estrategia(d, d.get("id"))
        except (TypeError, ValueError) as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"id": eid})

    @app.get("/api/estrategias/<int:eid>/evolucion")
    def estrategias_evolucion(eid):
        return jsonify({"evolucion": db.evolucion(eid)})

    # -- posicion y ledger de la estrategia ---------------------------
    # Todo esto colgaba del grupo. Un grupo es un par para alertar; la
    # posicion, el capital aportado y la cuota son de la estrategia, que
    # es la que sobrevive a la rotacion.

    def _estrategia(eid):
        for e in db.estrategias(incluir_cerradas=True):
            if e["id"] == eid:
                return e
        return None

    @app.get("/api/estrategias/<int:eid>/posicion")
    def estrategias_posicion(eid):
        e = _estrategia(eid)
        if not e:
            return jsonify({"error": "estrategia desconocida"}), 404
        return jsonify(P.resumen(e, _precios_vigentes()))

    @app.get("/api/estrategias/<int:eid>/movimientos")
    def estrategias_movimientos(eid):
        e = _estrategia(eid)
        if not e:
            return jsonify({"error": "estrategia desconocida"}), 404
        precios = _precios_vigentes()
        return jsonify({
            "movimientos": [{
                "id": m["id"], "ts": m["ts"], "tipo": m["tipo"],
                "ticker_de": m["ticker_de"], "cant_de": m["cant_de"],
                "ticker_a": m["ticker_a"], "cant_a": m["cant_a"],
                "ratio_base": m["ratio_base"],
                "equiv_antes": m["equiv_antes"],
                "propuesto_id": m["propuesto_id"], "nota": m["nota"],
            } for m in reversed(db.movimientos_estrategia(eid))],
            "curva": P.curva(e, precios),
            "resumen": P.resumen(e, precios),
        })

    @app.post("/api/estrategias/<int:eid>/movimientos")
    def estrategias_mov_nuevo(eid):
        e = _estrategia(eid)
        if not e:
            return jsonify({"error": "estrategia desconocida"}), 404
        precios = _precios_vigentes()
        limpio, error = P.validar_movimiento(e, request.get_json(silent=True)
                                             or {}, precios)
        if error:
            return jsonify({"error": error}), 400
        mid = db.registrar_mov_manual(eid, limpio)
        return jsonify({"ok": True, "id": mid,
                        "resumen": P.resumen(e, precios)})

    @app.delete("/api/estrategias/movimientos/<int:mid>")
    def estrategias_mov_borrar(mid):
        db.borrar_mov_estrategia(mid)
        return jsonify({"ok": True})

    @app.post("/api/estrategias/<int:eid>/sembrar")
    def estrategias_sembrar(eid):
        """Carga como aporte inicial lo que ya figura en la tenencia.

        La cuotaparte necesita un punto de partida. El equivalente sale
        del precio de ahora y se puede pisar por especie: la plata entro
        el dia que entro, no hoy. Con `simular` en true no escribe nada y
        devuelve lo que propondria, que es lo que la tarjeta muestra para
        que se corrija antes de confirmar.
        """
        e = _estrategia(eid)
        if not e:
            return jsonify({"error": "estrategia desconocida"}), 404
        if not e.get("ticker_base"):
            return jsonify({"error": "la estrategia no tiene ticker base: "
                                     "sin eso no hay en qué medir"}), 400
        if db.movimientos_estrategia(eid):
            return jsonify({"error": "la estrategia ya tiene movimientos"}), 400

        d = request.get_json(silent=True) or {}
        pisar = {(k or "").upper(): v
                 for k, v in (d.get("equivalentes") or {}).items()}
        precios = _precios_vigentes()
        sal = P.saldos(eid)
        if not sal:
            return jsonify({"error": "ninguna especie de la estrategia "
                                     "está en la tenencia"}), 400

        base = e["ticker_base"]
        propuesta, faltan, acum = [], [], 0.0
        for sim, v in sorted(sal.items()):
            eq = pisar.get(sim)
            try:
                eq = float(eq) if eq is not None else None
            except (TypeError, ValueError):
                eq = None
            if eq is None:
                eq = P.equiv_de(sim, v["cantidad"], base, precios, sal)
            if not eq:
                faltan.append(sim)
                continue
            propuesta.append({"simbolo": sim, "cantidad": v["cantidad"],
                              "equivalente": eq, "equiv_antes": acum})
            acum += eq
        if faltan and not propuesta:
            return jsonify({"error": "sin precio para %s: cargá el "
                                     "equivalente a mano"
                                     % ", ".join(faltan)}), 400
        if d.get("simular"):
            return jsonify({"propuesta": propuesta, "faltan_precio": faltan,
                            "ticker_base": base})

        for a in propuesta:
            db.registrar_mov_manual(eid, {
                "tipo": "aporte", "ticker_a": a["simbolo"],
                "cant_a": a["cantidad"], "ratio_base": a["equivalente"],
                "equiv_antes": a["equiv_antes"] or None,
                "nota": "tenencia inicial"})
        return jsonify({"sembrados": propuesta, "faltan_precio": faltan,
                        "resumen": P.resumen(e, precios)})

    @app.get("/api/estrategias/revisar")
    def estrategias_revisar():
        """Lo que la app sospecha y no aplica sola.

        Estaba escrito en db y no lo leia nadie: media funcionalidad.
        """
        return jsonify({"cruzadas": db.especies_cruzadas(),
                        "cierres": db.cierres_sugeridos()})

    @app.delete("/api/estrategias/<int:eid>")
    def estrategias_borrar(eid):
        return jsonify({"borradas": db.borrar_estrategia(eid)})

    @app.post("/api/estrategias/<int:eid>/cerrar")
    def estrategias_cerrar(eid):
        d = request.get_json(silent=True) or {}
        if d.get("reabrir"):
            db.reabrir_estrategia(eid)
        else:
            db.cerrar_estrategia(eid, (d.get("motivo") or "manual"))
        return jsonify({"ok": True})

    @app.post("/api/estrategias/asignar")
    def estrategias_asignar():
        # La asignacion es por simbolo y no por broker: la misma especie
        # en dos cuentas es una sola posicion de una sola estrategia. El
        # broker se sigue aceptando y se ignora, para no romper la
        # pantalla vieja mientras se saca.
        d = request.get_json(silent=True) or {}
        sim = (d.get("simbolo") or "").strip()
        if not sim:
            return jsonify({"error": "falta el símbolo"}), 400
        db.asignar(sim, d.get("estrategia_id") or None)
        return jsonify({"ok": True})

    @app.post("/api/estrategias/limpiar")
    def estrategias_limpiar():
        return jsonify({"borradas": db.borrar_vacias()})

    @app.post("/api/estrategias/auto")
    def estrategias_auto():
        """Crea una estrategia por grupo de rotacion y le asigna sus
        especies. Nunca pisa una asignacion hecha a mano."""
        return jsonify({"asignadas": db.asignar_por_grupos()})

    @app.get("/api/tenencias/historial")
    def tenencias_historial():
        return jsonify({
            "historial": db.historial_tenencia(
                request.args.get("broker"), request.args.get("simbolo"),
                request.args.get("desde")),
            "fechas": db.fechas_snapshot(request.args.get("broker")),
        })

    @app.get("/api/eventos")
    def eventos_listar():
        return jsonify({"eventos": db.eventos(request.args.get("simbolo"))})

    @app.post("/api/eventos")
    def eventos_crear():
        d = request.get_json(silent=True) or {}
        try:
            eid = db.guardar_evento(d.get("simbolo"), d.get("fecha"),
                                    d.get("factor"), d.get("nota"))
        except (TypeError, ValueError) as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"id": eid})

    @app.delete("/api/eventos/<int:eid>")
    def eventos_borrar(eid):
        return jsonify({"borrados": db.borrar_evento(eid)})

    # IOL agrupa por tipo de instrumento y no lo escribe siempre igual:
    # "TIT. PUBLICOS", "TitulosPublicos" y "titulos publicos" son el
    # mismo tipo. Se compara sin puntos, espacios ni acentos, buscando la
    # raiz adentro del texto.
    TIPO_IOL = (
        ("cedear", "cedears"),
        ("obligacion", "on"),
        ("negociable", "on"),
        ("letra", "letras"),
        ("titulopublico", "bonos"),
        ("titulospublicos", "bonos"),
        ("titpublico", "bonos"),
        ("publico", "bonos"),
        ("bono", "bonos"),
        ("accion", "acciones"),
        ("fondo", "fci"),
        ("fci", "fci"),
    )

    def _tipo_iol(txt):
        import unicodedata
        t = unicodedata.normalize("NFKD", str(txt or ""))
        t = "".join(ch for ch in t if not unicodedata.combining(ch))
        t = "".join(ch for ch in t.lower() if ch.isalnum())
        for clave, valor in TIPO_IOL:
            if clave in t:
                return valor
        return "otros"

    def _bajar_cuenta(cli, nombre):
        """Baja titulos y efectivo de una cuenta de IOL.

        Devuelve las filas listas para guardar. No escribe: el que llama
        decide, porque cada cuenta se reemplaza por separado y una que
        falla no tiene que impedir que la otra se cargue.
        """
        filas, vacios, deudas = [], [], []
        with cli.como("boton"):
            for pais in ("argentina", "estados_Unidos"):
                d = cli.portafolio(pais)
                # la respuesta trae los titulos bajo "activos" o bajo
                # "positions" segun la version; se aceptan las dos
                activos = ((d or {}).get("activos")
                           or (d or {}).get("positions") or [])
                if not activos:
                    vacios.append(pais)
                for a in activos:
                    t = (a or {}).get("titulo") or (a or {}).get("asset") or {}
                    sim = (t.get("simbolo") or t.get("symbol")
                           or "").strip().upper()
                    try:
                        cant = float(a.get("cantidad")
                                     or a.get("quantity") or 0)
                    except (TypeError, ValueError):
                        cant = 0
                    if not sim or not cant:
                        continue
                    tipo = _tipo_iol(t.get("tipo") or t.get("type")
                                     or a.get("tipo"))
                    filas.append({"broker": nombre, "simbolo": sim,
                                  "cantidad": cant, "tipo": tipo})

        # El portafolio trae solo titulos; el efectivo sale de otro
        # endpoint. Sin el disponible por moneda, el Rulo no sabe con que
        # se cuenta para partir desde una moneda.
        monedas = []
        try:
            with cli.como("boton"):
                ec = cli.estado_cuenta()
            for cu in (ec or {}).get("cuentas") or []:
                tipo_cta = (cu.get("tipo") or "").lower()
                if "estados_unidos" in tipo_cta:
                    sim = "CABLE"          # dolar que liquida afuera
                elif "dolares" in tipo_cta:
                    sim = "MEP"            # dolar que liquida local
                elif "pesos" in tipo_cta:
                    sim = "ARS"
                else:
                    continue
                # La suma de los disponibles por plazo, no el campo
                # "disponible" de la cuenta: ese ultimo netea lo
                # comprometido de una compra contra el saldo inmediato y
                # llega a dar negativo con dinero en la cuenta. Lo que
                # liquida en 24 o 48 horas igual sirve para operar, solo
                # que con esa fecha.
                monto, por_plazo = 0.0, []
                for sa in cu.get("saldos") or []:
                    try:
                        v = float(sa.get("disponible") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not v:
                        continue
                    monto += v
                    por_plazo.append("%s %s" % (
                        sa.get("liquidacion") or "?", round(v, 2)))
                if not por_plazo:
                    # Sin desglose por plazo se cae al campo de la
                    # cuenta, que es mejor que no informar nada.
                    try:
                        monto = float(cu.get("disponible")
                                      or cu.get("saldo") or 0)
                    except (TypeError, ValueError):
                        monto = 0
                if not monto:
                    continue
                filas.append({"broker": nombre, "simbolo": sim,
                              "cantidad": monto, "tipo": "moneda"})
                monedas.append("%s %s%s" % (
                    sim, round(monto, 2),
                    " (" + " · ".join(por_plazo) + ")" if len(por_plazo) > 1
                    else ""))
                if monto < 0:
                    # No se descarta: si el saldo da negativo con el
                    # campo correcto, es un dato que hay que ver y no
                    # algo para tragarse en silencio.
                    deudas.append("%s %s" % (sim, round(monto, 2)))
        except IOLError as e:
            log.warning("estado de cuenta de %s: %s", nombre, e)
        return filas, vacios, monedas, deudas

    def _cuentas_iol():
        """Las cuentas configuradas, en orden. La segunda es opcional."""
        cta = [((monitor.cfg.get("broker_propio") or "IOL").strip(),
                monitor.iol)]
        cli2 = getattr(monitor, "iol2", None)
        if cli2:
            cta.append(((monitor.cfg.get("broker2_nombre")
                         or "IOL-2").strip(), cli2))
        return cta

    @app.post("/api/iol/estadocuenta")
    def iol_estado_cuenta():
        """La respuesta cruda, sin interpretar.

        El registro de llamadas guarda ruta, estado y demora, pero no el
        cuerpo. Sin esto, cuando un saldo no cierra no hay donde mirar.
        """
        salida = []
        for nombre, cli in _cuentas_iol():
            try:
                with cli.como("boton"):
                    salida.append({"broker": nombre, "respuesta":
                                   cli.estado_cuenta()})
            except IOLError as e:
                salida.append({"broker": nombre, "error": str(e)})
        return jsonify({"cuentas": salida})

    @app.post("/api/tenencias/traer")
    def tenencias_traer():
        """Baja la tenencia de las cuentas de IOL y las carga.

        Cada cuenta reemplaza solo su propio broker: las cargadas a mano
        y la del exterior quedan intactas. Si una cuenta falla, la otra
        se carga igual y el error se informa aparte.
        """
        pedido = (request.args.get("broker") or "").strip()
        cuentas = _cuentas_iol()
        if pedido:
            cuentas = [c for c in cuentas if c[0] == pedido] or \
                      [(pedido, monitor.iol)]
        resultados, errores = [], []
        for nombre, cli in cuentas:
            try:
                filas, vacios, monedas, deudas = _bajar_cuenta(cli, nombre)
            except IOLError as e:
                errores.append("%s: %s" % (nombre, e))
                continue
            if not filas:
                errores.append("%s: no devolvió posiciones" % nombre)
                continue
            n = db.guardar_tenencias(filas, nombre, _precios_vigentes())
            resultados.append({
                "broker": nombre, "cargadas": n,
                "sin_posiciones": vacios, "monedas": monedas,
                "deudas": deudas,
                "sin_clasificar": sorted({f["simbolo"] for f in filas
                                          if f["tipo"] == "otros"}),
            })
        if not resultados:
            return jsonify({"error": " · ".join(errores)
                            or "IOL no devolvió posiciones"}), 502
        primero = resultados[0]
        # Los campos sueltos quedan por compatibilidad: son los de la
        # primera cuenta, que es la principal.
        return jsonify({"cuentas": resultados, "errores": errores,
                        "cargadas": sum(r["cargadas"] for r in resultados),
                        "broker": primero["broker"],
                        "sin_posiciones": primero["sin_posiciones"],
                        "sin_clasificar": primero["sin_clasificar"],
                        "monedas": primero["monedas"],
                        "deudas": primero["deudas"],
                        "en_rulo": monitor.tengo_actual()})

    @app.get("/api/canjes")
    def canjes_listar():
        """Contra que conviene rotar cada bono que se tiene.

        Por defecto devuelve lo que dejo el ultimo ciclo, que es lo mismo
        que ya se aviso por notificacion. Recalcular la curva entera en
        cada visita seria repetir un trabajo hecho.
        """
        if request.args.get("recalcular") == "1":
            try:
                filas = monitor.canjes_curva()
            except Exception as e:
                log.warning("canjes: %s", e)
                return jsonify({"error": str(e)}), 500
        else:
            filas = getattr(monitor, "canjes", [])
        return jsonify({"canjes": filas,
                        "calculado": monitor.ultimo_ciclo.isoformat(
                            timespec="seconds") if monitor.ultimo_ciclo else None,
                        "minimo": float(monitor.cfg.get("canje_min_pct") or 1)})

    @app.post("/api/precios/por-especie")
    def precios_por_especie():
        """Pide las cotizaciones de a una, hasta que la API frena.

        No corre solo: consume el cupo de la cuenta que hace el ciclo, y
        para valuar alcanza con BYMA. Es para cuando hay que operar y los
        veinte minutos de retraso no sirven.
        """
        try:
            n = monitor.repuesto_por_especie()
        except Exception as e:
            log.warning("por especie: %s", e)
            return jsonify({"error": str(e)}), 502
        return jsonify({"precios": n, "fuente": getattr(monitor, "fuente", "")})

    @app.post("/api/fuente")
    def fijar_fuente():
        """Cambia la fuente de precios sin reiniciar el add-on."""
        d = request.get_json(silent=True) or {}
        v = (d.get("fuente") or "").strip().lower()
        if v not in ("auto", "iol", "byma"):
            return jsonify({"error": "auto, iol o byma"}), 400
        monitor._fuente_forzada = None if v == "auto" else v
        return jsonify({"elegida": monitor.fuente_elegida(),
                        "usando": getattr(monitor, "fuente", "iol")})

    @app.post("/api/byma/panel")
    def byma_panel():
        """Respuesta cruda de un panel, sin interpretar.

        Mismo criterio que el estado de cuenta de IOL: cuando un numero
        no cierra hace falta ver de que campo salio, y el registro de
        llamadas guarda ruta y estado pero nunca el cuerpo.
        """
        import byma as BY
        d = request.get_json(silent=True) or {}
        inst = (d.get("panel") or "titulosPublicos").strip()
        if inst not in BY.PANELES:
            return jsonify({"error": "panel desconocido",
                            "paneles": sorted(BY.PANELES)}), 400
        cli = BY.Byma(verificar_ssl=bool(monitor.cfg.get("byma_verificar_ssl")))
        try:
            filas = cli.panel(inst, d.get("plazo") or None)
        except BY.BymaError as e:
            return jsonify({"error": str(e), "url": BY.BASE + BY.PANELES[inst],
                            "metodo": "POST"}), 502
        n = int(d.get("filas") or 3)
        simbolo = (d.get("simbolo") or "").strip().upper()
        if simbolo:
            filas = [f for f in filas
                     if (f.get("symbol") or "").upper() == simbolo]
        return jsonify({
            "panel": inst, "total": len(filas),
            "url": BY.BASE + BY.PANELES[inst],
            "plazos": sorted({str(f.get("settlementType") or "")
                              for f in filas}),
            "campos": sorted(filas[0].keys()) if filas else [],
            "filas": filas[:max(1, min(n, 25))],
        })

    @app.get("/api/cartera")
    def cartera_valuada():
        import cartera as CA
        import bonos as BO
        filas = db.tenencias()
        fuera = monitor.brokers_extranjeros()
        for f in filas:
            f["extranjero"] = f["broker"].upper() in fuera
        # Solo lo que ya esta en cache: valuar no justifica una rueda de
        # requests por cada visita a la pestania.
        cache = monitor.cotizaciones_vigentes()
        precios = _precios_vigentes()
        try:
            bonos_cfg, _ = BO.cargar()
        except Exception as e:
            log.warning("bonos.yaml para la cartera: %s", e)
            bonos_cfg = {}
        mep = None
        try:
            mep = (BO.calcular_mep(
                cache, monitor.cfg.get("mep_par_pesos") or "AL30",
                monitor.cfg.get("mep_par_usd") or "AL30D"
            ).get("medio") or 0) or None
        except Exception as e:
            log.debug("mep para la cartera: %s", e)

        # La medicion de estrategias va siempre sobre la cartera entera:
        # filtrada por broker daria el rendimiento de media estrategia,
        # que no significa nada.
        completa = CA.valuar(filas, precios, mep, bonos_cfg)

        # Los mismos filtros que la lista: al mirar un solo broker o un
        # solo tipo, el total y los pesos tienen que ser de eso.
        br = (request.args.get("broker") or "").strip()
        tp = (request.args.get("tipo") or "").strip().lower()
        fa = (request.args.get("familia") or "").strip().lower()
        ex = (request.args.get("exposicion") or "").strip()
        if br:
            filas = [f for f in filas if f["broker"] == br]
        if tp:
            filas = [f for f in filas if (f.get("tipo") or "otros") == tp]
        if ex:
            # La exposición no está en la tenencia: sale de bonos.yaml,
            # así que hay que calcularla para poder filtrar por ella.
            filas = [f for f in filas
                     if CA.exposicion(f, bonos_cfg) == ex]
        if fa == "_sin":
            filas = [f for f in filas if not f.get("estrategia_id")]
        elif fa:
            filas = [f for f in filas if f.get("familia") == fa]
        r = (completa if not (br or tp or fa or ex)
             else CA.valuar(filas, precios, mep, bonos_cfg))
        try:
            r["estrategias"] = CA.medir(db.estrategias(),
                                        completa["posiciones"])
            # Se guarda antes de que la estrategia pueda cerrarse: es el
            # unico momento en que todavia hay tenencia con que medir.
            db.guardar_medicion(r["estrategias"])
        except Exception as e:
            log.warning("medición de estrategias: %s", e)
            r["estrategias"] = []
        # Las exposiciones de la cartera entera: los chips no se pueden
        # armar con las del subconjunto o al filtrar quedaria una sola y
        # no habria como volver.
        r["exposiciones"] = [e["nombre"] for e in completa["por_exposicion"]]
        # Sin precios, decir por que: si los paneles estan caidos no es
        # que falte esperar el proximo ciclo.
        r["fallas"] = list(getattr(monitor, "orleans_fallas", []) or [])
        return jsonify(r)

    @app.get("/api/cobros")
    def cobros_listar():
        import cobros as CO
        try:
            dias = int(request.args.get("dias", 365))
        except ValueError:
            dias = 365
        try:
            filas = CO.proximos(
                dias=dias,
                cer_actual=float(monitor.cfg.get("cer_actual") or 0),
                incluir_extranjeros=request.args.get("todos") == "1",
                brokers_fuera=monitor.brokers_extranjeros())
        except Exception as e:
            log.exception("cobros")
            return jsonify({"error": str(e)}), 500
        # No tener pagos en la ventana no es no tener cronograma: un bono
        # que vence en 2029 no paga nada en 90 dias y esta perfectamente
        # cargado. Se mira contra el universo de especies.
        esps = set(BO.especies())
        sin_cronograma = sorted(
            {t["simbolo"] for t in db.tenencias()
             if t["cantidad"] and t["simbolo"] not in esps
             and (t.get("tipo") or "") in ("bonos", "letras", "on", "bcra")})
        return jsonify({
            "cobros": filas,
            "sin_cronograma": sin_cronograma,
            "dias_aviso": int(monitor.cfg.get("dias_aviso_cobro") or 2),
        })

    @app.get("/api/a3500")
    def a3500_estado():
        """Estado del tipo de cambio oficial, y prueba de la serie.

        El numero de serie del BCRA no esta confirmado contra la
        documentacion: con ?serie=N se puede probar otro sin tocar el
        codigo.
        """
        import dolar as DL
        serie = request.args.get("serie")
        if request.args.get("listar") == "1":
            # el catalogo completo: asi se ve cual es la A3500 sin adivinar
            filas = DL.catalogo()
            cambio = [f for f in filas
                      if "cambio" in f["descripcion"].lower()
                      or "3500" in f["descripcion"]]
            return jsonify({"series": cambio or filas[:40],
                            "total": len(filas),
                            "detectada": DL.buscar_a3500(),
                            "error": DL.ultimo_error})
        if serie and request.args.get("fijar") == "1":
            DL.fijar_serie(int(serie))
        if request.args.get("probar") == "1":
            DL.reintentar_ya()
            from datetime import date as _d, timedelta as _td
            hasta = _d.today()
            n = DL.descargar((hasta - _td(days=30)).isoformat(),
                             hasta.isoformat(),
                             serie=int(serie) if serie else None)
            return jsonify({"bajados": n, "estado": DL.estado(),
                            "serie_probada": int(serie) if serie else DL.SERIE,
                            "muestra": DL.ultima_respuesta,
                            "error": DL.ultimo_error})
        return jsonify(DL.estado())

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

    @app.post("/api/badlar/probar")
    def badlar_probar():
        """Fuerza una consulta al BCRA y devuelve el error si falla."""
        from datetime import date as _d, timedelta as _t
        import badlar as BA
        BA.reintentar_ya()
        hoy = _d.today()
        n = BA.descargar((hoy - _t(days=30)).isoformat(), hoy.isoformat())
        est = BA.resumen()
        bonos_cfg, _ = BO.cargar()
        det = []
        for tk, cfg in bonos_cfg.items():
            var = (cfg.get("interes") or {}).get("variable")
            if not var:
                continue
            v = BA.vigente()
            det.append("%s %s spread %s -> %s" % (
                tk, var.get("fuente"), var.get("spread") or 0,
                round(v + float(var.get("spread") or 0), 4) if v is not None else "sin dato"))
        return jsonify({"dias_traidos": n, "vigente": BA.vigente(),
                        "serie": 7,
                        "error": BA.ultimo_error,
                        "respuesta": BA.ultima_respuesta,
                        "rango": "%s a %s (%s días)" % (
                            est["desde"], est["hasta"], est["dias"])
                        if est["dias"] else None,
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

    # Los que acepta orleans. No coinciden con los nombres de los
    # instrumentos del endpoint viejo.
    INSTRUMENTOS_ORLEANS = ["titulosPublicos", "letras", "acciones",
                            "cedears", "opciones", "obligacionesNegociables",
                            "cauciones", "aDRs", "cHPD", "futuros"]

    @app.get("/api/explorar/instrumentos")
    def ex_instrumentos():
        """Los de orleans, que es la fuente que usa el ciclo.

        La lista es fija: no hay endpoint que la devuelva, sale del
        contrato de la API.
        """
        return jsonify(list(INSTRUMENTOS_ORLEANS))

    @app.get("/api/explorar/paneles")
    def ex_paneles():
        """Orleans no tiene paneles: tiene un filtro."""
        return jsonify(["Operables", "Todos"])

    @app.post("/api/explorar/recargar-catalogo")
    def ex_recargar():
        return jsonify({"borradas": db.cache_borrar("")})

    @app.get("/api/explorar/panel")
    def ex_panel():
        pais = request.args.get("pais", "argentina")
        instrumento = request.args.get("instrumento", "Bonos")
        panel = request.args.get("panel", "")
        # "panel" ahora es el filtro de orleans: Operables o Todos. Los
        # paneles viejos quedaron sin uso, asi que el explorador mira la
        # misma fuente que el ciclo.
        filtro = panel or "Operables"
        try:
            with monitor.iol.como("pestania"):
                d = monitor.iol.panel_orleans(instrumento, pais, filtro)
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
                "fecha": t.get("fecha") or "",
                "lote": t.get("lote"),
                "descripcion": t.get("descripcion") or "",
            })
        filas.sort(key=lambda f: f["simbolo"] or "")
        simbolos = [f["simbolo"] or "" for f in filas]
        return jsonify({
            "panel": filtro, "instrumento": instrumento,
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
           ("id", "alias", "num", "den", "ratio", "zona", "resistencia", "soporte",
            "z", "ts", "alertas", "error", "alerta_id", "origen", "cerca")}
    est = f.get("est") or {}
    out["est"] = {k: est.get(k) for k in
                  ("n", "media", "desvio", "min", "max", "fuente", "aviso")}
    for lado in ("p_num", "p_den"):
        if f.get(lado):
            out[lado] = _p(f[lado])
    return out
