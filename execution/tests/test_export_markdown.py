"""FASE 38.1 — Exportar la conversación a Markdown desde el chat.

- Guarda de i18n (corre en CI): las claves del menú y del pie existen en ES y EN.
- Test de navegador (Playwright, se salta en CI sin binario): el botón de descarga abre
  un menú HTML/Markdown y "Markdown" descarga un .md con la estructura acordada
  (título, aviso de IA, cabecera por mensaje, cuerpo intacto, pie con el visor recomendado).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import i18n


class TestI18nExportKeys(unittest.TestCase):
    def test_claves_export_en_es_y_en(self):
        for lang in ("es", "en"):
            for k in ("export.as_html", "export.as_markdown", "export.md_viewer"):
                self.assertIn(k, i18n.TRANSLATIONS[lang], f"falta {k} en {lang}")


# ── Test de navegador (fixtures de conftest: browser + server). Se salta en CI. ──
MSGS = [
    {"sender": "dev@local", "recipient": "qwen", "body": "¿Qué opináis?",
     "timestamp": "2026-07-07T18:00:05+00:00"},
    {"sender": "qwen", "recipient": "kimi", "body": "(qwen) Creo que **sí**.\n- uno\n- dos",
     "timestamp": "2026-07-07T18:00:10+00:00"},
]


def test_export_menu_y_markdown(browser, server):
    pg = browser.new_page()
    pg.add_init_script("window.MY_MOD_ID='dev@local';window.MY_NAME='dev';")
    pg.goto(server, wait_until="load")
    pg.wait_for_timeout(1000)
    # inyecta mensajes de prueba en el estado del chat
    pg.evaluate("(m)=>{ allMessages=m; currentThread='user_9_Test'; currentLang='es'; }", MSGS)

    # el botón de descarga abre el menú con las dos opciones
    pg.click("#exportBtn")
    pg.wait_for_selector("#exportMenuPopup")
    menu = pg.inner_text("#exportMenuPopup")
    assert "HTML" in menu and "Markdown" in menu

    # "Markdown" descarga un .md
    with pg.expect_download() as dl:
        pg.click("#exportMenuPopup >> text=Markdown")
    d = dl.value
    assert d.suggested_filename.endswith(".md")
    path = os.path.join(tempfile.gettempdir(), "h2ai_export_test.md")
    d.save_as(path)
    md = Path(path).read_text(encoding="utf-8")

    # estructura acordada
    assert md.startswith("# H2AI Chat")
    assert "Contenido generado por IA" in md            # aviso de IA
    assert "### Moderador" in md                          # cabecera del moderador
    assert "Qwen → Kimi" in md                            # cabecera de agente
    assert "**sí**" in md and "- uno" in md               # cuerpo markdown intacto
    assert "github.com/marktext/marktext" in md           # pie con el visor recomendado
    import re
    assert re.search(r"`\d\d?:\d\d", md)                   # la hora va en `codigo` (evita el rojo del :MM: como emoji)
    pg.close()


if __name__ == "__main__":
    unittest.main()
