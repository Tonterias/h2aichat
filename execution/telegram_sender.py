#!/usr/bin/env python3
"""
HumanIA - Envio de avisos por Telegram (FASE 30+)

Internal alert channel for saturation and server health. Telegram was chosen because
the production host BLOCKS outgoing SMTP (ports 25, 587 and 465, an anti-spam measure
at the hosting provider), and because this way alerts do NOT eat into the Resend quota,
which is reserved for users' mail: verification and password resets.
The Telegram API runs over HTTPS on port 443, which does leave the machine.

Variables de entorno:
  HUMANIA_TELEGRAM_TOKEN    token del bot (de @BotFather)
  HUMANIA_TELEGRAM_CHAT_ID  id del chat destino

Without credentials (dev and tests) the network is NOT touched: the message is recorded
in memory in SENT_TELEGRAM, the same pattern as email_sender's 'console' backend.
"""
import os

import httpx

API_URL = "https://api.telegram.org/bot{token}/sendMessage"

# In-memory record of what would have been sent when there are no credentials.
SENT_TELEGRAM = []
MAX_SENT_LOG = 50


def is_configured() -> bool:
    return bool(os.environ.get("HUMANIA_TELEGRAM_TOKEN") and os.environ.get("HUMANIA_TELEGRAM_CHAT_ID"))


def send_telegram(text: str) -> bool:
    token = os.environ.get("HUMANIA_TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("HUMANIA_TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        # dev and tests: no credentials, record in memory and leave the network alone
        SENT_TELEGRAM.append({"chat_id": chat_id, "text": text})
        del SENT_TELEGRAM[:-MAX_SENT_LOG]
        return True
    resp = httpx.post(API_URL.format(token=token),
                      json={"chat_id": chat_id, "text": text}, timeout=20)
    resp.raise_for_status()
    return True
