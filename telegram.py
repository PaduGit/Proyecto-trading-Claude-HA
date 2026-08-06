"""Envio de mensajes a Telegram. Sin dependencias extra."""

import logging

import requests

log = logging.getLogger("telegram")


class Telegram:
    def __init__(self, token, chat_id):
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.activo = bool(self.token and self.chat_id)
        if not self.activo:
            log.warning("Telegram sin configurar: las alertas solo quedan en el log")

    def enviar(self, texto):
        if not self.activo:
            log.info("[alerta no enviada] %s", texto)
            return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": texto,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if r.status_code != 200:
                log.error("Telegram %s: %s", r.status_code, r.text[:200])
                return False
            return True
        except Exception as e:
            log.error("Telegram fallo: %s", e)
            return False
