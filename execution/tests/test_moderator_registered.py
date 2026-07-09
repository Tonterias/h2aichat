"""FASE 31 — Regresión: el moderador 'miguel' debe registrarse SIEMPRE antes de darle el
turno, aunque ya existan bots.

El bug: `/orchestrate` solo registraba a 'miguel' si NO había NINGÚN participante. Si había
bots pero no 'miguel', `acquire_turn('miguel')` ponía `turns.current_turn='miguel'`
violando la clave foránea `turns.current_turn -> participants(id)`. Postgres lo caza (y
SQLite con `foreign_keys=ON` también). Con base limpia el fallo se reproduce.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

import api_server
import auth
from engine import ConversationEngine


class TestModeradorSiempreRegistrado(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.tmp)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        self.client = TestClient(api_server.app)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        api_server.engine = ConversationEngine()

    def test_orquesta_con_bots_pero_sin_moderador(self):
        # Estado que disparaba el bug: hay un bot registrado, pero el moderador NO.
        mod_id = auth.DEV_USER["email"]  # FASE 31: el moderador es el email del usuario
        self.engine.register_participant("qwen_plus", "creativo", "bot", "q@t")
        participants = self.engine.read_state().get("participants", {})
        self.assertIn("qwen_plus", participants)
        self.assertNotIn(mod_id, participants)  # el moderador falta a propósito

        # Orquestar (rounds=0, sin LLM) NO debe romper por la clave foránea.
        r = self.client.post("/orchestrate?rounds=0", json={
            "recipient_id": "qwen_plus", "body": "hola", "sender_id": mod_id, "thread_id": "s1"})
        self.assertEqual(r.status_code, 200, r.text)  # antes: 500 (FK violation)

        # Y el moderador (email del usuario) quedó registrado como participante.
        self.assertIn(mod_id, self.engine.read_state().get("participants", {}))
        self.assertNotIn("miguel", self.engine.read_state().get("participants", {}))  # ya no hay 'miguel' global


if __name__ == "__main__":
    unittest.main()
