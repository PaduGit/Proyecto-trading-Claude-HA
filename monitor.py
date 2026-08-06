"""Motor de monitoreo: calcula ratios, evalua niveles y dispara alertas."""

import logging
import statistics
import threading
import time
from datetime import datetime, timedelta

import db
from iol import IOL, IOLError

log = logging.getLogger("monitor")

VENTANA_DIAS = 90
MIN_MUESTRA_Z = 25       # dias minimos para que el z-score signifique algo
BACKFILL_DIAS = 400


class Monitor:
    def __init__(self, cfg, iol: IOL, tg):
        self.cfg = cfg
        self.iol = iol
        self.tg = tg
        self.pares = cfg["pares"]
        self.snapshot = {}          # alias -> dict con el ultimo estado
        self.lock = threading.Lock()
        self.ultimo_ciclo = None
        self.ultimo_error = None
        # estado de alertas en memoria
        self._racha = {}            # alias -> (zona, cuenta)
        self._ultimo_aviso = {}     # (alias, zona) -> datetime

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

    # -- historico ----------------------------------------------------

    def backfill(self, forzar=False):
        """Descarga cierres faltantes. Solo trae lo que no esta guardado."""
        simbolos = set()
        for p in self.pares:
            simbolos.add((p["mercado"], p["num"]))
            simbolos.add((p["mercado"], p["den"]))

        hasta = datetime.now().date()
        for mercado, sim in sorted(simbolos):
            ultimo = db.ultimo_cierre_guardado(sim)
            if ultimo and not forzar:
                desde = datetime.fromisoformat(ultimo).date() + timedelta(days=1)
                if desde > hasta:
                    continue
            else:
                desde = hasta - timedelta(days=BACKFILL_DIAS)

            try:
                datos = self.iol.serie(
                    mercado, sim, desde.isoformat(), hasta.isoformat()
                )
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
            time.sleep(0.4)   # cortesia con la API

    def estadistica(self, par):
        """Media, desvio y rango del ratio diario en la ventana."""
        desde = (datetime.now().date() - timedelta(days=VENTANA_DIAS)).isoformat()
        serie = db.serie_ratio_diaria(par["num"], par["den"], desde)
        valores = [v for _, v in serie]
        if len(valores) < 5:
            return {"n": len(valores)}
        media = statistics.mean(valores)
        desvio = statistics.pstdev(valores) if len(valores) > 1 else 0.0
        return {
            "n": len(valores),
            "media": media,
            "desvio": desvio,
            "min": min(valores),
            "max": max(valores),
        }

    # -- evaluacion ---------------------------------------------------

    def _zona(self, par, ratio, est):
        """Devuelve (zona, nivel). zona in {alta, baja, normal}."""
        res = par.get("resistencia") or 0
        sop = par.get("soporte") or 0

        if res > 0 and ratio >= res:
            return "alta", res
        if sop > 0 and ratio <= sop:
            return "baja", sop

        # sin niveles definidos: caemos al z-score si hay muestra
        if not res and not sop and est.get("n", 0) >= MIN_MUESTRA_Z:
            d = est.get("desvio") or 0
            if d:
                z = (ratio - est["media"]) / d
                if z >= 2.0:
                    return "alta", est["media"] + 2 * d
                if z <= -2.0:
                    return "baja", est["media"] - 2 * d
        return "normal", None

    def _debe_avisar(self, alias, zona):
        """Confirmacion por lecturas repetidas + cooldown."""
        necesarias = int(self.cfg.get("confirm_readings", 2))
        prev_zona, cuenta = self._racha.get(alias, ("normal", 0))
        cuenta = cuenta + 1 if zona == prev_zona else 1
        self._racha[alias] = (zona, cuenta)

        if zona == "normal" or cuenta < necesarias:
            return False

        cooldown = timedelta(minutes=int(self.cfg.get("alert_cooldown_minutes", 90)))
        ultimo = self._ultimo_aviso.get((alias, zona))
        if ultimo and datetime.now() - ultimo < cooldown:
            return False
        self._ultimo_aviso[(alias, zona)] = datetime.now()
        return True

    def _mensaje(self, par, ratio, zona, nivel, est, num, den):
        icono = "🔴" if zona == "alta" else "🟢"
        que = "tocó resistencia" if zona == "alta" else "tocó soporte"
        lineas = [
            f"{icono} <b>{par['alias']}</b> {que}",
            f"Ratio <b>{ratio:.4f}</b>  (nivel {nivel:.4f})",
            "",
            f"{par['num']}: {num['ref']:,.2f}"
            + (f"  [{num['compra']:,.2f} / {num['venta']:,.2f}]" if num["compra"] else ""),
            f"{par['den']}: {den['ref']:,.2f}"
            + (f"  [{den['compra']:,.2f} / {den['venta']:,.2f}]" if den["compra"] else ""),
        ]
        if est.get("n", 0) >= MIN_MUESTRA_Z and est.get("desvio"):
            z = (ratio - est["media"]) / est["desvio"]
            lineas += [
                "",
                f"Media {VENTANA_DIAS}d: {est['media']:.4f}   z: {z:+.2f}",
                f"Rango: {est['min']:.4f} – {est['max']:.4f}  (n={est['n']})",
            ]
        lineas.append("")
        lineas.append(f"<i>{datetime.now():%H:%M:%S}</i>")
        return "\n".join(lineas)

    def evaluar_par(self, par):
        num = self.iol.cotizacion(par["mercado"], par["num"], par.get("plazo", "t2"))
        den = self.iol.cotizacion(par["mercado"], par["den"], par.get("plazo", "t2"))

        if not num["ref"] or not den["ref"]:
            raise IOLError(f"sin precio para {par['num']} o {par['den']}")

        ratio = num["ref"] / den["ref"]
        est = self.estadistica(par)
        zona, nivel = self._zona(par, ratio, est)

        db.guardar_lectura(par["alias"], ratio, num, den)

        z = None
        if est.get("n", 0) >= MIN_MUESTRA_Z and est.get("desvio"):
            z = (ratio - est["media"]) / est["desvio"]

        estado = {
            "alias": par["alias"],
            "num": par["num"], "den": par["den"],
            "ratio": ratio,
            "zona": zona,
            "resistencia": par.get("resistencia") or 0,
            "soporte": par.get("soporte") or 0,
            "z": z,
            "est": est,
            "p_num": num, "p_den": den,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "alertas": bool(par.get("alertas")),
        }

        if par.get("alertas") and self._debe_avisar(par["alias"], zona):
            msg = self._mensaje(par, ratio, zona, nivel, est, num, den)
            self.tg.enviar(msg)
            db.registrar_alerta(par["alias"], zona, ratio, nivel, msg)
            log.info("alerta %s %s @ %.4f", par["alias"], zona, ratio)

        return estado

    # -- ciclo --------------------------------------------------------

    def ciclo(self):
        for par in self.pares:
            try:
                estado = self.evaluar_par(par)
                with self.lock:
                    self.snapshot[par["alias"]] = estado
            except Exception as e:
                log.warning("%s: %s", par["alias"], e)
                with self.lock:
                    prev = self.snapshot.get(par["alias"], {})
                    prev["error"] = str(e)
                    prev.setdefault("alias", par["alias"])
                    self.snapshot[par["alias"]] = prev
        self.ultimo_ciclo = datetime.now()

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
        espera = int(self.cfg.get("poll_seconds", 180))

        while True:
            try:
                if self._en_horario():
                    self.ciclo()
                    self.ultimo_error = None
                else:
                    # fuera de rueda: un ciclo cada tanto para mantener el snapshot
                    if not self.snapshot:
                        self.ciclo()

                hoy = datetime.now().date()
                if hoy != ultimo_backfill and datetime.now().hour >= 18:
                    self.backfill()
                    db.purgar()
                    ultimo_backfill = hoy
            except Exception as e:
                self.ultimo_error = str(e)
                log.error("ciclo fallo: %s", e)

            time.sleep(espera if self._en_horario() else max(espera, 600))
