"""FASE 29 — Orquestación asíncrona: registro de tareas + endpoint de estado."""
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api_server
import auth
from engine import ConversationEngine
from fastapi.testclient import TestClient


class TestOrchRegistry(unittest.TestCase):
    def setUp(self):
        with api_server._orch_lock:
            api_server._orch_tasks.clear()

    def test_register_progress_finish(self):
        api_server._orch_register("t1", 3, 5)
        self.assertTrue(api_server._orch_is_running("t1"))
        self.assertEqual(api_server._orch_count_running(), 1)
        api_server._orch_set_progress("t1", 2, 3, 5)
        s = api_server._orch_get("t1")
        self.assertEqual(s["round"], 2)
        self.assertEqual(s["total_rounds"], 3)
        self.assertEqual(s["status"], "running")
        api_server._orch_finish("t1", "done", {"rounds": 3, "budget_reached": False})
        self.assertFalse(api_server._orch_is_running("t1"))
        self.assertEqual(api_server._orch_count_running(), 0)
        self.assertEqual(api_server._orch_get("t1")["status"], "done")

    def test_cap_cuenta_solo_running(self):
        api_server._orch_register("a", 1, 1)
        api_server._orch_register("b", 1, 1)
        api_server._orch_finish("b", "done")
        self.assertEqual(api_server._orch_count_running(), 1)  # solo 'a'

    def test_staleness_heartbeat(self):
        api_server._orch_register("t2", 1, 1)
        with api_server._orch_lock:
            api_server._orch_tasks["t2"]["updated_at"] = time.time() - (api_server.ORCH_STALE_SECONDS + 10)
        self.assertEqual(api_server._orch_get("t2")["status"], "stalled")

    def test_get_none(self):
        self.assertIsNone(api_server._orch_get("nope"))


class TestOrchStatusEndpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.tmp)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        self.client = TestClient(api_server.app)
        with api_server._orch_lock:
            api_server._orch_tasks.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        api_server.engine = ConversationEngine()

    def test_status_none(self):
        r = self.client.get("/api/orchestration-status?thread_id=x")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "none")

    def test_status_refleja_running_y_done(self):
        thread = auth.scope_thread(dict(auth.DEV_USER), "deb")
        api_server._orch_register(thread, 2, 4)
        api_server._orch_set_progress(thread, 1, 2, 4)
        r = self.client.get("/api/orchestration-status?thread_id=deb").json()
        self.assertEqual(r["status"], "running")
        self.assertEqual(r["round"], 1)
        self.assertEqual(r["total_rounds"], 2)
        api_server._orch_finish(thread, "done", {"rounds": 2, "budget_reached": True})
        r2 = self.client.get("/api/orchestration-status?thread_id=deb").json()
        self.assertEqual(r2["status"], "done")
        self.assertTrue(r2["budget_reached"])

    def test_orchestrate_sync_via_testclient(self):
        # Desde TestClient el handler corre SINCRONO -> devuelve el resultado, no {started}
        r = self.client.post("/orchestrate?rounds=0", json={
            "recipient_id": "qwen_plus", "body": "hola", "sender_id": "miguel", "thread_id": "s1"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("started", r.json())  # sincrono: no es la respuesta async


if __name__ == "__main__":
    unittest.main()
