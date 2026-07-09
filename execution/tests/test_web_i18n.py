"""FASE 33.1 — Tests del motor de render i18n de la landing (T1)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import i18n


class TestWebI18n(unittest.TestCase):
    def test_sustituye_claves_presentes(self):
        html = "<h1>{{web.hero.titulo}}</h1><p>{{web.hero.sub}}</p>"
        out = i18n._substitute_web(html, {"web.hero.titulo": "Hola", "web.hero.sub": "Mundo"})
        self.assertIn("<h1>Hola</h1>", out)
        self.assertIn("<p>Mundo</p>", out)
        self.assertNotIn("{{", out)  # no quedan tokens sin sustituir

    def test_clave_ausente_muestra_marcador(self):  # criterio 5
        out = i18n._substitute_web("<p>{{web.x.falta}}</p>", {})
        self.assertEqual(out, "<p>⟦falta: web.x.falta⟧</p>")

    def test_clave_vacia_tambien_marca(self):  # vacío = se trata como ausente
        out = i18n._substitute_web("<p>{{web.x.vacia}}</p>", {"web.x.vacia": ""})
        self.assertIn("⟦falta: web.x.vacia⟧", out)

    def test_solo_toca_tokens_web(self):
        # no debe tocar otros {{...}} que no empiecen por web. (p. ej. plantillas JS)
        html = "<p>{{web.ok}}</p><p>{{noweb.x}}</p>"
        out = i18n._substitute_web(html, {"web.ok": "Sí"})
        self.assertIn("<p>Sí</p>", out)
        self.assertIn("{{noweb.x}}", out)  # intacto

    def test_render_web_usa_el_idioma(self):
        i18n.TRANSLATIONS["es"]["web._t_test"] = "Hola"
        i18n.TRANSLATIONS["en"]["web._t_test"] = "Hello"
        try:
            self.assertIn("Hola", i18n.render_web("{{web._t_test}}", "es"))
            self.assertIn("Hello", i18n.render_web("{{web._t_test}}", "en"))
        finally:
            del i18n.TRANSLATIONS["es"]["web._t_test"]
            del i18n.TRANSLATIONS["en"]["web._t_test"]


    def test_resolve_web_lang(self):  # T2
        self.assertEqual(i18n.resolve_web_lang("en", None), "en")
        self.assertEqual(i18n.resolve_web_lang(None, "en"), "en")   # cae a la cookie
        self.assertEqual(i18n.resolve_web_lang("xx", None), "es")   # no disponible -> es
        self.assertEqual(i18n.resolve_web_lang(None, None), "es")   # por defecto
        self.assertEqual(i18n.resolve_web_lang("EN", None), "en")   # case-insensitive
        self.assertEqual(i18n.resolve_web_lang("es-ES", None), "es")  # prefijo

    def test_resolve_web_lang_accept_language(self):  # AC-9: deteccion por navegador
        # Sin ?lang ni cookie -> se usa el idioma del navegador
        self.assertEqual(i18n.resolve_web_lang(None, None, "en-GB,en;q=0.9,es;q=0.8"), "en")
        self.assertEqual(i18n.resolve_web_lang(None, None, "es-ES,es;q=0.9"), "es")
        # Idioma del navegador NO disponible (frances) -> default es
        self.assertEqual(i18n.resolve_web_lang(None, None, "fr-FR,fr;q=0.9"), "es")
        # Respeta q=: el de mayor q gana aunque vaya despues
        self.assertEqual(i18n.resolve_web_lang(None, None, "fr;q=0.9,en;q=0.95"), "en")
        # La eleccion explicita (?lang) y la cookie SIEMPRE mandan sobre el navegador
        self.assertEqual(i18n.resolve_web_lang("es", None, "en-GB,en;q=0.9"), "es")
        self.assertEqual(i18n.resolve_web_lang(None, "es", "en-GB,en;q=0.9"), "es")
        # Cabecera vacia/ausente -> default es
        self.assertEqual(i18n.resolve_web_lang(None, None, ""), "es")
        self.assertEqual(i18n.resolve_web_lang(None, None, None), "es")


class TestWebRoute(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import api_server
        self.client = TestClient(api_server.app)

    def test_web_es_renderiza_hero_desde_claves(self):  # T3 + criterios 1, 2
        r = self.client.get("/web")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Donde las IAs conversan", r.text)   # hero ES desde claves
        self.assertNotIn("{{web.", r.text)                  # no quedan tokens sin sustituir
        self.assertNotIn("⟦falta:", r.text)                # ningún marcador en ES

    def test_web_en_cambia_idioma(self):  # T2 + criterio 3
        r = self.client.get("/web?lang=en")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Where AIs talk to each other", r.text)  # hero en EN
        self.assertIn('lang="en"', r.text)                      # <html lang="en">
        self.assertNotIn("{{web.", r.text)

    def test_galeria_es_y_en_son_listas_distintas(self):  # T5 criterio 7
        import i18n
        ges, gen = i18n.render_gallery("es"), i18n.render_gallery("en")
        self.assertIn("/conversations/en/", gen)       # EN apunta a subcarpeta en/
        self.assertNotIn("/conversations/en/", ges)    # ES no usa en/
        self.assertNotEqual(ges, gen)                   # datos por idioma: listas distintas

    def test_sirve_conversacion_en_subcarpeta(self):  # T5b route subcarpeta
        r = self.client.get("/conversations/en/h2aichat_user_1_PublicSpeaking_2026-06-19_221750.html")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
