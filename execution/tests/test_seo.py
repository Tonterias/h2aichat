"""FASE 36 — Tests de SEO de las conversaciones publicadas.

Cubre: inyeccion de <title>/description/canonical/<h1>/JSON-LD en las curadas, noindex en
las no curadas, hreflang en pares reales (fundacional), y las rutas sitemap.xml/robots.txt.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import seo
import i18n

# Ficheros concretos verificados en conversations/ (T0).
CURADA_ES = "h2aichat_ConcienciaArtificial_2026-06-19.html"          # -> "Conciencia artificial"
CURADA_EN = "en/h2aichat_user_1_PublicSpeaking_2026-06-19_221750.html"  # -> "Public speaking"
FUNDACIONAL = "Fundacional_ContratoDigital_20260516.html"           # par de traduccion literal
NO_CURADA = "SciFi_Peliculas_20260613.html"                         # servida pero fuera de la galeria


class TestSeoUnit(unittest.TestCase):
    def test_titulo_por_idioma(self):  # D3 / criterio 1
        self.assertEqual(seo.seo_title("Conciencia artificial", "es"),
                         "Conciencia artificial — Diálogo entre Humanos e IAs · H2AI Chat")
        self.assertEqual(seo.seo_title("Public speaking", "en"),
                         "Public speaking — Dialogue between humans and AIs · H2AI Chat")

    def test_iso_date(self):
        self.assertEqual(seo._iso_date("19/06/2026"), "2026-06-19")
        self.assertEqual(seo._iso_date(""), "")
        self.assertEqual(seo._iso_date("Mayo 2026"), "")

    def _sample(self):
        return ('<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">'
                '<title>H2AI Chat - Slug</title>'
                '<meta property="og:title" content="viejo > roto">'
                '<meta name="twitter:description" content="viejo">'
                '</head><body><header><h1>H2AI Chat</h1><p>Hilo</p></header></body></html>')

    def test_inject_seo_reescribe_todo(self):  # criterios 1,2,3,4,5,6
        meta = {"label": "Conciencia artificial", "desc": "Definir la conciencia artificial.",
                "lang": "es", "section": "Filosofía", "meta": "19/06/2026"}
        out = seo.inject_seo(self._sample(), meta,
                             "http://x/conversations/es/c.html", "http://x/static/og-share.png")
        self.assertIn("<title>Conciencia artificial — Diálogo entre Humanos e IAs · H2AI Chat</title>", out)
        self.assertIn('<meta name="description" content="Definir la conciencia artificial.">', out)
        self.assertIn('<link rel="canonical" href="http://x/conversations/es/c.html">', out)
        self.assertIn("<h1>Conciencia artificial</h1>", out)
        self.assertIn('application/ld+json', out)
        self.assertIn('"datePublished":"2026-06-19"', out)
        # og viejos (incluido el que llevaba '>' dentro) eliminados: solo queda 1 og:title
        self.assertEqual(out.count('property="og:title"'), 1)
        self.assertNotIn("viejo", out)
        self.assertNotIn("H2AI Chat - Slug", out)

    def test_inject_seo_idempotente(self):
        meta = {"label": "X", "desc": "Y", "lang": "es", "meta": ""}
        once = seo.inject_seo(self._sample(), meta, "http://x/c", "http://x/img")
        twice = seo.inject_seo(once, meta, "http://x/c", "http://x/img")
        self.assertEqual(twice.count('<meta name="description"'), 1)
        self.assertEqual(twice.count('rel="canonical"'), 1)

    def test_hreflang_solo_con_alternates(self):  # T6
        meta = {"label": "X", "desc": "Y", "lang": "es", "meta": ""}
        alts = [("es", "http://x/es"), ("en", "http://x/en"), ("x-default", "http://x/es")]
        out = seo.inject_seo(self._sample(), meta, "http://x/c", "http://x/img", alternates=alts)
        self.assertIn('hreflang="en"', out)
        self.assertIn('hreflang="x-default"', out)

    def test_inject_noindex(self):  # criterio 8
        out = seo.inject_noindex("<html><head></head><body></body></html>")
        self.assertIn('<meta name="robots" content="noindex,follow">', out)
        # idempotente
        self.assertEqual(seo.inject_noindex(out).count("noindex"), 1)


class TestSeoIndex(unittest.TestCase):
    def test_indice_desde_galeria(self):  # criterio 1,2 (fuente unica)
        idx = i18n.GALLERY_SEO_INDEX
        self.assertIn("es/" + CURADA_ES, idx)
        self.assertEqual(idx["es/" + CURADA_ES]["label"], "Conciencia artificial")
        # la fundacional (fuera de la rejilla) tambien es curada
        self.assertIn("es/" + FUNDACIONAL, idx)
        self.assertIn("en/" + FUNDACIONAL, idx)
        # una no curada NO esta
        self.assertNotIn("es/" + NO_CURADA, idx)

    def test_hreflang_pairs_solo_fundacional(self):
        pairs = i18n.SEO_HREFLANG_PAIRS
        self.assertEqual(pairs["es/" + FUNDACIONAL], "en/" + FUNDACIONAL)
        # las conversaciones normales NO tienen par (no son traducciones)
        self.assertNotIn("es/" + CURADA_ES, pairs)


class TestSeoRoutes(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import api_server
        self.client = TestClient(api_server.app)

    def test_conversacion_curada_indexable(self):  # criterios 1,2,3,4,6
        r = self.client.get("/conversations/" + CURADA_ES)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Conciencia artificial — Diálogo entre Humanos e IAs · H2AI Chat", r.text)
        self.assertIn('<meta name="description"', r.text)
        self.assertIn('rel="canonical"', r.text)
        self.assertIn("<h1>Conciencia artificial</h1>", r.text)
        self.assertIn("application/ld+json", r.text)
        self.assertNotIn("noindex", r.text)

    def test_conversacion_no_curada_noindex(self):  # criterio 8
        r = self.client.get("/conversations/" + NO_CURADA)
        self.assertEqual(r.status_code, 200)
        self.assertIn('content="noindex,follow"', r.text)

    def test_fundacional_hreflang(self):  # T6
        r = self.client.get("/conversations/" + FUNDACIONAL)
        self.assertEqual(r.status_code, 200)
        self.assertIn('hreflang="en"', r.text)
        self.assertIn('hreflang="x-default"', r.text)
        self.assertNotIn("noindex", r.text)

    def test_robots_txt(self):  # criterio 7
        r = self.client.get("/robots.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn("User-agent: *", r.text)
        self.assertIn("Sitemap:", r.text)
        self.assertIn("/sitemap.xml", r.text)

    def test_sitemap_xml(self):  # criterios 7,9
        r = self.client.get("/sitemap.xml")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/xml", r.headers.get("content-type", ""))
        self.assertIn("<urlset", r.text)
        self.assertIn("/web", r.text)
        self.assertIn("/conversations/es/" + CURADA_ES, r.text)
        # una no curada NO aparece en el sitemap
        self.assertNotIn(NO_CURADA, r.text)


if __name__ == "__main__":
    unittest.main()
