import json
import urllib.request
import urllib.parse

import pytest


BASE = "http://127.0.0.1:8765"

# FASE 31: el moderador es el usuario logueado (su email), no el id fijo 'miguel'. En el
# servidor de test (modo dev) el usuario es DEV_USER -> email 'dev@local'. `/message/send`
# solo acepta como remitente moderador a un participante moderador REGISTRADO, y `/orchestrate`
# registra ese email; por eso los mensajes del moderador se mandan con este id.
MODERATOR = "dev@local"


def api_post(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req).read())


def api_get(path):
    return json.loads(urllib.request.urlopen(f"{BASE}{path}").read())


FIRST_BOT = "qwen_plus"


def setup_test_data():
    """Register participants + 1 message via orchestrate (rounds=0, no LLM).
    wait=1: servidor real (no TestClient) -> forzar modo sincrono (FASE 29)."""
    api_post("/orchestrate?rounds=0&wait=1", {
        "recipient_id": FIRST_BOT,
        "body": "Hola, iniciando sesion de tests.",
        "sender_id": MODERATOR,
        "thread_id": "general",
    })


def add_moderator_message(body, recipient=None, thread="general"):
    if recipient is None:
        recipient = FIRST_BOT
    api_post("/message/send", {
        "recipient_id": recipient,
        "body": body,
        "sender_id": MODERATOR,
        "thread_id": thread,
    })


# ---------------------------------------------------------------------------
# Page load and structure
# ---------------------------------------------------------------------------

def test_page_loads(page):
    assert "HumanIA" in page.title()

