"""FASE 24 — Test de aceptacion: turno/cola/stop AISLADOS por conversacion.

Es la repro del sabotaje de la Fase 23 (repro_turno_global.py) convertida en
regresion: lo que antes demostraba el sabotaje, ahora debe demostrar el aislamiento."""
import os
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


class TestTurnIsolationEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        for p in ("alice", "bob", "qwen_plus", "minimax", "deepseek_flash"):
            self.engine.register_participant(p, "x", "bot", f"{p}@t")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_limpieza_de_B_no_roba_turno_ni_cola_de_A(self):
        """El corazon del fix: la orquestacion de B (clear_queue + force_release
        acotados a su hilo) NO toca a la conversacion A."""
        e = self.engine
        # A en marcha: un bot tiene el turno y otros esperan en cola
        e.acquire_turn("qwen_plus", "A")
        e.add_to_queue("minimax", "A")
        e.add_to_queue("deepseek_flash", "A")
        # B arranca: replica la limpieza de /orchestrate, acotada a 'B'
        e.clear_queue("B")
        tw = e.get_current_turn("B")
        if tw:
            e.force_release_turn(tw, "B")
        self.assertTrue(e.acquire_turn("bob", "B"))
        # A sigue intacta
        self.assertEqual(e.get_current_turn("A"), "qwen_plus")
        self.assertEqual(e.get_queue("A"), ["minimax", "deepseek_flash"])
        self.assertEqual(e.get_current_turn("B"), "bob")

    def test_dos_bots_con_turno_a_la_vez_en_hilos_distintos(self):
        e = self.engine
        self.assertTrue(e.acquire_turn("qwen_plus", "A"))
        self.assertTrue(e.acquire_turn("minimax", "B"))  # paralelismo real
        self.assertEqual(e.get_current_turn("A"), "qwen_plus")
        self.assertEqual(e.get_current_turn("B"), "minimax")

    def test_mismo_bot_puede_tener_turno_en_dos_hilos(self):
        e = self.engine
        self.assertTrue(e.acquire_turn("qwen_plus", "A"))
        self.assertTrue(e.acquire_turn("qwen_plus", "B"))

    def test_stop_es_por_conversacion(self):
        e = self.engine
        e.acquire_turn("qwen_plus", "A")
        e.acquire_turn("minimax", "B")
        e.request_stop("A")
        self.assertTrue(e.should_stop("A"))
        self.assertFalse(e.should_stop("B"))  # pausar A no para B

    def test_cola_es_por_conversacion(self):
        e = self.engine
        e.acquire_turn("alice", "A")  # ocupa el turno para que la cola tenga sentido
        e.acquire_turn("bob", "B")
        e.add_to_queue("qwen_plus", "A")
        e.add_to_queue("minimax", "B")
        self.assertEqual(e.get_queue("A"), ["qwen_plus"])
        self.assertEqual(e.get_queue("B"), ["minimax"])

    def test_hard_reset_de_un_hilo_no_afecta_a_otro(self):
        e = self.engine
        e.acquire_turn("qwen_plus", "A")
        e.acquire_turn("minimax", "B")
        e.hard_reset("A")
        self.assertIsNone(e.get_current_turn("A"))
        self.assertEqual(e.get_current_turn("B"), "minimax")  # B intacto

    def test_hard_reset_all_limpia_todos(self):
        e = self.engine
        e.acquire_turn("qwen_plus", "A")
        e.acquire_turn("minimax", "B")
        e.hard_reset_all()
        self.assertIsNone(e.get_current_turn("A"))
        self.assertIsNone(e.get_current_turn("B"))

    def test_migracion_de_esquema_viejo_preserva_general(self):
        """Una BD con el esquema VIEJO (turns de fila unica id=1) se migra a una fila
        por hilo, preservando el estado bajo 'general'."""
        d = Path(tempfile.mkdtemp())
        try:
            e = ConversationEngine(base_path=d)
            e.register_participant("qwen_plus", "x", "bot", "q@t")
            conn = e._get_conn()
            conn.execute("DROP TABLE turns")
            conn.execute("CREATE TABLE turns (id INTEGER PRIMARY KEY CHECK (id=1), current_turn TEXT, "
                         "state TEXT DEFAULT 'idle', started_at TEXT, max_duration INTEGER DEFAULT 300, "
                         "stop_flag INTEGER DEFAULT 0)")
            conn.execute("INSERT INTO turns (id, current_turn, state, max_duration, stop_flag) "
                         "VALUES (1, 'qwen_plus', 'active', 300, 0)")
            conn.commit()
            e._migrate_schema(conn)
            conn.commit()
            conn.close()
            self.assertEqual(e.get_current_turn("general"), "qwen_plus")
            self.assertEqual(e.read_state("general")["state"], "active")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestConcurrentOrchestrationHTTP(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        api_server.engine = ConversationEngine()

    def _orchestrate(self, thread):
        # rounds=0: registra participantes y postea el mensaje del moderador, sin LLM
        return self.client.post("/orchestrate?rounds=0", json={
            "recipient_id": "qwen_plus", "body": "hola", "sender_id": "miguel", "thread_id": thread})

    def test_orchestrate_de_B_no_toca_la_conversacion_A(self):
        # 1) Arrancar convA (rounds=0) -> registra participantes y postea en convA
        r = self._orchestrate("convA")
        self.assertEqual(r.status_code, 200)
        # 2) Simular que convA esta a media orquestacion: un bot tiene el turno y hay cola
        self.engine.acquire_turn("qwen_plus", "convA")
        self.engine.add_to_queue("minimax", "convA")
        # 3) Otra conversacion (convB) arranca su orquestacion
        r = self._orchestrate("convB")
        self.assertEqual(r.status_code, 200)
        # 4) convA quedo INTACTA (antes del fix, convB le robaba el turno y la cola)
        self.assertEqual(self.engine.get_current_turn("convA"), "qwen_plus")
        self.assertEqual(self.engine.get_queue("convA"), ["minimax"])


if __name__ == "__main__":
    unittest.main()
