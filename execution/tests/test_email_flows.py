"""FASES 20.4 + 20.3 — Tests de verificacion de email y recuperacion de contrasena."""
import os
import re
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

TOKEN_RE = re.compile(r"token=([A-Za-z0-9_\-]+)")


class EmailFlowBase(unittest.TestCase):
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
        os.environ.pop("HUMANIA_EMAIL_BACKEND", None)
        api_server.engine = ConversationEngine()

    def register(self, email="eva@test.com", password="secreta123", name="Eva"):
        return self.client.post("/auth/register", json={"email": email, "password": password, "name": name, "accept_terms": True, "confirm_adult": True})

    def last_email_token(self):
        body = email_sender.SENT_EMAILS[-1]["body"]
        match = TOKEN_RE.search(body)
        return match.group(1) if match else None


class TestEmailSender(EmailFlowBase):
    def test_backend_console_captura_envios(self):
        email_sender.send_email("x@test.com", "Asunto", "Cuerpo")
        self.assertEqual(email_sender.SENT_EMAILS[-1]["to"], "x@test.com")

    def test_backend_console_prohibido_en_produccion(self):
        os.environ["HUMANIA_ENV"] = "production"
        try:
            with self.assertRaises(RuntimeError):
                email_sender.get_backend()
        finally:
            os.environ.pop("HUMANIA_ENV", None)

    def test_backend_smtp_requiere_credenciales(self):
        os.environ["HUMANIA_EMAIL_BACKEND"] = "smtp"
        with self.assertRaises(RuntimeError):
            email_sender.send_email("x@test.com", "A", "B")


class TestBackendResend(EmailFlowBase):
    """FASE 20.1-A1: adaptador Resend (mock de httpx, sin llamadas reales)."""

    def tearDown(self):
        os.environ.pop("RESEND_API_KEY", None)
        os.environ.pop("HUMANIA_EMAIL_FROM", None)
        os.environ.pop("HUMANIA_ENV", None)
        super().tearDown()

    def test_backend_resend_requiere_api_key(self):
        os.environ["HUMANIA_EMAIL_BACKEND"] = "resend"
        with self.assertRaises(RuntimeError):
            email_sender.send_email("x@test.com", "A", "B")

    def test_backend_desconocido_rechazado(self):
        os.environ["HUMANIA_EMAIL_BACKEND"] = "paloma-mensajera"
        with self.assertRaises(RuntimeError):
            email_sender.get_backend()

    def test_backend_resend_payload_correcto(self):
        from unittest.mock import patch, MagicMock
        os.environ["HUMANIA_EMAIL_BACKEND"] = "resend"
        os.environ["RESEND_API_KEY"] = "re_test_clave_falsa"
        mock_resp = MagicMock()
        with patch.object(email_sender.httpx, "post", return_value=mock_resp) as mock_post:
            ok = email_sender.send_email("eva@test.com", "Asunto", "Cuerpo", "<p>Cuerpo</p>")
        self.assertTrue(ok)
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], email_sender.RESEND_API_URL)
        self.assertEqual(kwargs["json"]["from"], email_sender.DEFAULT_FROM)
        self.assertEqual(kwargs["json"]["to"], ["eva@test.com"])
        self.assertEqual(kwargs["json"]["subject"], "Asunto")
        self.assertEqual(kwargs["json"]["html"], "<p>Cuerpo</p>")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer re_test_clave_falsa")
        mock_resp.raise_for_status.assert_called_once()

    def test_registro_no_falla_si_resend_falla(self):
        """Patron 20.4b: el registro devuelve exito aunque el envio del email reviente."""
        from unittest.mock import patch
        os.environ["HUMANIA_EMAIL_BACKEND"] = "resend"
        os.environ["RESEND_API_KEY"] = "re_test_clave_falsa"
        with patch.object(email_sender.httpx, "post", side_effect=Exception("Resend caido")):
            resp = self.register()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_resend_valido_en_produccion(self):
        os.environ["HUMANIA_ENV"] = "production"
        os.environ["HUMANIA_EMAIL_BACKEND"] = "resend"
        os.environ["RESEND_API_KEY"] = "re_test_clave_falsa"
        self.assertEqual(email_sender.get_backend(), "resend")
        email_sender.validate_production_config()  # no debe lanzar

    def test_validate_production_exige_api_key(self):
        os.environ["HUMANIA_ENV"] = "production"
        os.environ["HUMANIA_EMAIL_BACKEND"] = "resend"
        with self.assertRaises(RuntimeError):
            email_sender.validate_production_config()


