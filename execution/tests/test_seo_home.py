"""FASE 36.3 — SEO de la home + desduplicado de URLs.

Verifica que:
- la home /web (ES y EN) sirve description, canonical, Open Graph, robots index, hreflang y JSON-LD WebSite,
- la app de chat / lleva robots noindex,
- el sitemap ya NO incluye la raiz "/" (solo /web, /web?lang=en, /preguntas y conversaciones).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api_server import app
import email_sender
from fastapi.testclient import TestClient


class TestSeoHome(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.base = email_sender.base_url()

    def test_home_es_head_completo(self):
        h = self.client.get("/web").text
        self.assertIn('name="description"', h)
        self.assertIn("No es un chatbot", h)                       # subtitulo del hero (ES)
        self.assertIn(f'rel="canonical" href="{self.base}/web"', h)
        self.assertIn('name="robots" content="index,follow"', h)
        self.assertIn('property="og:type" content="website"', h)
        self.assertIn("og-share.png", h)                           # imagen social
        self.assertIn('property="og:locale" content="es_ES"', h)
        self.assertIn('name="twitter:card"', h)
        self.assertIn('"@type":"WebSite"', h)                      # JSON-LD

    def test_home_hreflang(self):
        h = self.client.get("/web").text
        self.assertIn(f'hreflang="es" href="{self.base}/web"', h)
        self.assertIn(f'hreflang="en" href="{self.base}/web?lang=en"', h)
        self.assertIn(f'hreflang="x-default" href="{self.base}/web"', h)

    def test_home_en_canonical_y_locale(self):
        h = self.client.get("/web?lang=en").text
        self.assertIn(f'rel="canonical" href="{self.base}/web?lang=en"', h)
        self.assertIn('property="og:locale" content="en_US"', h)
        self.assertIn("It's not a chatbot", h)                     # subtitulo del hero (EN)

    def test_home_sin_metas_duplicadas(self):
        h = self.client.get("/web").text
        self.assertEqual(h.count('name="description"'), 1)
        self.assertEqual(h.count('rel="canonical"'), 1)
        self.assertEqual(h.count('property="og:type"'), 1)

    def test_chat_noindex(self):
        h = self.client.get("/").text
        self.assertIn('name="robots" content="noindex,follow"', h)

    def test_sitemap_sin_raiz(self):
        body = self.client.get("/sitemap.xml").text
        self.assertIn(f"<loc>{self.base}/web</loc>", body)
        self.assertIn(f"<loc>{self.base}/web?lang=en</loc>", body)
        self.assertNotIn(f"<loc>{self.base}/</loc>", body)         # la raiz (chat) ya no va


if __name__ == "__main__":
    unittest.main()