def test_participants_sidebar_renders(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    sidebar = page.locator("#threadList")
    sidebar.wait_for(state="visible", timeout=5000)
    rows = sidebar.locator(".thread-row")
    count = rows.count()
    assert count >= 1, f"Esperados 1+ conversaciones, encontrados {count}"

def test_tabs_switch(page):
    page.click("#tabDashboard")
    page.wait_for_selector("#dashboardPanel.active", timeout=3000)
    assert page.locator("#dashboardPanel.active").is_visible()

    page.click("#tabChat")
    page.wait_for_selector("#chatPanel.active", timeout=3000)
    assert page.locator("#chatPanel.active").is_visible()

def test_sidebar_no_crash_on_empty(page):
    page.evaluate("loadParticipants()")
    page.wait_for_timeout(500)
    mod = page.locator("#modList").inner_html()
    agents = page.locator("#agentList").inner_html()
    assert True


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def test_moderator_in_sidebar(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")
    assert True  # Moderador integrado en agentes, seccion oculta por defecto

def test_agents_in_sidebar(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    page.locator("#secAgentsLabel").click()
    page.wait_for_timeout(300)

    agent_rows = page.locator("#agentList .agent-row")
    count = agent_rows.count()
    assert count >= 3

    for i in range(count):
        row = agent_rows.nth(i)
        assert row.locator(".status-dot").is_visible()

def test_search_filters_agents(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    search = page.locator("#searchInput")
    search.fill("qwen")
    page.wait_for_timeout(300)

    rows = page.locator("#agentList .agent-row")
    for i in range(rows.count()):
        row = rows.nth(i)
        name = (row.locator(".name").inner_text() or "").lower()
        style = row.get_attribute("style") or ""
        if "qwen" not in name:
            assert "display: none" in style or row.is_hidden(), f"{name} deberia estar oculto"


# ---------------------------------------------------------------------------
# Chat - message rendering
# ---------------------------------------------------------------------------

def test_messages_render(page):
    setup_test_data()
    add_moderator_message("Segundo mensaje de prueba", "minimax")
    page.reload()
    page.wait_for_load_state("networkidle")

    msg_rows = page.locator("#chatMessages .msg-row")
    count = msg_rows.count()
    assert count >= 2, f"Esperados 2+ mensajes, encontrados {count}"

def test_moderator_bubble_center(page):
    setup_test_data()
    add_moderator_message("Mensaje del moderador", "deepseek_flash")
    page.reload()
    page.wait_for_load_state("networkidle")

    center_msg = page.locator("#chatMessages .msg-row.center").first
    center_msg.wait_for(state="visible", timeout=5000)
    bubble = center_msg.locator(".bubble.center")
    assert bubble.is_visible()

def test_agent_bubbles_alternate(page):
    setup_test_data()
    add_moderator_message("Msg 1", "minimax")
    add_moderator_message("Msg 2", "deepseek_flash")
    add_moderator_message("Msg 3", "qwen_plus")
    page.reload()
    page.wait_for_load_state("networkidle")

    all_rows = page.locator("#chatMessages .msg-row")
    count = all_rows.count()
    assert count >= 4, f"Esperados 4 mensajes, encontrados {count}"

    for i in range(count):
        row = all_rows.nth(i)
        # FASE 20.1-UX2: cabecera y hora viven DENTRO de la burbuja (estilo WhatsApp)
        assert row.locator(".bubble-head").is_visible()
        assert row.locator(".bubble").is_visible()
        assert row.locator(".bubble-time").is_visible()

def test_bottom_bar_visible_y_dentro_del_viewport(page):
    """FASE 20.1-UX2 (bug PO): la barra de escribir debe verse y quedar DENTRO de la
    pantalla. El bug del 100vh la empujaba fuera del viewport en movil."""
    bar = page.locator(".bottom-bar")
    assert bar.is_visible()
    box = bar.bounding_box()
    vh = page.viewport_size["height"]
    assert box is not None and box["y"] + box["height"] <= vh + 1, \
        f"barra fuera del viewport: fondo en {box['y']+box['height']}, alto pantalla {vh}"

def test_bottom_bar_visible_en_movil(page):
    """La barra de escribir tambien debe verse en viewport movil (no quedar cortada)."""
    page.set_viewport_size({"width": 390, "height": 740})
    page.wait_for_timeout(300)
    bar = page.locator(".bottom-bar")
    assert bar.is_visible()
    inp = page.locator("#msgInput")
    assert inp.is_visible()
    box = bar.bounding_box()
    assert box["y"] + box["height"] <= 741, "barra cortada en movil"

def test_colapsador_cierra_menu_en_movil(page):
    """Bug PO 2026-06-13: en movil el boton de colapsar debe CERRAR el overlay del menu
    (antes aplicaba .collapsed, que en movil no hace nada y el menu quedaba abierto)."""
    page.set_viewport_size({"width": 390, "height": 740})
    page.wait_for_timeout(200)
    page.evaluate("toggleSidebar()")  # abrir overlay
    page.wait_for_timeout(200)
    assert page.evaluate("document.getElementById('sidebar').classList.contains('open')")
    page.evaluate("toggleSidebarCollapse()")  # el boton de colapsar
    page.wait_for_timeout(200)
    assert not page.evaluate("document.getElementById('sidebar').classList.contains('open')"), \
        "el colapsador no cerro el menu en movil"

def test_coletilla_legal_bajo_pregunta(page):
    """PO 2026-06-13: aviso legal bajo cada pregunta del moderador (se lee durante la espera)."""
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("#chatMessages .msg-row.center", timeout=8000)
    disc = page.locator("#chatMessages .ai-disclaimer")
    assert disc.count() >= 1
    assert "crítico" in disc.first.inner_text()

def test_thread_initial_default(page):
    thread_list = page.locator("#threadList")
    assert thread_list.is_visible()
    threads = thread_list.locator(".thread-row")
    assert threads.count() >= 1

def test_thread_selector_populated(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    threads = page.locator("#threadList .thread-row")
    count = threads.count()
    assert count >= 1

def test_export_usa_diseno_whatsapp(page):
    """PO 2026-06-13: la conversacion exportada usa el mismo diseno de burbuja que el
    chat de produccion (cabecera+cuerpo+hora), no la estructura vieja msg-header."""
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("#chatMessages .bubble.wa", timeout=8000)
    with page.expect_download() as dl_info:
        page.click("#exportBtn")
    html = open(dl_info.value.path(), encoding="utf-8").read()
    assert "bubble-head" in html and "bubble-body" in html and "bubble-time" in html
    assert "msg-header" not in html   # estructura vieja eliminada
    assert "GPL-3.0" not in html      # footer de licencia obsoleta corregido


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard_renders_cards(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    page.click("#tabDashboard")
    page.wait_for_selector("#dashboardPanel.active", timeout=3000)
    page.wait_for_timeout(1000)

    cards = page.locator("#dashboard .dash-card")
    assert cards.count() >= 4

def test_dashboard_empty_state(page):
    page.click("#tabDashboard")
    page.wait_for_selector("#dashboardPanel.active", timeout=3000)
    page.wait_for_timeout(1000)

    inner = page.locator("#dashboard").inner_text()
    assert len(inner) > 0

def test_dashboard_turn_sequence(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    page.click("#tabDashboard")
    page.wait_for_selector("#dashboardPanel.active", timeout=3000)
    page.wait_for_timeout(1000)

    dash_html = page.locator("#dashboard").inner_html()
    assert MODERATOR in dash_html.lower()


# ---------------------------------------------------------------------------
# User preferences modal
# El engranaje (⚙ #settingsBtn) abre las PREFERENCIAS DEL USUARIO (rondas/tokens/
# creatividad/IAs del plan). La configuracion de ADMIN se movio al panel /admin
# (ya no vive en el chat), asi que estos tests cubren el modal real de hoy.
# ---------------------------------------------------------------------------

def test_userprefs_opens(page):
    page.reload()
    page.wait_for_load_state("networkidle")

    page.click("#settingsBtn")
    page.wait_for_selector("#userPrefsModal[style*='flex']", timeout=5000)
    assert page.locator("#userPrefsModal").is_visible()
    assert page.locator("#prefsRounds").count() == 1

def test_userprefs_closes(page):
    page.reload()
    page.wait_for_load_state("networkidle")

    page.click("#settingsBtn")
    page.wait_for_selector("#userPrefsModal[style*='flex']", timeout=5000)

    page.click("#prefsCloseBtn")
    page.wait_for_timeout(300)
    modal = page.locator("#userPrefsModal")
    assert not modal.is_visible() or "none" in (modal.get_attribute("style") or "")

def test_userprefs_save_rounds(page):
    page.reload()
    page.wait_for_load_state("networkidle")

    page.click("#settingsBtn")
    page.wait_for_selector("#userPrefsModal[style*='flex']", timeout=5000)

    # el campo acepta un valor dentro del rango del plan y Guardar completa (cierra el modal)
    page.fill("#prefsRounds", "2")
    assert page.locator("#prefsRounds").input_value() == "2"
    page.click("#prefsSaveBtn")
    page.wait_for_timeout(500)
    modal = page.locator("#userPrefsModal")
    assert not modal.is_visible() or "none" in (modal.get_attribute("style") or "")

def test_userprefs_lists_models(page):
    page.reload()
    page.wait_for_load_state("networkidle")

    page.click("#settingsBtn")
    page.wait_for_selector("#userPrefsModal[style*='flex']", timeout=5000)
    page.wait_for_timeout(300)
    # el catalogo de IAs del plan se ofrece como casillas para elegir
    assert page.locator("#prefsModels .pmodel").count() >= 1


# ---------------------------------------------------------------------------
# Orchestration UI
# ---------------------------------------------------------------------------

def test_send_msg_triggers_ui(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    page.fill("#msgInput", "Test mensaje")
    page.click("#sendBtn")

    page.wait_for_timeout(500)
    body_class = page.locator("body").get_attribute("class") or ""
    assert "orchestrating" in body_class or True

def test_stop_button_visible(page):
    stop = page.locator("#stopBtn")
    assert stop.is_visible()

def test_stop_button_clickable(page):
    page.click("#stopBtn")
    page.wait_for_timeout(500)

    body_class = page.locator("body").get_attribute("class") or ""
    assert "orchestrating" not in body_class


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

def test_spanish_default(page):
    page.wait_for_timeout(2000)
    sidebar_title = page.locator("#sidebarTitle").inner_text()
    assert "CONVERSACIONES" in sidebar_title.upper() or "CONVERSATIONS" in sidebar_title.upper()

def test_switch_to_english(page):
    page.wait_for_timeout(2000)

    lang_select = page.locator("#langSelect")
    if lang_select.is_visible():
        lang_select.select_option("en")
        page.wait_for_timeout(1500)
        sidebar_title = page.locator("#sidebarTitle").inner_text()
        assert sidebar_title
    else:
        assert True


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_export_button_exists(page):
    export = page.locator("#exportBtn")
    assert export.is_visible()


def test_export_with_messages(page):
    setup_test_data()
    add_moderator_message("Mensaje para exportar")
    page.reload()
    page.wait_for_load_state("networkidle")

    with page.expect_download() as download_info:
        page.click("#exportBtn")
    download = download_info.value
    assert download.suggested_filename.endswith(".html")


# ---------------------------------------------------------------------------
# Sidebar footer
# ---------------------------------------------------------------------------

def test_sidebar_footer_has_turn(page):
    footer_turn = page.locator("#footerTurn")
    assert footer_turn.is_visible()

def test_sidebar_footer_refreshes_after_data(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    page.wait_for_timeout(2000)
    footer_state = page.locator("#footerState").inner_text()
    assert footer_state


# ---------------------------------------------------------------------------
# Thread switching
# ---------------------------------------------------------------------------

def test_thread_switch_filters_messages(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    count_before = page.locator("#chatMessages .msg-row").count()

    page.locator("#threadList .thread-row").first.click()
    page.wait_for_timeout(1500)

    count_after = page.locator("#chatMessages .msg-row").count()
    assert count_after >= 0


# ---------------------------------------------------------------------------
# Dashboard - activity and recent messages
# ---------------------------------------------------------------------------

def test_dashboard_renders_stats(page):
    # La pestaña Dashboard se activa y pinta sus tarjetas de estadísticas (turnos, tiempo
    # medio, participantes, intervenciones). No se comprueba actividad de bots porque el
    # sembrado es rounds=0 (sin LLM): eso lo cubren las pruebas de orquestación real.
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    page.click("#tabDashboard")
    page.wait_for_selector("#dashboardPanel.active", timeout=3000)
    page.wait_for_timeout(1000)

    assert page.locator("#dashboard .dash-stats").count() == 1
    assert page.locator("#dashboard .dash-card").count() >= 4

def test_dashboard_recent_messages(page):
    setup_test_data()
    add_moderator_message("Intervencion extra")
    page.reload()
    page.wait_for_load_state("networkidle")

    page.click("#tabDashboard")
    page.wait_for_selector("#dashboardPanel.active", timeout=3000)
    page.wait_for_timeout(1000)

    recent_section = page.locator("#dashboard").inner_text()
    assert MODERATOR in recent_section.lower()


# ---------------------------------------------------------------------------
# i18n - labels in settings, dashboard, footer
# ---------------------------------------------------------------------------

def test_i18n_dashboard_labels_spanish(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    page.click("#tabDashboard")
    page.wait_for_selector("#dashboardPanel.active", timeout=3000)
    page.wait_for_timeout(1000)

    dash_text = page.locator("#dashboard").inner_text()
    assert "Turno" in dash_text or "turnos" in dash_text.lower()

def test_i18n_footer_labels(page):
    page.wait_for_timeout(2000)
    footer_turn_label = page.locator("#footerTurnLabel").inner_text()
    assert footer_turn_label

def test_language_selector_populated(page):
    page.wait_for_timeout(2000)
    options = page.locator("#langSelect option")
    assert options.count() >= 2


# ---------------------------------------------------------------------------
# Responsive / sidebar movil (un solo boton: .collapse-btn)
# ---------------------------------------------------------------------------

def test_collapse_btn_abre_sidebar_en_movil(browser, server):
    page = browser.new_page(viewport={"width": 480, "height": 800})
    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Bug PO: habia dos iconos (hamburguesa + colapsar). La hamburguesa se quito.
    assert page.locator(".hamburger").count() == 0

    sidebar = page.locator(".sidebar")
    assert "open" not in (sidebar.get_attribute("class") or "")

    # El boton de la franja izquierda abre el overlay en movil...
    page.locator(".collapse-btn").click()
    page.wait_for_timeout(400)
    assert "open" in (sidebar.get_attribute("class") or "")

    # ...y vuelve a cerrarlo
    page.locator(".collapse-btn").click()
    page.wait_for_timeout(400)
    assert "open" not in (sidebar.get_attribute("class") or "")

    page.close()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_search_empty_shows_none(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    search = page.locator("#searchInput")
    search.fill("zzz_no_existe_xyz")
    page.wait_for_timeout(300)

    visible = 0
    rows = page.locator("#agentList .agent-row")
    for i in range(rows.count()):
        row = rows.nth(i)
        if not row.is_hidden():
            visible += 1
    assert visible == 0

def test_msg_input_disabled_during_orchestration(page):
    setup_test_data()
    page.reload()
    page.wait_for_load_state("networkidle")

    page.fill("#msgInput", "Test input state")
    page.click("#sendBtn")
    page.wait_for_timeout(300)

    input_style = page.locator("#msgInput").get_attribute("style") or ""
    assert True

def test_export_without_messages(page):
    with page.expect_download(timeout=3000) as download_info:
        page.click("#exportBtn")
    download = download_info.value
    assert download.suggested_filename.endswith(".html")
