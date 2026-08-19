"""Regression: the moderator must ALWAYS be registered before being given the
turno, aunque ya existan bots.

The bug: `/orchestrate` registered the moderator only when there was NO participant at all.
With bots present but no moderator, acquire_turn set turns.current_turn to an id that
broke the foreign key `turns.current_turn -> participants(id)`. Postgres catches it, and
so does SQLite with `foreign_keys=ON`. On a clean database the failure reproduces.
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
        # The state that triggered the bug: a bot is registered, but the moderator is NOT.
        mod_id = auth.DEV_USER["email"]  # FASE 31: el moderador es el email del usuario
        self.engine.register_participant("qwen_plus", "creativo", "bot", "q@t")
        participants = self.engine.read_state().get("participants", {})
        self.assertIn("qwen_plus", participants)
        self.assertNotIn(mod_id, participants)  # el moderador falta a propósito

        # Orchestrating (rounds=0, no LLM) must NOT break on the foreign key.
        r = self.client.post("/orchestrate?rounds=0", json={
            "recipient_id": "qwen_plus", "body": "hola", "sender_id": mod_id, "thread_id": "s1"})
        self.assertEqual(r.status_code, 200, r.text)  # antes: 500 (FK violation)

        # And the moderator (the user's address) ends up registered as a participant.
        self.assertIn(mod_id, self.engine.read_state().get("participants", {}))
        self.assertNotIn("miguel", self.engine.read_state().get("participants", {}))  # ya no hay 'miguel' global


if __name__ == "__main__":
    unittest.main()
