"""FASE 20.1 (leccion 106) — Frontend con AUTH FORZADA (como produccion).

Cubre el viaje real de un usuario con sesion JWT en el navegador:
carga inicial del chat con contenido (no en blanco), hilo canonico con prefijo
de usuario, nueva conversacion visible en el menu, y errores de envio visibles.

Estos fallos llegaron a produccion porque toda la suite previa corria en modo dev
(hallazgos UAT PO 2026-06-12).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE = "http://127.0.0.1:8766"
ROOT = Path(__file__).parent.parent.parent


def _post(path, data, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", data=json.dumps(data).encode("utf-8"),
                                 headers=headers, method="POST")
    return json.loads(urllib.request.urlopen(req).read())


@pytest.fixture(scope="module")
def auth_server():
    """Servidor aparte (puerto 8766) con HUMANIA_AUTH=on. No borra la BD: usa un
    usuario nuevo por ejecucion (aislamiento por threads de 20.2)."""
    env = dict(os.environ, HUMANIA_AUTH="on")
    proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "execution.api_server:app",
         "--port", "8766", "--host", "127.0.0.1"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            urllib.request.urlopen(f"{BASE}/status", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        raise RuntimeError("auth server did not start within 10s")
    yield BASE
    proc.terminate()
    proc.wait()


@pytest.fixture(scope="module")
def user_token(auth_server):
    """Usuario fresco + participantes registrados + un mensaje semilla en 'general'."""
    from engine import ConversationEngine
    eng = ConversationEngine(base_path=ROOT)
    eng.register_participant("miguel", "t-uat-1", "human", "miguel@test.local")
    eng.register_participant("qwen_plus", "t-uat-2", "bot", "qwen@test.local")
    email = f"uat_{int(time.time())}@test.local"
    resp = _post("/auth/register", {"email": email, "password": "secreta123",
                                    "name": "UAT", "accept_terms": True, "confirm_adult": True})
    token = resp["token"]
    user_id = resp["user"]["user_id"]
    # mensajes semilla via API autenticada: crean el hilo user_N_general
    _post("/message/send", {"recipient_id": "qwen_plus", "body": "Mensaje semilla UAT",
                            "sender_id": "miguel", "thread_id": "general"}, token=token)
    # y una respuesta de agente (directa por engine) para poder verificar su burbuja
    eng.send_message("miguel", "Respuesta semilla del agente", "qwen_plus",
                     thread_id=f"user_{user_id}_general")
    return token


@pytest.fixture
def auth_page(browser, auth_server, user_token):
    pg = browser.new_page()
    pg.add_init_script(f"localStorage.setItem('h2ai_token', '{user_token}')")
    pg.goto(f"{auth_server}/chat")
    pg.wait_for_load_state("networkidle")
    yield pg
    pg.close()


def test_carga_inicial_no_en_blanco(auth_page):
    """El chat debe mostrar los mensajes del usuario SIN tener que pulsar el hilo."""
    auth_page.wait_for_selector("#chatMessages .msg-row", timeout=8000)
    assert auth_page.locator("#chatMessages .msg-row").count() >= 1


def test_hilo_canonico_sincronizado(auth_page):
    """currentThread debe sincronizarse al nombre real (user_N_general)."""
    auth_page.wait_for_selector("#chatMessages .msg-row", timeout=8000)
    current = auth_page.evaluate("currentThread")
    assert current.startswith("user_") and current.endswith("_general"), current


def test_menu_no_ensena_prefijo_interno(auth_page):
    """El menu izquierdo muestra 'general', no 'user_N_general'."""
    auth_page.wait_for_selector("#threadList .thread-row", timeout=8000)
    names = auth_page.locator("#threadList .thread-name").all_inner_texts()
    assert any(n == "general" for n in names), names
    assert not any(n.startswith("user_") for n in names), names


def test_nueva_conversacion_aparece_en_menu(auth_page):
    """Hallazgo UAT: la conversacion recien creada debe verse en el menu izquierdo."""
    auth_page.wait_for_selector("#threadList .thread-row", timeout=8000)
    auth_page.on("dialog", lambda d: d.accept("Prueba UAT"))
    auth_page.click(".new-thread-wrap button")
    auth_page.wait_for_timeout(800)
    names = auth_page.locator("#threadList .thread-name").all_inner_texts()
    assert any("Prueba_UAT" in n for n in names), names
    assert auth_page.locator("#chatTitle").inner_text() == "Prueba_UAT"


def test_error_de_envio_visible(auth_page):
    """Hallazgo UAT: un fallo del servidor al enviar debe mostrarse, no tragarse."""
    auth_page.evaluate("showSendError('Limite del plan free alcanzado')")
    toast = auth_page.locator("#sendErrorToast")
    toast.wait_for(state="visible", timeout=3000)
    assert "Limite del plan free" in toast.inner_text()


def test_burbujas_estilo_whatsapp(auth_page):
    """FASE 20.1-UX2 (PO): burbuja de agente BLANCA, color solo en la cabecera,
    cuerpo casi-negro, hora dentro de la burbuja."""
    auth_page.wait_for_selector("#chatMessages .bubble.wa", timeout=8000)
    agent = auth_page.locator("#chatMessages .msg-row:not(.center) .bubble.wa").first
    agent.wait_for(state="visible", timeout=8000)
    bg = agent.evaluate("el=>getComputedStyle(el).backgroundColor")
    assert bg == "rgb(255, 255, 255)", f"burbuja de agente debe ser blanca, es {bg}"
    rgb = agent.locator(".bubble-body").evaluate(
        "el=>getComputedStyle(el).color.match(/\\d+/g).map(Number)")
    assert all(c < 100 for c in rgb[:3]), f"cuerpo debe ser casi negro, es {rgb}"
    assert agent.locator(".bubble-time").is_visible()
    assert agent.locator(".bubble-head").is_visible()


# ── FASE 20.1-UX: menus de usuario reordenados (decision PO 2026-06-12) ──

def test_menu_del_chat_sin_acciones_destructivas(auth_page):
    """En el chat solo: Mi cuenta + Cerrar sesion. Eliminar/exportar viven en /web#cuenta."""
    auth_page.wait_for_selector("#chatMessages .msg-row", timeout=8000)
    auth_page.evaluate("toggleAccountMenu()")
    menu = auth_page.locator("#accountMenu")
    menu.wait_for(state="visible", timeout=3000)
    text = menu.inner_text()
    assert "Mi cuenta" in text
    assert "Cerrar sesión" in text
    assert "Eliminar" not in text
    assert "Descargar" not in text


def test_pagina_mi_cuenta(browser, auth_server, user_token):
    """/web#cuenta: perfil, plan/uso, descarga RGPD y zona de peligro al final."""
    pg = browser.new_page()
    pg.add_init_script(f"localStorage.setItem('h2ai_token', '{user_token}')")
    # ojo: networkidle nunca llega en /web (el iframe de Vimeo mantiene la red viva)
    pg.goto(f"{auth_server}/web#cuenta", wait_until="domcontentloaded")
    pg.wait_for_selector("#zona-peligro", timeout=10000)
    body = pg.locator("#cuenta-body")
    text = body.inner_text()
    assert "Plan" in text and "Conversaciones este mes" in text
    assert "Descargar mis datos" in text
    assert "Cerrar sesión" in text          # bug PO 2026-06-13
    assert pg.locator("#logoutBtn").is_visible()
    assert "Eliminar cuenta" in text
    nav = pg.locator("#navPublicActions").inner_text()
    assert "Mi cuenta" in nav and "Ir al chat" in nav
    pg.close()
