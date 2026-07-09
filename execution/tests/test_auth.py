"""FASE 20.2 — Tests de autenticacion, limites free tier y kill-switch."""
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


class AuthTestBase(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        api_server._login_attempts.clear()
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        os.environ.pop("HUMANIA_AUTH", None)
        api_server.engine = ConversationEngine()

    def register(self, email="ana@test.com", password="secreta123", name="Ana"):
        return self.client.post("/auth/register", json={"email": email, "password": password, "name": name, "accept_terms": True, "confirm_adult": True})


class TestRegister(AuthTestBase):
    def test_register_ok_devuelve_token(self):
        resp = self.register()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("token", data)
        self.assertEqual(data["user"]["email"], "ana@test.com")
        self.assertEqual(data["user"]["plan"], "free")

    def test_register_email_duplicado(self):
        self.register()
        resp = self.register()
        self.assertEqual(resp.status_code, 400)

    def test_register_email_invalido(self):
        resp = self.register(email="no-es-un-email")
        self.assertEqual(resp.status_code, 400)

    def test_register_password_corta(self):
        resp = self.register(password="corta")
        self.assertEqual(resp.status_code, 400)

    def test_password_nunca_en_plaintext(self):
        self.register(password="secreta123")
        conn = self.engine._get_conn()
        row = conn.execute("SELECT password_hash FROM users WHERE email='ana@test.com'").fetchone()
        conn.close()
        self.assertNotIn("secreta123", row["password_hash"])
        self.assertTrue(row["password_hash"].startswith("$2"))  # formato bcrypt

    def test_register_sin_confirmar_mayor_de_edad_da_400(self):
        resp = self.client.post("/auth/register", json={
            "email": "menor@test.com", "password": "secreta123", "name": "X",
            "accept_terms": True, "confirm_adult": False})
        self.assertEqual(resp.status_code, 400)

    def test_register_guarda_confirmacion_mayor_de_edad(self):
        self.register()
        conn = self.engine._get_conn()
        row = conn.execute("SELECT confirmed_adult_at FROM users WHERE email='ana@test.com'").fetchone()
        conn.close()
        self.assertIsNotNone(row["confirmed_adult_at"])

    def test_tablas_users_y_usage_creadas(self):
        conn = self.engine._get_conn()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        self.assertIn("users", tables)
        self.assertIn("usage", tables)


class TestLogin(AuthTestBase):
    def test_login_ok(self):
        self.register()
        resp = self.client.post("/auth/login", json={"email": "ana@test.com", "password": "secreta123"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("token", resp.json())

    def test_login_password_incorrecta(self):
        self.register()
        resp = self.client.post("/auth/login", json={"email": "ana@test.com", "password": "incorrecta1"})
        self.assertEqual(resp.status_code, 401)

    def test_login_email_inexistente(self):
        resp = self.client.post("/auth/login", json={"email": "nadie@test.com", "password": "loquesea123"})
        self.assertEqual(resp.status_code, 401)

    def test_login_rate_limit_5_por_hora(self):
        os.environ["HUMANIA_AUTH"] = "on"  # activa el limite tambien para IPs locales
        self.register()
        for _ in range(5):
            self.client.post("/auth/login", json={"email": "ana@test.com", "password": "mala12345"})
        resp = self.client.post("/auth/login", json={"email": "ana@test.com", "password": "secreta123"})
        self.assertEqual(resp.status_code, 429)


class TestSesion(AuthTestBase):
    def test_me_con_token(self):
        token = self.register().json()["token"]
        resp = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user"]["email"], "ana@test.com")
        self.assertIn("usage", resp.json())

    def test_me_sin_token_en_dev_devuelve_usuario_dev(self):
        resp = self.client.get("/auth/me")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user"]["user_id"], 0)

    def test_token_invalido_da_401(self):
        resp = self.client.get("/auth/me", headers={"Authorization": "Bearer token-falso"})
        self.assertEqual(resp.status_code, 401)

    def test_logout_revoca_token(self):
        token = self.register().json()["token"]
        resp = self.client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertTrue(resp.json()["success"])
        resp = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)

    def test_enforcement_en_produccion(self):
        os.environ["HUMANIA_AUTH"] = "on"
        resp = self.client.get("/api/participants")
        self.assertEqual(resp.status_code, 401)
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/web")

    def test_rutas_publicas_sin_token_con_enforcement(self):
        os.environ["HUMANIA_AUTH"] = "on"
        self.assertEqual(self.client.get("/status").status_code, 200)
        self.assertEqual(self.client.get("/web").status_code, 200)


class TestAislamiento(AuthTestBase):
    def test_scope_thread_prefija_usuario(self):
        user = {"user_id": 7, "plan": "free"}
        self.assertEqual(auth.scope_thread(user, "general"), "user_7_general")
        self.assertEqual(auth.scope_thread(user, "user_7_general"), "user_7_general")
        self.assertEqual(auth.scope_thread(dict(auth.DEV_USER), "general"), "general")

    def test_usuario_no_ve_threads_ajenos(self):
        self.assertTrue(auth.visible_to_user({"user_id": 7}, "user_7_ideas"))
        self.assertFalse(auth.visible_to_user({"user_id": 7}, "user_8_ideas"))
        self.assertTrue(auth.visible_to_user(dict(auth.DEV_USER), "user_8_ideas"))

    def test_api_threads_filtra_por_usuario(self):
        token = self.register().json()["token"]
        self.engine.register_participant("miguel", "moderador", "human", "m@t")
        self.engine.register_participant("bot1", "analista", "bot", "b@t")
        self.engine.send_message("bot1", "hola", "miguel", thread_id="user_1_privado")
        self.engine.send_message("bot1", "ajeno", "miguel", thread_id="user_99_secreto")
        resp = self.client.get("/api/threads", headers={"Authorization": f"Bearer {token}"})
        threads = resp.json()["threads"]
        self.assertIn("user_1_privado", threads)
        self.assertNotIn("user_99_secreto", threads)

    def test_borrar_thread_ajeno_prohibido(self):
        token = self.register().json()["token"]
        resp = self.client.delete("/api/thread/user_99_secreto", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)


class TestLimites(AuthTestBase):
    def _free_user(self):
        self.register()
        return {"user_id": 1, "email": "ana@test.com", "name": "Ana", "plan": "free"}

    def test_free_dentro_de_limites_pasa(self):
        ok, _ = auth.check_free_limits(self.engine, self._free_user())
        self.assertTrue(ok)

    def test_free_al_limite_de_debates_bloqueado(self):
        user = self._free_user()
        for _ in range(auth.FREE_DEBATES_PER_MONTH):
            auth.record_debate(self.engine, user, 3, 3)
        ok, reason = auth.check_free_limits(self.engine, user)
        self.assertFalse(ok)
        self.assertIn("Pro", reason)

    def test_kill_switch_presupuesto_global(self):
        user = self._free_user()
        self.engine.set_setting("free_spent_month", auth._current_month())
        self.engine.set_setting("free_spent_eur", "30")
        ok, reason = auth.check_free_limits(self.engine, user)
        self.assertFalse(ok)
        self.assertIn("Demanda desbordada", reason)

    def test_premium_no_afectado_por_kill_switch(self):
        self.engine.set_setting("free_spent_month", auth._current_month())
        self.engine.set_setting("free_spent_eur", "999")
        ok, _ = auth.check_free_limits(self.engine, {"user_id": 5, "plan": "premium"})
        self.assertTrue(ok)

    def test_usuario_dev_no_consume(self):
        auth.record_debate(self.engine, dict(auth.DEV_USER), 5, 3)
        self.assertEqual(auth.get_usage(self.engine, 0)["debates"], 0)

    def test_record_debate_acumula_coste(self):
        user = self._free_user()
        auth.record_debate(self.engine, user, 3, 3)
        usage = auth.get_usage(self.engine, user["user_id"])
        self.assertEqual(usage["debates"], 1)
        self.assertGreater(usage["est_cost_eur"], 0)
        self.assertGreater(float(self.engine.get_setting("free_spent_eur", "0")), 0)

    def test_record_debate_acumula_tokens(self):
        user = self._free_user()
        auth.record_debate(self.engine, user, 3, 3, tokens={"prompt": 100, "completion": 50, "reasoning": 40, "total": 150})
        auth.record_debate(self.engine, user, 3, 3, tokens={"prompt": 10, "completion": 5, "reasoning": 4, "total": 15})
        usage = auth.get_usage(self.engine, user["user_id"])
        self.assertEqual(usage["prompt_tokens"], 110)
        self.assertEqual(usage["reasoning_tokens"], 44)
        self.assertEqual(usage["total_tokens"], 165)

    def test_free_jamas_openrouter(self):
        config_caro = {"gpt": {"provider": "openrouter", "model": "openai/gpt-5.4"}}
        fallback = {"qwen": {"provider": "cloud", "model": "qwen3.5-plus"}}
        safe = auth.free_safe_bots_config(config_caro, fallback)
        self.assertEqual(safe, fallback)
        config_ok = {"qwen": {"provider": "cloud", "model": "qwen3.5-plus"}}
        self.assertEqual(auth.free_safe_bots_config(config_ok, fallback), config_ok)


class TestAccesoProduccion(AuthTestBase):
    """FASE 20.1 (hallazgo UAT PO 2026-06-12): flujo de acceso con auth forzada.
    El JWT del usuario va antes que el token maestro; /chat sirve la SPA sin sesion
    en el header (la SPA se autoprotege via /auth/me)."""

    def test_chat_sirve_spa_sin_sesion_con_auth_forzada(self):
        os.environ["HUMANIA_AUTH"] = "on"
        resp = self.client.get("/chat")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("initSession", resp.text)  # es la SPA, que validara la sesion ella misma

    def test_raiz_anonima_redirige_a_web_con_auth_forzada(self):
        os.environ["HUMANIA_AUTH"] = "on"
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/web")

    def test_jwt_da_acceso_a_api_con_auth_forzada(self):
        token = self.register().json()["token"]
        os.environ["HUMANIA_AUTH"] = "on"
        resp = self.client.get("/api/threads", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)

    def test_token_maestro_da_acceso_admin_con_auth_forzada(self):
        os.environ["HUMANIA_AUTH"] = "on"
        resp = self.client.get("/api/turn-history", headers={"X-Humania-Token": "humania-dev-token"})
        self.assertEqual(resp.status_code, 200)

    def test_sin_jwt_ni_maestro_da_401_con_auth_forzada(self):
        os.environ["HUMANIA_AUTH"] = "on"
        resp = self.client.get("/api/threads")
        self.assertEqual(resp.status_code, 401)

    def test_lectura_de_hilos_traducida_al_usuario(self):
        """Hallazgo UAT PO 2026-06-12: pedir ?thread_id=general debe devolver los
        mensajes del hilo del usuario (user_N_general) y el nombre canonico."""
        self.engine.register_participant("miguel", "t1", "human", "m@t")
        self.engine.register_participant("qwen_plus", "t2", "bot", "q@t")
        token = self.register().json()["token"]
        os.environ["HUMANIA_AUTH"] = "on"
        headers = {"Authorization": f"Bearer {token}"}
        r = self.client.post("/message/send", headers=headers, json={
            "recipient_id": "qwen_plus", "body": "hola", "sender_id": "miguel", "thread_id": "general"})
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/all-messages?thread_id=general", headers=headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreaterEqual(data["count"], 1)
        self.assertTrue(data["thread_id"].startswith("user_"))
        self.assertTrue(data["thread_id"].endswith("_general"))
        for msg in data["messages"]:
            self.assertEqual(msg["thread_id"], data["thread_id"])


if __name__ == "__main__":
    unittest.main()
