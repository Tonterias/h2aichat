"""FASE 36.2 — Tests del EMBED (T5-T7): render sin chrome, enmarcado permitido solo en
embed, noindex, y codigo <iframe> para incrustar."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import share_page

CURADA = "h2aichat_ConcienciaArtificial_2026-06-19.html"

_SNAP = {
    "messages": [
        {"sender": "miguel", "recipient": "qwen", "body": "¿Qué es la conciencia?",
         "timestamp": "2026-06-19T15:30:11"},
        {"sender": "qwen", "recipient": "miguel", "body": "Una función.",
         "timestamp": "2026-06-19T15:30:36"},
    ],
    "mod_sender": "miguel", "count": 2, "lang": "es",
}


class TestSharePageEmbed(unittest.TestCase):
    def test_embed_sin_barra_y_noindex(self):  # criterios 6,7
        out = share_page.render_shared_page(_SNAP, "es", "http://x", "tok", embed=True)
        self.assertIn('name="robots"', out)
        self.assertIn("noindex", out)
        self.assertNotIn('class="sharebar"', out)      # sin barra
        self.assertNotIn("h2aiEmbedToggle", out)        # sin boton insertar
        self.assertIn("&#9888;", out)                    # aviso AI Act presente

    def test_normal_lleva_boton_y_codigo(self):  # criterio 8
        out = share_page.render_shared_page(_SNAP, "es", "http://x", "tok", embed=False)
        self.assertIn('class="sharebar"', out)
        self.assertIn("h2aiEmbedToggle", out)
        self.assertIn("?embed=1", out)                   # el iframe apunta al modo embed
        self.assertNotIn("noindex", out)


class TestConversationEmbedRoutes(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import api_server
        self.client = TestClient(api_server.app)

    def test_conversacion_normal_boton_y_frame_deny(self):  # criterio 8 + seguridad
        r = self.client.get("/conversations/" + CURADA)
        self.assertEqual(r.status_code, 200)
        self.assertIn("h2aiEmbedToggle", r.text)                 # boton Insertar
        self.assertIn("?embed=1", r.text)
        self.assertEqual(r.headers.get("x-frame-options"), "DENY")
        self.assertIn("frame-ancestors 'none'", r.headers.get("content-security-policy", ""))

    def test_conversacion_embed_desnuda_y_framable(self):  # criterios 6,7
        r = self.client.get("/conversations/" + CURADA + "?embed=1")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("h2aiVoteUp", r.text)                   # sin barra/votos
        self.assertIn("H2AI Chat", r.text)                       # pie de vuelta
        self.assertIn("noindex", r.text)
        # enmarcado permitido SOLO aqui: sin X-Frame-Options DENY y CSP frame-ancestors *
        self.assertIsNone(r.headers.get("x-frame-options"))
        self.assertIn("frame-ancestors *", r.headers.get("content-security-policy", ""))


if __name__ == "__main__":
    unittest.main()
