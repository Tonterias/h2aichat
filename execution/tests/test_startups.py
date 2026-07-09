"""FASE 23 — Tests del monitor de arranques del sistema (23.1c)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine
import auth
import api_server
from api_server import app
from fastapi.testclient import TestClient


class TestStartups(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        api_server.engine = ConversationEngine()

    def test_record_y_list(self):
        auth.record_startup(self.engine)
        rows = auth.list_startups(self.engine)
        self.assertEqual(len(rows), 1)
        self.assertIn("started_at", rows[0])

    def test_orden_mas_reciente_primero(self):
        auth.record_startup(self.engine, version="1")
        auth.record_startup(self.engine, version="2")
        rows = auth.list_startups(self.engine)
        self.assertEqual(rows[0]["version"], "2")

    def test_retencion_conserva_solo_keep(self):
        for _ in range(5):
            auth.record_startup(self.engine, keep=3)
        self.assertEqual(len(auth.list_startups(self.engine, limit=100)), 3)

    def test_last_startup_en_stats(self):
        auth.record_startup(self.engine)
        stats = auth.admin_stats(self.engine)
        self.assertIn("last_startup", stats)
        self.assertTrue(stats["last_startup"])

    def test_endpoint_startups(self):
        auth.record_startup(self.engine)
        r = self.client.get("/api/admin/startups")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()["startups"]), 1)

    def test_endpoint_startups_no_admin_403(self):
        token, _ = auth.register_user(self.engine, "x@test.com", "secreta123", "X",
                                      accept_terms=True, confirm_adult=True)
        r = self.client.get("/api/admin/startups", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 403)


class TestOrchTimes(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        api_server.engine = ConversationEngine()

    TIEMPOS = {"A_wall_ms": 90000, "B_llm_ms": 75000, "C_lock_ms": 3,
               "D_delays_ms": 12000, "E_overhead_ms": 2997}

    def test_record_y_list_con_media(self):
        auth.record_orch_time(self.engine, 0, "user_0_bola1", 2, 3, self.TIEMPOS, 6840)
        out = auth.list_orch_times(self.engine)
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(out["items"][0]["wall_ms"], 90000)
        self.assertEqual(out["avg"]["n"], 1)
        self.assertAlmostEqual(out["avg"]["llm"], 75000)

    def test_retencion(self):
        for i in range(4):
            auth.record_orch_time(self.engine, 0, "t", 1, 3, self.TIEMPOS, 0, keep=2)
        self.assertEqual(len(auth.list_orch_times(self.engine, limit=100)["items"]), 2)

    def test_endpoint(self):
        auth.record_orch_time(self.engine, 0, "t", 1, 3, self.TIEMPOS, 0)
        r = self.client.get("/api/admin/orch-times")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()["items"]), 1)

    def test_endpoint_no_admin_403(self):
        token, _ = auth.register_user(self.engine, "y@test.com", "secreta123", "Y",
                                      accept_terms=True, confirm_adult=True)
        r = self.client.get("/api/admin/orch-times", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 403)

    def test_orchestrate_persiste_los_tiempos(self):
        # rounds=0 (sin LLM): la orquestacion igual persiste su desglose A-E
        r = self.client.post("/orchestrate?rounds=0", json={
            "recipient_id": "qwen_plus", "body": "hola", "sender_id": "miguel", "thread_id": "t1"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("tiempos", r.json())
        self.assertGreaterEqual(len(auth.list_orch_times(self.engine)["items"]), 1)

    def test_recipient_se_redirige_a_bot_activo(self):
        # FASE 26: si el moderador manda la bola a un bot que NO esta en los bots activos
        # (caso: config OpenRouter -> free cae a otro set, pero el front manda a qwen_plus
        # que sigue registrado), debe redirigir a un bot activo. Si no -> todos skip -> 0 tokens.
        cfg = {"qwen": {"provider": "cloud", "model": "qwen3.5-plus", "role": "creativo", "email": "q@b", "max_tokens": 300},
               "minimax": {"provider": "cloud", "model": "minimax-m2.7", "role": "estratega", "email": "m@b", "max_tokens": 300},
               "deepseek": {"provider": "cloud", "model": "deepseek-v4-flash", "role": "analista", "email": "d@b", "max_tokens": 300}}
        self.engine.set_setting("bots_config", json.dumps(cfg))
        self.client.post("/orchestrate?rounds=0", json={  # monta miguel + qwen/minimax/deepseek
            "recipient_id": "qwen", "body": "setup", "sender_id": "miguel", "thread_id": "tr"})
        self.engine.register_participant("qwen_plus", "creativo", "bot", "qp@b", provider="cloud")
        r = self.client.post("/orchestrate?rounds=0", json={  # el front manda a qwen_plus (no activo)
            "recipient_id": "qwen_plus", "body": "hi", "sender_id": "miguel", "thread_id": "tr"})
        self.assertEqual(r.status_code, 200)
        redirects = [e for e in r.json()["trace"] if e.get("action") == "redirect_recipient"]
        self.assertTrue(redirects, "deberia haber redirigido el recipient a un bot activo")
        self.assertIn(redirects[0]["to"], ["qwen", "minimax", "deepseek"])

    def test_orquestacion_ignora_bots_fantasma(self):
        # FASE 26: un bot registrado que NO esta en bots_config (fantasma de un perfil viejo)
        # no debe entrar en la conversacion. El orch_time persistido debe contar solo los 3
        # configurados (qwen_plus, minimax, deepseek_flash), no el fantasma.
        # 1a orquestacion: monta miguel + los 3 bots configurados (como en PROD)
        self.client.post("/orchestrate?rounds=0", json={
            "recipient_id": "qwen_plus", "body": "setup", "sender_id": "miguel", "thread_id": "tg"})
        # ahora aparece un bot fantasma (de un perfil viejo)
        self.engine.register_participant("ghostbot", "x", "bot", "g@t", provider="cloud")
        r = self.client.post("/orchestrate?rounds=0", json={
            "recipient_id": "qwen_plus", "body": "hi", "sender_id": "miguel", "thread_id": "tg"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(auth.list_orch_times(self.engine)["items"][0]["bots"], 3)

    def test_presupuesto_corta_antes_de_504(self):
        # FASE 26: con presupuesto agotado (0s) la orquestacion cierra LIMPIA (200) antes de
        # llamar a ningun bot -> nunca llega a los 300s de nginx. Sin LLM, sin coste.
        self.engine.set_setting("orchestrate_max_seconds", "0")
        r = self.client.post("/orchestrate?rounds=2", json={
            "recipient_id": "qwen_plus", "body": "hola", "sender_id": "miguel", "thread_id": "tb"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d.get("budget_reached"))
        self.assertEqual(len(d.get("responses", [])), 0)


class TestNormalizeGhostBots(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        api_server.engine = ConversationEngine()

    def test_apaga_fantasmas_y_respeta_catalogo(self):
        # fantasmas del viejo perfil (ids fuera del catalogo) + un bot del catalogo
        self.engine.register_participant("qwen", "creativo", "bot", "qwen@b", provider="cloud")
        self.engine.register_participant("deepseek", "analista", "bot", "deepseek@b", provider="cloud")
        self.engine.register_participant("kimi", "creativo", "bot", "kimi@b", provider="cloud")
        apagados = api_server.normalize_ghost_bots(self.engine)
        parts = self.engine.read_state()["participants"]
        self.assertEqual(set(apagados), {"qwen", "deepseek"})
        self.assertEqual(parts["qwen"]["status"], "inactive")
        self.assertEqual(parts["deepseek"]["status"], "inactive")
        self.assertEqual(parts["kimi"]["status"], "active")   # del catalogo: intacto

    def test_no_toca_humanos_ni_es_destructivo(self):
        self.engine.register_participant("miguel", "moderador", "human", "m@b")
        self.engine.register_participant("qwen", "creativo", "bot", "qwen@b", provider="cloud")
        api_server.normalize_ghost_bots(self.engine)
        parts = self.engine.read_state()["participants"]
        self.assertIn("qwen", parts)        # NO se borra (reversible)
        self.assertIn("miguel", parts)
        self.assertEqual(parts["miguel"]["type"], "human")


if __name__ == "__main__":
    unittest.main()
