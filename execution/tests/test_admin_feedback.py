"""FASE 20.7.1 — Lector de comentarios en conversaciones (panel /admin).

Cubre la funcion auth.list_conversation_comments (T1) y el endpoint
GET /api/admin/feedback/comments (solo admin). Verifica que:
- solo entran los comentarios de TEXTO de conversaciones (no los pulgares sueltos ni el contacto),
- orden mas reciente primero, usuario/anonimo, pulgar, y el enlace publico si la conversacion esta publicada,
- el endpoint es solo-admin.
"""
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


class Base(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        api_server.engine = ConversationEngine()

    def mkuser(self, email="ana@test.com", name="Ana"):
        token, user = auth.register_user(self.engine, email, "secreta123", name,
                                         accept_terms=True, confirm_adult=True)
        return token, user["user_id"]


class TestBackend(Base):
    def test_solo_comentarios_de_texto_de_conversacion(self):
        auth.save_feedback(self.engine, "conversation", conversation_id="user_1_Tema", vote="up", comment="Muy bueno")
        auth.save_feedback(self.engine, "conversation", conversation_id="user_1_Tema", vote="down", comment=None)  # sin texto
        auth.save_feedback(self.engine, "public", conversation_id="user_1_Tema", vote="up")                        # pulgar publico
        auth.save_feedback(self.engine, "contact", comment="Hola", contact_type="bug")                            # contacto, no conversacion
        out = auth.list_conversation_comments(self.engine)["comments"]
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["comentario"], "Muy bueno")
        self.assertEqual(out[0]["pulgar"], "up")

    def test_comentario_en_blanco_no_entra(self):
        auth.save_feedback(self.engine, "conversation", conversation_id="c1", comment="   ")  # solo espacios
        self.assertEqual(auth.list_conversation_comments(self.engine)["comments"], [])

    def test_orden_reciente_primero(self):
        auth.save_feedback(self.engine, "conversation", conversation_id="c1", comment="viejo")
        auth.save_feedback(self.engine, "conversation", conversation_id="c2", comment="nuevo")
        out = auth.list_conversation_comments(self.engine)["comments"]
        self.assertEqual(out[0]["comentario"], "nuevo")
        self.assertEqual(out[1]["comentario"], "viejo")

    def test_usuario_o_anonimo(self):
        _, uid = self.mkuser("ana@test.com", "Ana")
        auth.save_feedback(self.engine, "conversation", user_id=uid, conversation_id="c1", comment="con usuario")
        auth.save_feedback(self.engine, "conversation", user_id=None, conversation_id="c2", comment="sin usuario")
        by = {c["comentario"]: c for c in auth.list_conversation_comments(self.engine)["comments"]}
        self.assertEqual(by["con usuario"]["usuario"], "Ana")
        self.assertIsNone(by["sin usuario"]["usuario"])  # el front lo pinta como "anonimo"

    def test_pulgar_mapea(self):
        auth.save_feedback(self.engine, "conversation", conversation_id="c1", vote="up", comment="a")
        auth.save_feedback(self.engine, "conversation", conversation_id="c2", vote="down", comment="b")
        auth.save_feedback(self.engine, "conversation", conversation_id="c3", vote=None, comment="c")
        by = {c["comentario"]: c["pulgar"] for c in auth.list_conversation_comments(self.engine)["comments"]}
        self.assertEqual(by["a"], "up")
        self.assertEqual(by["b"], "down")
        self.assertIsNone(by["c"])

    def test_url_publica_solo_si_publicada(self):
        auth.save_feedback(self.engine, "conversation", conversation_id="user_1_Pub", comment="hola")
        auth.save_feedback(self.engine, "conversation", conversation_id="user_1_Priv", comment="mundo")
        conn = self.engine._get_conn()
        conn.execute("INSERT INTO shared_conversation (token, thread_id, user_id, snapshot, revoked) VALUES (?,?,?,?,0)",
                     ("tok999", "user_1_Pub", 1, "{}"))
        conn.commit()
        conn.close()
        by = {c["conversacion"]: c for c in auth.list_conversation_comments(self.engine)["comments"]}
        self.assertEqual(by["user_1_Pub"]["url_publica"], "/c/tok999")
        self.assertIsNone(by["user_1_Priv"]["url_publica"])

    def test_share_revocado_no_da_enlace(self):
        auth.save_feedback(self.engine, "conversation", conversation_id="user_1_X", comment="hola")
        conn = self.engine._get_conn()
        conn.execute("INSERT INTO shared_conversation (token, thread_id, user_id, snapshot, revoked) VALUES (?,?,?,?,1)",
                     ("tokRev", "user_1_X", 1, "{}"))
        conn.commit()
        conn.close()
        out = auth.list_conversation_comments(self.engine)["comments"]
        self.assertIsNone(out[0]["url_publica"])


class TestEndpoint(Base):
    def test_dev_admin_ve_comentarios(self):
        auth.save_feedback(self.engine, "conversation", conversation_id="c1", comment="hey")
        r = self.client.get("/api/admin/feedback/comments")  # sin cabecera = dev/local = admin
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["comments"]), 1)
        self.assertEqual(r.json()["comments"][0]["comentario"], "hey")

    def test_usuario_normal_recibe_403(self):
        token, _ = self.mkuser("u@test.com", "U")
        r = self.client.get("/api/admin/feedback/comments", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
