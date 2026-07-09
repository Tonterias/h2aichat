"""FASE 20.8 — Tests GDPR: consentimiento, export, supresion, limpieza y paginas legales."""
import os
import sys
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine
import auth
import email_sender
import api_server
from api_server import app
from fastapi.testclient import TestClient


class GdprTestBase(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        api_server._login_attempts.clear()
        email_sender.SENT_EMAILS.clear()
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        os.environ.pop("HUMANIA_AUTH", None)
        api_server.engine = ConversationEngine()

    def register(self, email="leo@test.com", password="secreta123", name="Leo", accept=True):
        return self.client.post("/auth/register",
                                json={"email": email, "password": password, "name": name, "accept_terms": accept, "confirm_adult": True})


class TestConsentimiento(GdprTestBase):
    def test_registro_sin_aceptar_terminos_da_400(self):
        resp = self.register(accept=False)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("terminos", resp.json()["detail"])

    def test_registro_guarda_timestamp_y_version(self):
        self.register()
        conn = self.engine._get_conn()
        row = conn.execute("SELECT accepted_terms_at, terms_version FROM users WHERE email='leo@test.com'").fetchone()
        conn.close()
        self.assertIsNotNone(row["accepted_terms_at"])
        self.assertEqual(row["terms_version"], auth.TERMS_VERSION)


class TestExport(GdprTestBase):
    def test_export_requiere_sesion(self):
        resp = self.client.get("/api/account/export")
        self.assertEqual(resp.status_code, 401)

    def test_export_devuelve_perfil_uso_y_mensajes_propios(self):
        token = self.register().json()["token"]
        self.engine.register_participant("miguel", "moderador", "human", "m@t")
        self.engine.register_participant("bot1", "analista", "bot", "b@t")
        self.engine.send_message("bot1", "mio", "miguel", thread_id="user_1_ideas")
        self.engine.send_message("bot1", "ajeno", "miguel", thread_id="user_99_otro")
        resp = self.client.get("/api/account/export", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["user"]["email"], "leo@test.com")
        self.assertNotIn("password_hash", data["user"])
        bodies = [m["body"] for m in data["messages"]]
        self.assertIn("mio", bodies)
        self.assertNotIn("ajeno", bodies)

    def test_export_con_cabecera_de_descarga(self):
        token = self.register().json()["token"]
        resp = self.client.get("/api/account/export", headers={"Authorization": f"Bearer {token}"})
        self.assertIn("attachment", resp.headers.get("content-disposition", ""))


class TestSupresion(GdprTestBase):
    def test_delete_requiere_sesion(self):
        resp = self.client.request("DELETE", "/api/account", json={"password": "secreta123"})
        self.assertEqual(resp.status_code, 401)

    def test_delete_password_incorrecta_da_403(self):
        token = self.register().json()["token"]
        resp = self.client.request("DELETE", "/api/account", json={"password": "mala12345"},
                                   headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)

    def test_delete_borra_cuenta_y_todos_sus_datos(self):
        token = self.register().json()["token"]
        self.engine.register_participant("miguel", "moderador", "human", "m@t")
        self.engine.register_participant("bot1", "analista", "bot", "b@t")
        self.engine.send_message("bot1", "mio", "miguel", thread_id="user_1_ideas")
        self.engine.send_message("bot1", "ajeno", "miguel", thread_id="user_99_otro")
        auth.record_debate(self.engine, {"user_id": 1, "plan": "free"}, 3, 3)
        resp = self.client.request("DELETE", "/api/account", json={"password": "secreta123"},
                                   headers={"Authorization": f"Bearer {token}"})
        self.assertTrue(resp.json()["success"])
        conn = self.engine._get_conn()
        self.assertIsNone(conn.execute("SELECT 1 FROM users WHERE id=1").fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM messages WHERE thread_id LIKE 'user_1_%'").fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM usage WHERE user_id=1").fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM email_verifications WHERE user_id=1").fetchone())
        # Los datos de otros usuarios sobreviven
        self.assertIsNotNone(conn.execute("SELECT 1 FROM messages WHERE thread_id LIKE 'user_99_%'").fetchone())
        conn.close()

    def test_delete_revoca_el_jwt(self):
        token = self.register().json()["token"]
        self.client.request("DELETE", "/api/account", json={"password": "secreta123"},
                            headers={"Authorization": f"Bearer {token}"})
        resp = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)

    def test_login_imposible_tras_borrar(self):
        token = self.register().json()["token"]
        self.client.request("DELETE", "/api/account", json={"password": "secreta123"},
                            headers={"Authorization": f"Bearer {token}"})
        resp = self.client.post("/auth/login", json={"email": "leo@test.com", "password": "secreta123"})
        self.assertEqual(resp.status_code, 401)


class TestLimpieza(GdprTestBase):
    def test_purga_tokens_caducados_antiguos(self):
        self.register()
        conn = self.engine._get_conn()
        viejo = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        conn.execute("UPDATE email_verifications SET expires_at=?", (viejo,))
        conn.commit()
        conn.close()
        auth.cleanup_expired(self.engine)
        conn = self.engine._get_conn()
        self.assertIsNone(conn.execute("SELECT 1 FROM email_verifications").fetchone())
        conn.close()

    def test_conserva_tokens_vigentes(self):
        self.register()
        auth.cleanup_expired(self.engine)
        conn = self.engine._get_conn()
        self.assertIsNotNone(conn.execute("SELECT 1 FROM email_verifications").fetchone())
        conn.close()


class TestPaginasLegales(GdprTestBase):
    def test_web_contiene_privacidad_y_terminos(self):
        resp = self.client.get("/web")
        self.assertIn("Política de privacidad", resp.text)
        self.assertIn("Términos de servicio", resp.text)
        self.assertIn("modelos de IA de proveedores terceros", resp.text)  # transparencia IA

    def test_footer_enlaza_legales(self):
        resp = self.client.get("/web")
        self.assertIn("navTo('privacidad')", resp.text)
        self.assertIn("navTo('terminos')", resp.text)

    def test_emails_llevan_aviso_de_privacidad(self):
        self.register()
        self.assertIn("privacidad", email_sender.SENT_EMAILS[-1]["body"].lower())


if __name__ == "__main__":
    unittest.main()
