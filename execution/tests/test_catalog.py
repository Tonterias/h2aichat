"""FASE 32 — Editor del catálogo de IAs en /admin."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api_server
import auth
from engine import ConversationEngine
from fastapi.testclient import TestClient


class TestCatalog(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.tmp)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        self.client = TestClient(api_server.app)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        api_server.engine = ConversationEngine()

    def test_get_default(self):
        d = self.client.get("/api/admin/catalog").json()
        self.assertTrue(any(m["id"] == "kimi" for m in d["catalog"]))
        self.assertIn("openai/gpt-5.4", d["openrouter_suggestions"])
        self.assertEqual(d["tokens_range"], [64, 4000])

    def test_save_y_releer(self):
        cat = [{"id": "qwen_plus", "label": "Qwen", "model": "qwen3.7-plus", "provider": "cloud", "role": "creativo", "max_tokens": 800},
               {"id": "kimi", "label": "Kimi", "model": "kimi-k2.6", "provider": "cloud", "role": "creativo", "max_tokens": 1500, "reasoning_effort": "none"}]
        r = self.client.post("/api/admin/catalog", json={"catalog": cat})
        self.assertEqual(r.status_code, 200)
        again = api_server.get_model_catalog(self.engine)
        self.assertEqual(len(again), 2)
        kimi = [m for m in again if m["id"] == "kimi"][0]
        self.assertEqual(kimi["reasoning_effort"], "none")
        self.assertEqual(kimi["email"], "kimi@bot.humania.local")  # auto-generado

    def test_reset(self):
        self.client.post("/api/admin/catalog", json={"catalog": [{"id": "x", "model": "m", "provider": "cloud"}]})
        self.assertEqual(len(api_server.get_model_catalog(self.engine)), 1)
        r = self.client.post("/api/admin/catalog/reset")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(api_server.get_model_catalog(self.engine)), len(api_server.MODEL_CATALOG_DEFAULT))

    def test_validacion_id_duplicado(self):
        cat = [{"id": "a", "model": "m1", "provider": "cloud"}, {"id": "a", "model": "m2", "provider": "cloud"}]
        self.assertEqual(self.client.post("/api/admin/catalog", json={"catalog": cat}).status_code, 400)

    def test_validacion_modelo_free_bloqueado(self):
        cat = [{"id": "a", "model": "qwen-free", "provider": "cloud"}]
        self.assertEqual(self.client.post("/api/admin/catalog", json={"catalog": cat}).status_code, 400)

    def test_validacion_provider_invalido(self):
        cat = [{"id": "a", "model": "m", "provider": "marte"}]
        self.assertEqual(self.client.post("/api/admin/catalog", json={"catalog": cat}).status_code, 400)

    def test_validacion_vacio(self):
        self.assertEqual(self.client.post("/api/admin/catalog", json={"catalog": []}).status_code, 400)

    def test_tokens_acotados(self):
        self.client.post("/api/admin/catalog", json={"catalog": [{"id": "a", "model": "m", "provider": "cloud", "max_tokens": 999999}]})
        self.assertEqual(api_server.get_model_catalog(self.engine)[0]["max_tokens"], 4000)

    def test_no_admin_403(self):
        token, _ = auth.register_user(self.engine, "u@t.com", "secreta123", "U", accept_terms=True, confirm_adult=True)
        r = self.client.get("/api/admin/catalog", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
