"""FASE 28 — Tests del módulo de métricas de sistema y los contadores en vuelo."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import system_metrics
import api_server


class TestSystemMetrics(unittest.TestCase):
    def test_read_devuelve_claves_y_disco(self):
        m = system_metrics.read_system_metrics()
        for k in ("ram_pct", "cpu_pct", "disk_used_pct", "disk_free_pct", "load1", "cpu_count"):
            self.assertIn(k, m)
        # el disco SIEMPRE se puede medir (stdlib), aunque no haya psutil
        self.assertIsNotNone(m["disk_used_pct"])
        self.assertGreaterEqual(m["disk_used_pct"], 0)
        self.assertLessEqual(m["disk_used_pct"], 100)

    def test_disco_libre_complementa_usado(self):
        u = system_metrics.disk_used_pct()
        f = system_metrics.disk_free_pct()
        self.assertAlmostEqual(u + f, 100.0, delta=0.2)

    def test_capacidad_es_el_peor_submedidor(self):
        metrics = {"ram_pct": 40, "cpu_pct": 90, "disk_used_pct": 30, "cpu_count": 1}
        cap = system_metrics.compute_capacity(metrics, inflight_orch=0, orch_cap=8)
        self.assertEqual(cap["capacity_pct"], 90.0)
        self.assertEqual(cap["worst"], "cpu")

    def test_capacidad_ignora_none(self):
        metrics = {"ram_pct": None, "cpu_pct": None, "disk_used_pct": 55, "cpu_count": 1}
        cap = system_metrics.compute_capacity(metrics, inflight_orch=0, orch_cap=8)
        self.assertEqual(cap["capacity_pct"], 55.0)
        self.assertEqual(cap["worst"], "disk")

    def test_capacidad_satura_por_orquestaciones(self):
        metrics = {"ram_pct": 10, "disk_used_pct": 10, "cpu_count": 1}
        cap = system_metrics.compute_capacity(metrics, inflight_orch=8, orch_cap=8)
        self.assertEqual(cap["sub"]["orch"], 100.0)
        self.assertEqual(cap["capacity_pct"], 100.0)

    def test_capacidad_sin_datos_es_cero(self):
        cap = system_metrics.compute_capacity({}, inflight_orch=0, orch_cap=0)
        self.assertEqual(cap["capacity_pct"], 0.0)


class TestInflightCounters(unittest.TestCase):
    def setUp(self):
        # reset de los contadores entre tests
        with api_server._inflight_lock:
            api_server._inflight["orch"] = 0
            api_server._inflight["requests"] = 0
            api_server._inflight_peak["orch"] = 0
            api_server._inflight_peak["requests"] = 0

    def test_orch_sube_y_baja_con_pico(self):
        api_server._orch_enter()
        api_server._orch_enter()
        cur, peak = api_server.get_inflight()
        self.assertEqual(cur["orch"], 2)
        self.assertEqual(peak["orch"], 2)
        api_server._orch_exit()
        cur, peak = api_server.get_inflight()
        self.assertEqual(cur["orch"], 1)
        self.assertEqual(peak["orch"], 2)  # el pico se conserva

    def test_requests_no_baja_de_cero(self):
        api_server._req_exit()  # sin entrar antes
        cur, _ = api_server.get_inflight()
        self.assertEqual(cur["requests"], 0)


class TestHealthData(unittest.TestCase):
    def setUp(self):
        import tempfile, shutil
        from engine import ConversationEngine
        import auth
        self.tmp = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.tmp)
        auth.init_auth_tables(self.engine)
        self.auth = auth
        self._shutil = shutil

    def tearDown(self):
        self._shutil.rmtree(self.tmp, ignore_errors=True)

    def test_record_list_y_pico(self):
        self.auth.record_system_health(self.engine, {
            "ram_pct": 40, "cpu_pct": 30, "disk_used_pct": 20, "disk_free_pct": 80,
            "inflight_orch": 1, "inflight_requests": 3, "capacity_pct": 40, "worst": "ram"})
        self.auth.record_system_health(self.engine, {
            "ram_pct": 95, "cpu_pct": 88, "disk_used_pct": 22, "disk_free_pct": 78,
            "inflight_orch": 6, "inflight_requests": 10, "capacity_pct": 95, "worst": "ram"})
        hist = self.auth.list_system_health(self.engine, hours=24)
        self.assertEqual(len(hist["items"]), 2)
        peak = self.auth.get_system_peak(self.engine)
        # el pico guarda el máximo CON SUS CONDICIONES (matiz del PO)
        self.assertEqual(peak["capacity_pct"], 95)
        self.assertEqual(peak["inflight_orch"], 6)
        self.assertEqual(peak["inflight_requests"], 10)
        self.assertEqual(peak["ram_pct"], 95)


class TestHealthEndpoints(unittest.TestCase):
    def setUp(self):
        import tempfile, shutil
        from engine import ConversationEngine
        import auth
        from fastapi.testclient import TestClient
        self.tmp = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.tmp)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        self.client = TestClient(api_server.app)
        self._shutil = shutil

    def tearDown(self):
        self._shutil.rmtree(self.tmp, ignore_errors=True)
        from engine import ConversationEngine
        api_server.engine = ConversationEngine()

    def test_health_live(self):
        r = self.client.get("/api/admin/health")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIn("capacity_pct", d["sample"])
        self.assertIsNotNone(d["sample"]["disk_used_pct"])  # disco siempre
        self.assertEqual(d["thresholds"]["disk_used_pct"], 75)

    def test_health_record_y_history(self):
        self.client.get("/api/admin/health?record=1")
        h = self.client.get("/api/admin/health/history?hours=24").json()
        self.assertGreaterEqual(len(h["items"]), 1)

    def test_health_reset_vacia_grafica_pico_y_tiempos(self):
        import auth
        # deja datos de salud + tiempos + un mensaje basura del arnes
        self.client.get("/api/admin/health?record=1")
        self.client.get("/api/admin/health?record=1")
        with api_server._inflight_lock:
            api_server._inflight_peak["orch"] = 9
            api_server._llm_stats["ok"] = 5
            api_server._http_5xx["n"] = 3
        self.assertGreaterEqual(len(auth.list_system_health(self.engine)["items"]), 1)
        r = self.client.post("/api/admin/health/reset")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        # grafica y pico vacios
        self.assertEqual(len(auth.list_system_health(self.engine)["items"]), 0)
        self.assertIsNone(auth.get_system_peak(self.engine))
        # contadores en memoria a cero
        cur, peak = api_server.get_inflight()
        self.assertEqual(peak["orch"], 0)
        self.assertEqual(api_server.get_llm_stats()["ok"], 0)
        self.assertEqual(api_server.get_http_5xx(), 0)

    def test_backup_crea_copia(self):
        r = self.client.post("/api/admin/backup")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["ok"])
        self.assertTrue(d["file"].startswith("humania_"))
        self.assertGreater(d["bytes"], 0)
        backups = list((self.tmp / "memory" / "backups").glob("humania_*.db"))
        self.assertEqual(len(backups), 1)

    def test_health_no_admin_403(self):
        token, _ = self.auth_user()
        r = self.client.get("/api/admin/health", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 403)

    def test_restart_admin_ok_sin_matar_el_proceso(self):
        # Desde TestClient NO debe enviar SIGTERM (el test seguiría vivo).
        r = self.client.post("/api/admin/restart")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_restart_no_admin_403(self):
        token, _ = self.auth_user()
        r = self.client.post("/api/admin/restart", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 403)

    def test_staging_status_devuelve_estado(self):
        # En el entorno de test no hay systemd; debe degradar con gracia (no romper).
        r = self.client.get("/api/admin/staging/status")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIn("active", d)
        self.assertIn("state", d)
        self.assertEqual(d["service"], "humania-staging")

    def test_staging_control_no_admin_403(self):
        token, _ = self.auth_user()
        h = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.get("/api/admin/staging/status", headers=h).status_code, 403)
        self.assertEqual(self.client.post("/api/admin/staging/start", headers=h).status_code, 403)
        self.assertEqual(self.client.post("/api/admin/staging/stop", headers=h).status_code, 403)

    def test_reboot_admin_ok_sin_reiniciar(self):
        # Desde TestClient NO debe reiniciar la maquina de verdad.
        r = self.client.post("/api/admin/reboot")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_reboot_no_admin_403(self):
        token, _ = self.auth_user()
        r = self.client.post("/api/admin/reboot", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 403)

    def auth_user(self):
        import auth
        token, user = auth.register_user(self.engine, "u@test.com", "secreta123", "U",
                                         accept_terms=True, confirm_adult=True)
        return token, user["user_id"]


class TestLlmStats(unittest.TestCase):
    def setUp(self):
        with api_server._inflight_lock:
            for k in api_server._llm_stats:
                api_server._llm_stats[k] = 0

    def test_cuenta_y_fail_pct(self):
        api_server._llm_stat("ok"); api_server._llm_stat("ok")
        api_server._llm_stat("timeout"); api_server._llm_stat("rate_limited")
        s = api_server.get_llm_stats()
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["ok"], 2)
        self.assertEqual(s["fail_pct"], 50.0)


class TestAlerts(unittest.TestCase):
    def setUp(self):
        import tempfile, os
        from engine import ConversationEngine
        import auth
        import telegram_sender
        self.tmp = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.tmp)
        auth.init_auth_tables(self.engine)
        api_server._alert_state.clear()
        telegram_sender.SENT_TELEGRAM.clear()
        os.environ["HUMANIA_ALERTS"] = "1"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sample(self, **kw):
        base = {"disk_used_pct": 20, "disk_free_pct": 80, "worst": "ram",
                "cpu_pct": 50, "inflight_orch": 0, "inflight_requests": 0}
        base.update(kw)
        return base

    def _last_text(self):
        import telegram_sender
        return telegram_sender.SENT_TELEGRAM[-1]["text"]

    def test_alerta_en_rojo_y_recordatorio(self):
        import telegram_sender
        rojo = self._sample(capacity_pct=97, ram_pct=96, disk_used_pct=30)
        sent = api_server._health_alert_check(self.engine, sample=rojo)
        self.assertIn("capacity", sent)
        self.assertIn("ram", sent)
        self.assertEqual(len(telegram_sender.SENT_TELEGRAM), 2)
        self.assertIn("[H2AI alerta]", telegram_sender.SENT_TELEGRAM[0]["text"])
        # mismo nivel y dentro del intervalo de recordatorio -> no reenvía
        sent2 = api_server._health_alert_check(self.engine, sample=rojo)
        self.assertEqual(sent2, [])

    def test_escalado_salta_el_silencio(self):
        # aviso -> crítico de forma inmediata: el empeoramiento NO espera 30 min
        sent1 = api_server._health_alert_check(self.engine, sample=self._sample(ram_pct=88))
        self.assertEqual(sent1, ["ram"])
        self.assertIn("RAM aviso", self._last_text())
        sent2 = api_server._health_alert_check(self.engine, sample=self._sample(ram_pct=97))
        self.assertEqual(sent2, ["ram"])
        self.assertIn("RAM crítico", self._last_text())

    def test_mejora_parcial_no_reavisa(self):
        api_server._health_alert_check(self.engine, sample=self._sample(ram_pct=97))  # crítico
        # baja a "aviso" pero NO por debajo de la recuperación (75) -> silencio
        sent = api_server._health_alert_check(self.engine, sample=self._sample(ram_pct=88))
        self.assertEqual(sent, [])
        # vuelve a crítico sin haberse recuperado -> mismo nivel del episodio, no reavisa
        sent2 = api_server._health_alert_check(self.engine, sample=self._sample(ram_pct=97))
        self.assertEqual(sent2, [])

    def test_recuperacion_y_recaida(self):
        import telegram_sender
        api_server._health_alert_check(self.engine, sample=self._sample(ram_pct=97))  # crítico
        # baja por debajo de la línea de recuperación (75) -> aviso de recuperación ✅
        sent_rec = api_server._health_alert_check(self.engine, sample=self._sample(ram_pct=40))
        self.assertEqual(sent_rec, ["ram"])
        self.assertIn("recuperada", self._last_text())
        # recae: nuevo episodio -> vuelve a avisar aunque hayan pasado pocos minutos
        sent_re = api_server._health_alert_check(self.engine, sample=self._sample(ram_pct=88))
        self.assertEqual(sent_re, ["ram"])
        self.assertIn("RAM aviso", self._last_text())
        self.assertEqual(len(telegram_sender.SENT_TELEGRAM), 3)

    def test_muteado_no_envia(self):
        import os
        os.environ["HUMANIA_ALERTS"] = "0"
        sent = api_server._health_alert_check(self.engine, sample=self._sample(capacity_pct=99, ram_pct=99))
        self.assertEqual(sent, [])
        os.environ.pop("HUMANIA_ALERTS", None)


if __name__ == "__main__":
    unittest.main()
