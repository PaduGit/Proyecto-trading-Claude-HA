"""Motor de monitoreo: paneles, ratios, niveles y alertas."""

import logging
import statistics
import threading
import time
from datetime import datetime, timedelta

import db
from iol import IOLError

log = logging.getLogger("monitor")

VENTANA_DIAS = 90
MIN_MUESTRA_Z = 20
MIN_MUESTRA_PROPIA = 15
BACKFILL_DIAS = 400


class Monitor:
    def __init__(self, cfg, iol, notif):
        self.cfg = cfg
        self.iol = iol
        self.notif = notif
        self.pares = cfg["pares"]

        self.snapshot = {}
        self.plazos = {}
        self.lock = threading.Lock()
        self.ultimo_ciclo = None
        self.ultimo_error = None
        self.hay_rueda = None
        self.cotizaciones = {}      # simbolo -> dict, del ultimo ciclo
        self.origen = {}            # simbolo -> "panel" | "individual"

        self._zona_actual = self._cargar_zonas()
        self._pidiendo = threading.Lock()
        self._ultimo_manual = datetime.min

    # -- estado persistente -------------------------------------------

    def _cargar_zonas(self):
        """La zona vive en la base: si no, cada reinicio repite las alertas."""
        import json
        try:
            return json.loads(db.get_estado("zonas") or "{}")
        except (ValueError, TypeError):
            return {}

    def _guardar_zonas(self):
        import json
        try:
            db.set_estado("zonas", json.dumps(self._zona_actual))
        except Exception as e:
            log.debug("no se pudo guardar el estado de zonas: %s", e)

    # -- helpers ------------------------------------------------------

    def par_por_alias(self, alias):
        for p in self.pares:
            if p["alias"] == alias:
                return p
        return None

    def _en_horario(self):
        try:
            ini = datetime.strptime(self.cfg["market_open"], "%H:%M").time()
            fin = datetime.strptime(self.cfg["market_close"], "%H:%M").time()
        except ValueError:
            return True
        ahora = datetime.now()
        if ahora.weekday() >= 5:
            return False
        return ini <= ahora.time() <= fin

    def segundos_desde_ciclo(self):
        if not self.ultimo_ciclo:
            return None
        return int((datetime.now() - self.ultimo_ciclo).total_seconds())

    # -- obtencion de precios ----------------------------------------

    def simbolos_necesarios(self):
        s = set()
        for p in self.pares:
            s.add(p["num"])
            s.add(p["den"])
        for t in self.cfg.get("arbitraje_tickers") or []:
            s.add((t.get("ticker") or "").upper())
        s.discard("")
        return s

    def bajar_paneles(self):
        """Un request por panel. Devuelve simbolo -> cotizacion."""
        from iol import normalizar
        mapa = {}
        planos = 0
        total = 0

        for pan in self.cfg.get("paneles") or []:
            inst = pan.get("instrumento") or "Bonos"
            nombre = pan.get("panel") or ""
            pais = pan.get("pais") or "argentina"
            if not nombre:
                continue
            try:
                d = self.iol.cotizacion_panel(inst, nombre, pais)
            except IOLError as e:
                log.warning("panel %s/%s: %s", inst, nombre, e)
                continue

            for t in (d or {}).get("titulos") or []:
                sim = (t.get("simbolo") or "").upper()
                if not sim:
                    continue
                c = normalizar(t, sim)
                if not c["ref"]:
                    continue
                mapa[sim] = c
                self.origen[sim] = "panel"
                total += 1
                if not c["variacion"] and not c.get("volumen"):
                    planos += 1

        # deteccion de dia sin rueda: nada se movio en todo el panel
        if total >= 10:
            self.hay_rueda = planos < total
        return mapa

    def cotizaciones_del_ciclo(self):
        mapa = self.bajar_paneles()
        faltan = self.simbolos_necesarios() - set(mapa)

        # lo que no vino en ningun panel, se pide suelto
        for p in self.pares:
            for lado in ("num", "den"):
                sim = p[lado]
                if sim in faltan:
                    try:
                        mapa[sim] = self.iol.cotizacion(
                            p["mercado"], sim, p.get("plazo", "t1"))
                        self.origen[sim] = "individual"
                        faltan.discard(sim)
                    except IOLError as e:
                        log.warning("%s: %s", sim, e)
        if faltan:
            log.debug("sin cotizacion: %s", ", ".join(sorted(faltan)))
        return mapa

    # -- estadistica --------------------------------------------------

    def estadistica(self, par):
        """Prefiere nuestras propias lecturas; el historico de IOL es respaldo."""
        desde = (datetime.now().date() - timedelta(days=VENTANA_DIAS)).isoformat()
        propia = db.serie_propia_diaria(par["alias"], desde)
        if len(propia) >= MIN_MUESTRA_PROPIA:
            return _stats([v for _, v in propia], "propia")

        serie = db.serie_ratio_diaria(par["num"], par["den"], desde)
        st = _stats([v for _, v in serie], "iol")
        st["aviso"] = ("El histórico viene de IOL y puede mezclar plazos. "
                       "Se reemplaza solo cuando junte %d días propios."
                       % MIN_MUESTRA_PROPIA)
        return st

    # -- zonas y alertas ---------------------------------------------

    def _zona(self, par, ratio, est):
        """Zona con histeresis: salir cuesta mas que entrar."""
        res = par.get("resistencia") or 0
        sop = par.get("soporte") or 0
        margen = float(self.cfg.get("histeresis_pct", 0.5)) / 100.0
        actual = self._zona_actual.get(par["alias"], "normal")

        if res > 0 or sop > 0:
            if actual == "alta":
                # sigue en alta hasta que baje del nivel menos el margen
                if res and ratio >= res * (1 - margen):
                    return "alta", res
            elif actual == "baja":
                if sop and ratio <= sop * (1 + margen):
                    return "baja", sop
            if res > 0 and ratio >= res:
                return "alta", res
            if sop > 0 and ratio <= sop:
                return "baja", sop
            return "normal", None

        # sin niveles: z-score
        if est.get("n", 0) >= MIN_MUESTRA_Z and est.get("desvio"):
            z = (ratio - est["media"]) / est["desvio"]
            umbral = 2.0 if actual == "normal" else 1.6
            if z >= umbral:
                return "alta", est["media"] + 2 * est["desvio"]
            if z <= -umbral:
                return "baja", est["media"] - 2 * est["desvio"]
        return "normal", None

    def _mensaje(self, par, ratio, zona, nivel, est, num, den):
        icono = "🔴" if zona == "alta" else "🟢"
        que = "tocó resistencia" if zona == "alta" else "tocó soporte"
        L = [
            "%s <b>%s</b> %s" % (icono, par["alias"], que),
            "Ratio <b>%.4f</b>  (nivel %.4f)" % (ratio, nivel or 0),
            "",
        ]
        for etq, sim, c in (("", par["num"], num), ("", par["den"], den)):
            linea = "%s: %s" % (sim, _n(c["ref"]))
            if c["compra"] or c["venta"]:
                linea += "   %s / %s" % (_n(c["compra"]), _n(c["venta"]))
            if c.get("vol_compra") or c.get("vol_venta"):
                linea += "   [%s / %s]" % (
                    _e(c.get("vol_compra")), _e(c.get("vol_venta")))
            L.append(linea)

        if est.get("n", 0) >= MIN_MUESTRA_Z and est.get("desvio"):
            z = (ratio - est["media"]) / est["desvio"]
            L += ["",
                  "Media: %.4f   z: %+.2f" % (est["media"], z),
                  "Rango: %.4f – %.4f  (n=%d, %s)" % (
                      est["min"], est["max"], est["n"], est.get("fuente", ""))]
        ten = self._tenencia_del_par(par, ratio)
        if ten:
            L += [""] + ten
        L += ["", "<i>%s</i>" % datetime.now().strftime("%H:%M:%S")]
        return "\n".join(L)

    def _tenencia_del_par(self, par, ratio):
        """Si el par pertenece a un grupo, cuanto tenes y cuanto obtendrias."""
        try:
            import posicion as P
            for g in db.listar_grupos():
                tks = set(g["tickers"])
                if par["num"] not in tks or par["den"] not in tks:
                    continue
                saldos = P.tenencia(g["id"])
                lineas = []
                cn = saldos.get(par["num"], 0)
                cd = saldos.get(par["den"], 0)
                if cn > 0:
                    lineas.append("Tenés %s %s → %s %s si rotás"
                                  % (_e(cn), par["num"],
                                     _e(cn * ratio), par["den"]))
                if cd > 0:
                    lineas.append("Tenés %s %s → %s %s si rotás"
                                  % (_e(cd), par["den"],
                                     _e(cd / ratio if ratio else 0), par["num"]))
                return lineas
        except Exception as e:
            log.debug("tenencia en alerta: %s", e)
        return []

    # -- evaluacion ---------------------------------------------------

    def evaluar_par(self, par, mapa):
        num = mapa.get(par["num"])
        den = mapa.get(par["den"])
        if not num or not den or not num["ref"] or not den["ref"]:
            raise IOLError("sin precio para %s o %s" % (par["num"], par["den"]))

        ratio = num["ref"] / den["ref"]
        est = self.estadistica(par)
        previa = self._zona_actual.get(par["alias"], "normal")
        zona, nivel = self._zona(par, ratio, est)
        if zona != previa:
            self._zona_actual[par["alias"]] = zona
            self._guardar_zonas()

        db.guardar_lectura(par["alias"], ratio, num, den)

        z = None
        if est.get("n", 0) >= MIN_MUESTRA_Z and est.get("desvio"):
            z = (ratio - est["media"]) / est["desvio"]

        alerta_id = None
        # avisa solo al ENTRAR en zona, no mientras se queda
        if par.get("alertas") and zona != "normal" and previa != zona:
            msg = self._mensaje(par, ratio, zona, nivel, est, num, den)
            alerta_id = db.registrar_alerta(
                par["alias"], zona, ratio, nivel, msg, num, den)
            self.notif.enviar(
                "%s %s" % (par["alias"], "▲" if zona == "alta" else "▼"),
                msg, urgente=True)
            log.info("alerta %s %s @ %.4f", par["alias"], zona, ratio)

        estado = {
            "alias": par["alias"], "num": par["num"], "den": par["den"],
            "cerca": _cerca_del_borde(par, ratio, est),
            "ratio": ratio, "zona": zona, "zona_previa": previa,
            "resistencia": par.get("resistencia") or 0,
            "soporte": par.get("soporte") or 0,
            "z": z, "est": est, "p_num": num, "p_den": den,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "alertas": bool(par.get("alertas")),
            "alerta_id": alerta_id,
            "origen": self.origen.get(par["num"], "?"),
            "error": None,
        }

        if self.cfg.get("publicar_sensores"):
            self.notif.publicar_sensor(par["alias"], ratio, {
                "friendly_name": "Ratio " + par["alias"],
                "zona": zona,
                "resistencia": par.get("resistencia") or 0,
                "soporte": par.get("soporte") or 0,
                "z_score": round(z, 3) if z is not None else None,
                "numerador": par["num"], "denominador": par["den"],
                "precio_numerador": num["ref"], "precio_denominador": den["ref"],
                "unit_of_measurement": "ratio",
                "icon": "mdi:swap-horizontal",
            })
        return estado

    # -- arbitraje de plazos t0 / t1 ---------------------------------

    def comision(self, tipo):
        tabla = self.cfg.get("comisiones") or {}
        try:
            return float(tabla.get(tipo, tabla.get("acciones", 0.15))) / 100.0
        except (TypeError, ValueError):
            return 0.0015

    def evaluar_arbitraje(self):
        """Vender en t0 y recomprar en t1 conviene si la punta compradora
        de t0 supera a la vendedora de t1, neto de costos y por encima
        de lo que rendiria la caucion a un dia."""
        filas = []
        tasa_anual = float(self.cfg.get("tasa_caucion_anual") or 0)
        tasa_dia = tasa_anual / 365.0 / 100.0
        com_caucion = self.comision("cauciones")

        for t in self.cfg.get("arbitraje_tickers") or []:
            sim = (t.get("ticker") or "").upper()
            if not sim:
                continue
            mercado = t.get("mercado") or "bCBA"
            tipo = t.get("tipo") or "bonos"
            fila = {"ticker": sim, "tipo": tipo}
            try:
                c0 = self.iol.cotizacion(mercado, sim, "t0")
                c1 = self.iol.cotizacion(mercado, sim, "t1")
            except IOLError as e:
                fila["error"] = str(e)
                filas.append(fila)
                continue

            fila.update({
                "compra_t0": c0["compra"], "venta_t0": c0["venta"],
                "q_compra_t0": c0.get("vol_compra"),
                "compra_t1": c1["compra"], "venta_t1": c1["venta"],
                "q_venta_t1": c1.get("vol_venta"),
            })

            if not c0["compra"] or not c1["venta"]:
                fila["error"] = "faltan puntas"
                filas.append(fila)
                continue

            bruto = (c0["compra"] - c1["venta"]) / c1["venta"]
            costo = self.comision(tipo) * 2
            neto = bruto - costo
            referencia = tasa_dia - com_caucion / 365.0

            fila.update({
                "bruto_pct": bruto * 100,
                "costo_pct": costo * 100,
                "neto_pct": neto * 100,
                "caucion_dia_pct": referencia * 100,
                "conviene": bool(c0["compra"] > c1["venta"] and neto > referencia),
                "ejecutable": min(c0.get("vol_compra") or 0,
                                  c1.get("vol_venta") or 0),
            })
            filas.append(fila)

        filas.sort(key=lambda f: f.get("neto_pct") or -999, reverse=True)
        return filas

    # -- ciclo --------------------------------------------------------

    def ciclo(self, manual=False):
        if not self._pidiendo.acquire(blocking=False):
            return False
        try:
            mapa = self.cotizaciones_del_ciclo()
            with self.lock:
                self.cotizaciones = mapa
            for par in self.pares:
                try:
                    estado = self.evaluar_par(par, mapa)
                    with self.lock:
                        self.snapshot[par["alias"]] = estado
                except Exception as e:
                    log.warning("%s: %s", par["alias"], e)
                    with self.lock:
                        prev = self.snapshot.get(par["alias"]) or {
                            "alias": par["alias"], "num": par["num"],
                            "den": par["den"]}
                        prev["error"] = str(e)
                        self.snapshot[par["alias"]] = prev
            self.ultimo_ciclo = datetime.now()
            if manual:
                self._ultimo_manual = datetime.now()
            return True
        finally:
            self._pidiendo.release()

    def ciclo_manual(self):
        """Refresco a pedido, con un minimo entre disparos."""
        minimo = int(self.cfg.get("min_segundos_manual", 20))
        falta = minimo - (datetime.now() - self._ultimo_manual).total_seconds()
        if falta > 0:
            return False, int(falta) + 1
        ok = self.ciclo(manual=True)
        return ok, 0

    # -- relleno de huecos --------------------------------------------

    def rellenar_huecos(self):
        """Días laborables sin lecturas propias se completan con cierres de IOL.

        Pasa cuando se cae internet o la máquina queda apagada. Corre una vez
        por semana: los cierres de la semana ya están consolidados.
        """
        from datetime import date as _date
        desde = (datetime.now().date() - timedelta(days=180)).isoformat()
        rellenados = 0

        for par in self.pares:
            propios = {f for f, _ in db.serie_propia_diaria(par["alias"], desde)}
            serie = db.serie_ratio_diaria(par["num"], par["den"], desde)
            for fecha, ratio in serie:
                if fecha in propios:
                    continue
                try:
                    d = _date.fromisoformat(fecha)
                except ValueError:
                    continue
                if d.weekday() >= 5:
                    continue
                vacio = {"ref": 0, "compra": 0, "venta": 0,
                         "vol_compra": 0, "vol_venta": 0}
                db.guardar_lectura(par["alias"], ratio, vacio, vacio,
                                   ts=fecha + "T23:59:00")
                rellenados += 1

        if rellenados:
            log.info("relleno semanal: %d días completados con cierres de IOL",
                     rellenados)
        db.set_estado("ultimo_relleno", datetime.now().date().isoformat())
        return rellenados

    # -- historico ----------------------------------------------------

    def backfill(self):
        simbolos = set()
        for p in self.pares:
            simbolos.add((p["mercado"], p["num"]))
            simbolos.add((p["mercado"], p["den"]))
        hasta = datetime.now().date()

        for mercado, sim in sorted(simbolos):
            ultimo = db.ultimo_cierre_guardado(sim)
            if ultimo:
                desde = datetime.fromisoformat(ultimo).date() + timedelta(days=1)
                if desde > hasta:
                    continue
            else:
                desde = hasta - timedelta(days=BACKFILL_DIAS)
            try:
                datos = self.iol.serie(mercado, sim, desde.isoformat(),
                                       hasta.isoformat())
            except IOLError as e:
                log.warning("historico %s: %s", sim, e)
                continue
            filas = []
            for punto in datos or []:
                fecha = str(punto.get("fechaHora") or "")[:10]
                cierre = punto.get("ultimoPrecio") or punto.get("cierreAnterior")
                try:
                    cierre = float(cierre)
                except (TypeError, ValueError):
                    continue
                if fecha and cierre > 0:
                    filas.append((fecha, cierre))
            if filas:
                db.guardar_cierres(sim, filas)
                log.info("historico %s: +%d cierres", sim, len(filas))
            time.sleep(0.4)

    # -- loop ---------------------------------------------------------

    def loop(self):
        db.init()
        try:
            self.iol.login()
        except Exception as e:
            self.ultimo_error = str(e)
            log.error("no se pudo autenticar: %s", e)
            return

        try:
            self.backfill()
        except Exception as e:
            log.warning("backfill incompleto: %s", e)

        ultimo_backfill = datetime.now().date()
        espera = int(self.cfg.get("poll_seconds", 600))

        while True:
            try:
                if self._en_horario():
                    self.ciclo()
                    self.ultimo_error = None
                elif not self.snapshot:
                    self.ciclo()

                hoy = datetime.now().date()
                if hoy != ultimo_backfill and datetime.now().hour >= 18:
                    self.backfill()
                    db.purgar()
                    ultimo_backfill = hoy
                    # domingos: completar los días que faltaron
                    if hoy.weekday() == 6:
                        try:
                            self.rellenar_huecos()
                        except Exception as e:
                            log.warning("relleno semanal: %s", e)
            except Exception as e:
                self.ultimo_error = str(e)
                log.error("ciclo fallo: %s", e)

            if not self._en_horario():
                dormir = max(espera, 900)
            elif self.hay_rueda is False:
                dormir = max(espera, 1800)   # feriado: casi no consultamos
            else:
                dormir = espera
            time.sleep(dormir)


