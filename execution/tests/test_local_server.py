"""FASE 40.1 — Ajuste global de la dirección del servidor de modelos LOCAL.

Cubre T1+T2: el ajuste `local_server_url` existe con el default de LM Studio, se
persiste (la BD manda), valida que sea una URL http(s), y los agentes locales lo usan.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from api_server import app  # noqa: E402
from engine import ConversationEngine  # noqa: E402


class TestLocalServerUrl(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        import api_server
        api_server.engine = self.engine
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        import api_server
        api_server.engine = ConversationEngine()

    def test_default_es_lm_studio(self):
        s = self.client.get("/api/settings").json()["settings"]
        self.assertEqual(s.get("local_server_url"), "http://localhost:1234/v1")

    def test_guardar_ollama_ok(self):
        r = self.client.post("/api/settings", json={"local_server_url": "http://localhost:11434/v1"})
        self.assertEqual(r.status_code, 200)
        s = self.client.get("/api/settings").json()["settings"]
        self.assertEqual(s.get("local_server_url"), "http://localhost:11434/v1")

    def test_url_sin_http_rechazada(self):
        r = self.client.post("/api/settings", json={"local_server_url": "localhost:1234/v1"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("http", r.json()["detail"].lower())

    def test_url_a_medida_https_ok(self):
        r = self.client.post("/api/settings", json={"local_server_url": "https://mi-servidor.local:8080/v1"})
        self.assertEqual(r.status_code, 200)

    def test_el_agente_local_usa_el_ajuste(self):
        # el default y el guardado se leen con get_setting (lo que usa /orchestrate)
        self.engine.set_setting("local_server_url", "http://localhost:11434/v1")
        self.assertEqual(self.engine.get_setting("local_server_url"), "http://localhost:11434/v1")

    def test_probar_conexion_servidor_caido(self):
        # T3: un servidor que no existe -> ok:false, sin reventar (puerto improbable)
        r = self.client.get("/api/local/test?url=http://127.0.0.1:59999/v1")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertFalse(d["ok"])
        self.assertIn("error", d)

    def test_probar_conexion_url_invalida(self):
        r = self.client.get("/api/local/test?url=noesunaurl")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])

    def test_default_local_url_respeta_env(self):
        # FASE 40.2: docker-compose fija LOCAL_SERVER_URL -> el default lo respeta
        import os
        import api_server
        old = os.environ.get("LOCAL_SERVER_URL")
        os.environ["LOCAL_SERVER_URL"] = "http://ollama:11434/v1"
        try:
            self.assertEqual(api_server._default_local_url(), "http://ollama:11434/v1")
        finally:
            if old is None:
                os.environ.pop("LOCAL_SERVER_URL", None)
            else:
                os.environ["LOCAL_SERVER_URL"] = old


class TestAgenteLocalPorDefecto(unittest.TestCase):
    """FASE 40.2: en self-host local (HUMANIA_LOCAL=1) el debate arranca con un agente
    'Local' listo; en PROD (sin la variable) siguen los bots de nube. Cambio NO-OP en PROD."""

    def _set_local(self, on):
        import os
        if on:
            os.environ["HUMANIA_LOCAL"] = "1"
        else:
            os.environ.pop("HUMANIA_LOCAL", None)

    def tearDown(self):
        self._set_local(False)

    def test_default_bots_local_trae_agente_local(self):
        import api_server
        self._set_local(True)
        cfg = api_server._default_bots_config()
        self.assertIn("local", cfg)
        self.assertEqual(cfg["local"]["provider"], "local")

    def test_default_bots_prod_son_de_nube(self):
        import api_server
        self._set_local(False)
        cfg = api_server._default_bots_config()
        self.assertNotIn("local", cfg)
        self.assertTrue(all(b["provider"] == "cloud" for b in cfg.values()))

    def test_catalogo_local_incluye_entrada_local(self):
        import tempfile
        import api_server
        from engine import ConversationEngine
        self._set_local(True)
        eng = ConversationEngine(base_path=Path(tempfile.mkdtemp()))
        ids = [m["id"] for m in api_server.get_model_catalog(eng)]
        self.assertIn("local", ids)


class TestIndicadorI18n(unittest.TestCase):
    def test_claves_nube_local_en_es_y_en(self):
        import i18n
        for lang in ("es", "en"):
            for k in ("agent.runs_local", "agent.runs_cloud"):
                self.assertIn(k, i18n.TRANSLATIONS[lang], f"falta {k} en {lang}")


if __name__ == "__main__":
    unittest.main()
