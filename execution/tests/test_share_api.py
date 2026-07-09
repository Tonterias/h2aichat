"""FASE 34 (T3) — Tests de los endpoints del enlace publico + la ruta /c/<token>."""
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine
import auth
import api_server
from api_server import app
from fastapi.testclient import TestClient


class ShareApiTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        api_server._login_attempts.clear()
        self.client = TestClient(app)
        r = self.client.post("/auth/register", json={
            "email": "po@test.com", "password": "secreta123", "name": "Miguel",
            "accept_terms": True, "confirm_adult": True})
        self.token = r.json()["token"]
        self.h = {"Authorization": f"Bearer {self.token}"}
        me = self.client.get("/auth/me", headers=self.h).json()["user"]
        self.uid = me["user_id"]
        self.thread = f"user_{self.uid}_LBO"
        self._seq = 0
        self._seed("miguel", "qwen_plus", "¿Es **inteligente** endeudarse para comprar?", "2026-06-26T08:29:05")
        self._seed("qwen_plus", "miguel", "Depende de las **sinergias**.", "2026-06-26T08:29:20")

    def _seed(self, sender, recipient, body, ts, thread=None):
        thread = thread or self.thread
        self._seq += 1
        conn = self.engine._get_conn()
        conn.execute(
            "INSERT INTO messages (message_id,sender,recipient,body,timestamp,sequence,read,content_type,thread_id) "
            "VALUES (?,?,?,?,?,?,0,'text/plain',?)",
            (f"m_{ts}_{self._seq}", sender, recipient, body, ts, self._seq, thread))
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        api_server.engine = ConversationEngine()

    def share(self):
        return self.client.post(f"/api/conversations/{self.thread}/share", json={"lang": "es"}, headers=self.h)

    def test_compartir_devuelve_url(self):
        r = self.share()
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["success"])
        self.assertTrue(d["token"])
        self.assertTrue(d["url"].endswith("/c/" + d["token"]))

    def test_pagina_publica_sin_login(self):
        token = self.share().json()["token"]
        r = self.client.get(f"/c/{token}")  # SIN auth
        self.assertEqual(r.status_code, 200)
        self.assertIn("endeudarse", r.text)
        self.assertIn('property="og:title"', r.text)
        self.assertIn("Miguel", r.text)  # moderador con su nombre

    def test_actualizar_mismo_token(self):
        t1 = self.share().json()["token"]
        self._seed("miguel", "qwen_plus", "Nuevo mensaje posterior.", "2026-06-26T09:00:00")
        t2 = self.share().json()["token"]
        self.assertEqual(t1, t2)  # mismo enlace
        self.assertIn("Nuevo mensaje posterior", self.client.get(f"/c/{t2}").text)  # re-congelado

    def test_estado(self):
        self.assertFalse(self.client.get(f"/api/conversations/{self.thread}/share", headers=self.h).json()["shared"])
        token = self.share().json()["token"]
        st = self.client.get(f"/api/conversations/{self.thread}/share", headers=self.h).json()
        self.assertTrue(st["shared"])
        self.assertEqual(st["token"], token)

    def test_revocar(self):
        token = self.share().json()["token"]
        r = self.client.post(f"/api/conversations/{self.thread}/share/revoke", headers=self.h)
        self.assertEqual(r.status_code, 200)
        gone = self.client.get(f"/c/{token}", follow_redirects=False)
        self.assertIn(gone.status_code, (302, 307))      # enlace roto/revocado -> a la home
        self.assertEqual(gone.headers["location"], "/web")
        self.assertFalse(self.client.get(f"/api/conversations/{self.thread}/share", headers=self.h).json()["shared"])

    def test_no_es_tuya_403(self):
        r = self.client.post("/api/conversations/user_99999_X/share", json={"lang": "es"}, headers=self.h)
        self.assertEqual(r.status_code, 403)

    def test_anonimo_401(self):
        r = self.client.post(f"/api/conversations/{self.thread}/share", json={"lang": "es"})
        self.assertEqual(r.status_code, 401)

    def test_enlace_roto_redirige_a_home(self):
        r = self.client.get("/c/noexisteee", follow_redirects=False)
        self.assertIn(r.status_code, (302, 307))
        self.assertEqual(r.headers["location"], "/web")

    def test_conversacion_vacia_400(self):
        r = self.client.post(f"/api/conversations/user_{self.uid}_Vacia/share", json={"lang": "es"}, headers=self.h)
        self.assertEqual(r.status_code, 400)

    def test_borrar_conversacion_mata_enlace(self):  # T6
        token = self.share().json()["token"]
        r = self.client.delete(f"/api/thread/{self.thread}", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(auth.get_share_link(self.engine, token))  # enlace muerto
        self.assertIn(self.client.get(f"/c/{token}", follow_redirects=False).status_code, (302, 307))

    def test_borrar_cuenta_mata_enlace_rgpd(self):  # T6 (RGPD)
        token = self.share().json()["token"]
        auth.delete_account(self.engine, self.uid)
        self.assertIsNone(auth.get_share_link(self.engine, token))


if __name__ == "__main__":
    unittest.main()