def _cerca_del_borde(par, ratio, est, umbral=0.15):
    """Devuelve 'alta', 'baja' o None si el ratio entró en el tramo final."""
    res = par.get("resistencia") or 0
    sop = par.get("soporte") or 0
    if res > 0 and sop > 0 and res > sop:
        ancho = res - sop
        if ratio >= res - ancho * umbral:
            return "alta"
        if ratio <= sop + ancho * umbral:
            return "baja"
        return None
    if est.get("n", 0) >= MIN_MUESTRA_Z and est.get("desvio"):
        z = (ratio - est["media"]) / est["desvio"]
        if z >= 1.5:
            return "alta"
        if z <= -1.5:
            return "baja"
    return None


def _stats(valores, fuente):
    if len(valores) < 5:
        return {"n": len(valores), "fuente": fuente}
    media = statistics.mean(valores)
    return {
        "n": len(valores),
        "fuente": fuente,
        "media": media,
        "desvio": statistics.pstdev(valores) if len(valores) > 1 else 0.0,
        "min": min(valores),
        "max": max(valores),
    }


def _n(v):
    try:
        return "{:,.2f}".format(float(v)).replace(",", "@").replace(
            ".", ",").replace("@", ".")
    except (TypeError, ValueError):
        return "—"


def _e(v):
    try:
        return "{:,.0f}".format(float(v or 0)).replace(",", ".")
    except (TypeError, ValueError):
        return "—"
