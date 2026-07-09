#!/usr/bin/env python3
"""
HumanIA - Envio de email (FASES 20.3/20.4)

Backend intercambiable via HUMANIA_EMAIL_BACKEND (decision PO 2026-06-11):
  - "console" (default en dev): imprime el email en la consola del servidor.
    Sin servicios externos. Los tests capturan los envios en SENT_EMAILS.
  - "resend" (produccion, decision final PO 2026-06-11, FASE 20.1): API HTTP de
    Resend con dominio verificado noreplay.h2aichat.com.
  - "smtp": SMTP estandar con STARTTLS. Alternativa conservada (leccion 99).

Variables de entorno (backend resend):
  RESEND_API_KEY
  HUMANIA_EMAIL_FROM (default hola@noreplay.h2aichat.com)

Variables de entorno (backend smtp):
  HUMANIA_SMTP_HOST (default smtp.gmail.com)
  HUMANIA_SMTP_PORT (default 587)
  HUMANIA_SMTP_USER
  HUMANIA_SMTP_PASS
  HUMANIA_EMAIL_FROM (default = HUMANIA_SMTP_USER)
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "hola@noreplay.h2aichat.com"

# Registro en memoria de los envios del backend console (lo usan los tests y el UAT)
SENT_EMAILS = []
MAX_SENT_LOG = 50


def get_backend() -> str:
    backend = os.environ.get("HUMANIA_EMAIL_BACKEND", "console").lower()
    if backend not in ("console", "resend", "smtp"):
        raise RuntimeError(f"HUMANIA_EMAIL_BACKEND desconocido: '{backend}'. Usa 'console', 'resend' o 'smtp'.")
    if os.environ.get("HUMANIA_ENV", "dev") == "production" and backend == "console":
        raise RuntimeError("HUMANIA_EMAIL_BACKEND=console no es valido en produccion. Usa 'resend' o 'smtp'.")
    return backend


def validate_production_config():
    """Fallo en arranque (FASE 20.1-A3), mismo patron que HUMANIA_TOKEN/JWT_SECRET:
    en produccion el backend debe ser valido y tener sus credenciales configuradas."""
    if os.environ.get("HUMANIA_ENV", "dev") != "production":
        return
    backend = get_backend()  # rechaza console y valores desconocidos
    if backend == "resend" and not os.environ.get("RESEND_API_KEY"):
        raise RuntimeError("RESEND_API_KEY must be set in production (HUMANIA_EMAIL_BACKEND=resend)")
    if backend == "smtp" and not (os.environ.get("HUMANIA_SMTP_USER") and os.environ.get("HUMANIA_SMTP_PASS")):
        raise RuntimeError("HUMANIA_SMTP_USER y HUMANIA_SMTP_PASS must be set in production (HUMANIA_EMAIL_BACKEND=smtp)")


def send_email(to: str, subject: str, body_text: str, body_html: str = None) -> bool:
    backend = get_backend()
    if backend == "resend":
        return _send_resend(to, subject, body_text, body_html)
    if backend == "smtp":
        return _send_smtp(to, subject, body_text, body_html)
    return _send_console(to, subject, body_text)


def _send_console(to: str, subject: str, body_text: str) -> bool:
    print(f"\n{'=' * 60}\n[EMAIL console] Para: {to}\nAsunto: {subject}\n{'-' * 60}\n{body_text}\n{'=' * 60}\n", flush=True)
    SENT_EMAILS.append({"to": to, "subject": subject, "body": body_text})
    del SENT_EMAILS[:-MAX_SENT_LOG]
    return True


def _send_resend(to: str, subject: str, body_text: str, body_html: str = None) -> bool:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        raise RuntimeError("Backend resend requiere RESEND_API_KEY")
    sender = os.environ.get("HUMANIA_EMAIL_FROM", DEFAULT_FROM)
    payload = {"from": sender, "to": [to], "subject": subject, "text": body_text}
    if body_html:
        payload["html"] = body_html
    resp = httpx.post(RESEND_API_URL, json=payload,
                      headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
    resp.raise_for_status()
    return True


def _send_smtp(to: str, subject: str, body_text: str, body_html: str = None) -> bool:
    host = os.environ.get("HUMANIA_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("HUMANIA_SMTP_PORT", "587"))
    user = os.environ.get("HUMANIA_SMTP_USER", "")
    password = os.environ.get("HUMANIA_SMTP_PASS", "")
    sender = os.environ.get("HUMANIA_EMAIL_FROM", user)
    if not user or not password:
        raise RuntimeError("Backend smtp requiere HUMANIA_SMTP_USER y HUMANIA_SMTP_PASS")

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(sender, [to], msg.as_string())
    return True


def base_url() -> str:
    return os.environ.get("HUMANIA_BASE_URL", "http://localhost:8000").rstrip("/")


def _privacy_footer() -> str:
    """GDPR 20.8f: por que recibes este email + enlace a la politica de privacidad."""
    return (f"\n\n—\nRecibes este email porque se solicito una accion con tu direccion en h2aichat.com. "
            f"Politica de privacidad: {base_url()}/web#privacidad")


def send_verification_email(to: str, token: str) -> bool:
    link = f"{base_url()}/auth/verify-email?token={token}"
    return send_email(
        to,
        "Verifica tu email — H2AI Chat",
        f"Bienvenido a H2AI Chat.\n\nVerifica tu email abriendo este enlace:\n{link}\n\n"
        f"El enlace caduca en 24 horas. Si no creaste esta cuenta, ignora este mensaje." + _privacy_footer(),
        f'<p>Bienvenido a <b>H2AI Chat</b>.</p><p><a href="{link}">Verifica tu email</a> '
        f"(caduca en 24 horas).</p><p>Si no creaste esta cuenta, ignora este mensaje.</p>"
        f'<p style="color:#888;font-size:12px">Recibes este email porque se solicitó una acción con tu dirección en h2aichat.com. '
        f'<a href="{base_url()}/web#privacidad">Política de privacidad</a></p>',
    )


def send_password_reset_email(to: str, token: str) -> bool:
    link = f"{base_url()}/auth/reset-password?token={token}"
    return send_email(
        to,
        "Recupera tu contraseña — H2AI Chat",
        f"Has pedido restablecer tu contraseña en H2AI Chat.\n\nAbre este enlace:\n{link}\n\n"
        f"El enlace caduca en 1 hora. Si no lo pediste tú, ignora este mensaje." + _privacy_footer(),
        f'<p>Has pedido restablecer tu contraseña en <b>H2AI Chat</b>.</p>'
        f'<p><a href="{link}">Crear nueva contraseña</a> (caduca en 1 hora).</p>'
        f"<p>Si no lo pediste tú, ignora este mensaje.</p>"
        f'<p style="color:#888;font-size:12px">Recibes este email porque se solicitó una acción con tu dirección en h2aichat.com. '
        f'<a href="{base_url()}/web#privacidad">Política de privacidad</a></p>',
    )
