#!/usr/bin/env python3
"""
HumanIA - Envio de avisos por Telegram (FASE 30+)

Canal de alertas internas (saturacion/salud del servidor). Se eligio Telegram
porque el droplet de PROD tiene BLOQUEADO el SMTP saliente (puertos 25/587/465,
medida anti-spam de DigitalOcean) y porque asi las alertas NO consumen el cupo
de Resend, reservado para el correo de los usuarios (verificacion / reset).
La API de Telegram va por HTTPS (443), que si sale del droplet.

Variables de entorno:
  HUMANIA_TELEGRAM_TOKEN    token del bot (de @BotFather)
  HUMANIA_TELEGRAM_CHAT_ID  id del chat destino

Sin credenciales (dev/tests) NO se llama a la red: el mensaje se registra en
memoria en SENT_TELEGRAM (mismo patron que el backend 'console' de email_sender).
"""
import os

import httpx

API_URL = "https://api.telegram.org/bot{token}/sendMessage"

# Registro en memoria de los envios en modo sin-credenciales (lo usan tests y UAT)
SENT_TELEGRAM = []
MAX_SENT_LOG = 50


def is_configured() -> bool:
    return bool(os.environ.get("HUMANIA_TELEGRAM_TOKEN") and os.environ.get("HUMANIA_TELEGRAM_CHAT_ID"))


def send_telegram(text: str) -> bool:
    token = os.environ.get("HUMANIA_TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("HUMANIA_TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        # dev/tests: sin credenciales, registra en memoria y no toca la red
        SENT_TELEGRAM.append({"chat_id": chat_id, "text": text})
        del SENT_TELEGRAM[:-MAX_SENT_LOG]
        return True
    resp = httpx.post(API_URL.format(token=token),
                      json={"chat_id": chat_id, "text": text}, timeout=20)
    resp.raise_for_status()
    return True