class TestVerificacionEmail(EmailFlowBase):
    def test_registro_envia_email_verificacion(self):
        self.register()
        self.assertEqual(len(email_sender.SENT_EMAILS), 1)
        self.assertEqual(email_sender.SENT_EMAILS[0]["to"], "eva@test.com")
        self.assertIn("/auth/verify-email?token=", email_sender.SENT_EMAILS[0]["body"])

    def test_usuario_nuevo_no_verificado(self):
        token = self.register().json()["token"]
        resp = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.json()["user"]["email_verified"], 0)

    def test_verify_email_con_token_valido(self):
        jwt_token = self.register().json()["token"]
        vtoken = self.last_email_token()
        resp = self.client.get(f"/auth/verify-email?token={vtoken}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("verificado", resp.text)
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {jwt_token}"})
        self.assertEqual(me.json()["user"]["email_verified"], 1)

    def test_verify_token_invalido(self):
        resp = self.client.get("/auth/verify-email?token=falso123")
        self.assertIn("no válido", resp.text)

    def test_verify_token_no_reutilizable(self):
        self.register()
        vtoken = self.last_email_token()
        self.client.get(f"/auth/verify-email?token={vtoken}")
        resp = self.client.get(f"/auth/verify-email?token={vtoken}")
        self.assertIn("no válido", resp.text)

    def test_verify_token_expirado(self):
        self.register()
        vtoken = self.last_email_token()
        conn = self.engine._get_conn()
        pasado = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute("UPDATE email_verifications SET expires_at=?", (pasado,))
        conn.commit()
        conn.close()
        resp = self.client.get(f"/auth/verify-email?token={vtoken}")
        self.assertIn("no válido", resp.text)

    def test_resend_genera_token_nuevo_e_invalida_anterior(self):
        jwt_token = self.register().json()["token"]
        token_viejo = self.last_email_token()
        resp = self.client.post("/auth/resend-verification", headers={"Authorization": f"Bearer {jwt_token}"})
        self.assertTrue(resp.json()["success"])
        token_nuevo = self.last_email_token()
        self.assertNotEqual(token_viejo, token_nuevo)
        self.assertIn("no válido", self.client.get(f"/auth/verify-email?token={token_viejo}").text)
        self.assertIn("verificado", self.client.get(f"/auth/verify-email?token={token_nuevo}").text)

    def test_resend_sin_sesion_da_401(self):
        resp = self.client.post("/auth/resend-verification")
        self.assertEqual(resp.status_code, 401)

    def test_resend_ya_verificado(self):
        jwt_token = self.register().json()["token"]
        self.client.get(f"/auth/verify-email?token={self.last_email_token()}")
        resp = self.client.post("/auth/resend-verification", headers={"Authorization": f"Bearer {jwt_token}"})
        self.assertIn("ya esta verificado", resp.json()["message"])


class TestLimiteNoVerificado(EmailFlowBase):
    def test_no_verificado_limitado_a_1_debate_dia(self):
        self.register()
        user = {"user_id": 1, "email": "eva@test.com", "plan": "free"}
        ok, _ = auth.check_unverified_limit(self.engine, user)
        self.assertTrue(ok)
        auth.record_debate(self.engine, user, 3, 3)
        ok, reason = auth.check_unverified_limit(self.engine, user)
        self.assertFalse(ok)
        self.assertIn("Verifica tu email", reason)

    def test_verificado_sin_limite_diario(self):
        self.register()
        self.client.get(f"/auth/verify-email?token={self.last_email_token()}")
        user = {"user_id": 1, "email": "eva@test.com", "plan": "free"}
        auth.record_debate(self.engine, user, 3, 3)
        ok, _ = auth.check_unverified_limit(self.engine, user)
        self.assertTrue(ok)

    def test_usuario_dev_sin_limite(self):
        ok, _ = auth.check_unverified_limit(self.engine, dict(auth.DEV_USER))
        self.assertTrue(ok)


class TestRecuperacionPassword(EmailFlowBase):
    def test_forgot_envia_email_con_enlace(self):
        self.register()
        email_sender.SENT_EMAILS.clear()
        resp = self.client.post("/auth/forgot-password", json={"email": "eva@test.com"})
        self.assertTrue(resp.json()["success"])
        self.assertEqual(len(email_sender.SENT_EMAILS), 1)
        self.assertIn("/auth/reset-password?token=", email_sender.SENT_EMAILS[0]["body"])

    def test_forgot_email_inexistente_respuesta_neutra(self):
        resp = self.client.post("/auth/forgot-password", json={"email": "nadie@test.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Si el email existe", resp.json()["message"])
        self.assertEqual(len(email_sender.SENT_EMAILS), 0)

    def test_reset_cambia_la_password(self):
        self.register()
        email_sender.SENT_EMAILS.clear()
        self.client.post("/auth/forgot-password", json={"email": "eva@test.com"})
        rtoken = self.last_email_token()
        resp = self.client.post("/auth/reset-password", json={"token": rtoken, "password": "nuevapass456"})
        self.assertTrue(resp.json()["success"])
        self.assertEqual(self.client.post("/auth/login", json={"email": "eva@test.com", "password": "nuevapass456"}).status_code, 200)
        self.assertEqual(self.client.post("/auth/login", json={"email": "eva@test.com", "password": "secreta123"}).status_code, 401)

    def test_reset_token_no_reutilizable(self):
        self.register()
        email_sender.SENT_EMAILS.clear()
        self.client.post("/auth/forgot-password", json={"email": "eva@test.com"})
        rtoken = self.last_email_token()
        self.client.post("/auth/reset-password", json={"token": rtoken, "password": "nuevapass456"})
        resp = self.client.post("/auth/reset-password", json={"token": rtoken, "password": "otravez789"})
        self.assertEqual(resp.status_code, 400)

    def test_reset_token_expirado(self):
        self.register()
        email_sender.SENT_EMAILS.clear()
        self.client.post("/auth/forgot-password", json={"email": "eva@test.com"})
        rtoken = self.last_email_token()
        conn = self.engine._get_conn()
        pasado = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        conn.execute("UPDATE password_resets SET expires_at=?", (pasado,))
        conn.commit()
        conn.close()
        resp = self.client.post("/auth/reset-password", json={"token": rtoken, "password": "nuevapass456"})
        self.assertEqual(resp.status_code, 400)

    def test_reset_password_corta(self):
        self.register()
        email_sender.SENT_EMAILS.clear()
        self.client.post("/auth/forgot-password", json={"email": "eva@test.com"})
        rtoken = self.last_email_token()
        resp = self.client.post("/auth/reset-password", json={"token": rtoken, "password": "corta"})
        self.assertEqual(resp.status_code, 400)

    def test_pagina_reset_se_sirve(self):
        resp = self.client.get("/auth/reset-password?token=abc")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Nueva contraseña", resp.text)


if __name__ == "__main__":
    unittest.main()
