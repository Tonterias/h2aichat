import unittest
import tempfile
import shutil
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine
from api_server import app
from fastapi.testclient import TestClient


class TestAPI(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        import api_server
        api_server.engine = self.engine
        self.client = TestClient(app)
        self.engine.register_participant("alice", "t1", "human", "a@t")
        self.engine.register_participant("bob", "t2", "bot", "b@t")

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        import api_server
        api_server.engine = ConversationEngine()

    def test_get_status(self):
        resp = self.client.get("/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("participants", data)

    def test_acquire_turn(self):
        resp = self.client.post("/turn/acquire", json={"participant_id": "alice"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_acquire_turn_busy(self):
        self.client.post("/turn/acquire", json={"participant_id": "alice"})
        resp = self.client.post("/turn/acquire", json={"participant_id": "bob"})
        self.assertFalse(resp.json()["success"])

    def test_release_turn(self):
        self.client.post("/turn/acquire", json={"participant_id": "alice"})
        resp = self.client.post("/turn/release", json={"participant_id": "alice"})
        self.assertTrue(resp.json()["success"])

    def test_send_message(self):
        self.engine.acquire_turn("alice")
        resp = self.client.post("/message/send", json={
            "recipient_id": "bob", "body": "Hello", "sender_id": "alice"
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_send_message_forbidden(self):
        resp = self.client.post("/message/send", json={
            "recipient_id": "alice", "body": "fail", "sender_id": "bob"
        })
        self.assertEqual(resp.status_code, 403)

    def test_get_messages(self):
        self.engine.acquire_turn("alice")
        self.engine.send_message("bob", "Test API", "alice")
        self.engine.release_turn("alice")
        resp = self.client.get("/messages/bob")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)

    def test_mark_as_read(self):
        self.engine.acquire_turn("alice")
        msg_id = self.engine.send_message("bob", "Read", "alice")
        self.engine.release_turn("alice")
        resp = self.client.post(f"/messages/bob/read?message_id={msg_id}")
        self.assertTrue(resp.json()["success"])


class TestWebLegal(unittest.TestCase):
    """FASE 20.1 (mejora PO 2026-06-12): enlaces legales en todas las paginas de /web."""

    def setUp(self):
        self.client = TestClient(app)

    def test_enlaces_legales_en_todas_las_paginas(self):
        resp = self.client.get("/web")
        self.assertEqual(resp.status_code, 200)
        # footer legal en home, about, login, forgot, register + cruces en privacidad/terminos.
        # Los enlaces existen en dos formatos: navTo('...') (misma pestaña) y /web#... (pestaña nueva, en los footers de auth).
        priv = resp.text.count("navTo('privacidad')") + resp.text.count("/web#privacidad")
        term = resp.text.count("navTo('terminos')") + resp.text.count("/web#terminos")
        self.assertGreaterEqual(priv, 7)
        self.assertGreaterEqual(term, 6)

    def test_sin_enlaces_muertos_ni_aviso_cookies(self):
        resp = self.client.get("/web")
        self.assertNotIn("Aviso de Cookies", resp.text)   # no usamos cookies: ese aviso es teatro
        self.assertNotIn(">Accesibilidad<", resp.text)    # enlace muerto retirado

    def test_email_contacto_privacidad_publicado(self):
        resp = self.client.get("/web")
        self.assertIn("contact@h2aichat.com", resp.text)  # decision D4 del PO


class TestConversationVotes(unittest.TestCase):
    """FASE 20.1 (hallazgo UAT PO): pulgares localStorage inyectados al servir conversaciones."""

    def setUp(self):
        self.client = TestClient(app)

    def test_votos_inyectados_en_conversacion(self):
        conv_dir = Path(__file__).parent.parent.parent / "conversations"
        htmls = sorted(conv_dir.glob("*.html"))
        if not htmls:
            self.skipTest("sin conversaciones html en el repo")
        resp = self.client.get(f"/conversations/{htmls[0].name}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("h2aiVoteUp", resp.text)      # boton pulgar arriba
        self.assertIn("h2aiVoteDown", resp.text)    # boton pulgar abajo
        self.assertIn("h2ai_votes", resp.text)      # mismo almacen localStorage que la estatica
        self.assertIn("&larr; Volver", resp.text)   # la nav original sigue presente


class TestFreeModelGuard(unittest.TestCase):
    """RGPD: los modelos 'free' (retienen/entrenan) no deben poder guardarse ni usarse.

    Ver docs/calidad-seguridad-legal/GDPR.md §2.1.
    """

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        import api_server
        api_server.engine = self.engine
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        import api_server
        api_server.engine = ConversationEngine()

    def test_is_free_model(self):
        import api_server
        self.assertTrue(api_server.is_free_model("deepseek-v4-flash-free"))
        self.assertTrue(api_server.is_free_model("some/model:free"))
        self.assertFalse(api_server.is_free_model("deepseek-v4-flash"))
        self.assertFalse(api_server.is_free_model("qwen3.5-plus"))
        self.assertFalse(api_server.is_free_model(""))

    def test_guardar_modelo_de_pago_ok(self):
        cfg = {"deepseek": {"provider": "cloud", "model": "deepseek-v4-flash",
                            "role": "analista", "email": "d@bot", "max_tokens": 800}}
        resp = self.client.post("/api/settings", json={"bots_config": json.dumps(cfg)})
        self.assertEqual(resp.status_code, 200)

    def test_guardar_modelo_free_rechazado(self):
        cfg = {"deepseek": {"provider": "cloud", "model": "deepseek-v4-flash-free",
                            "role": "analista", "email": "d@bot", "max_tokens": 800}}
        resp = self.client.post("/api/settings", json={"bots_config": json.dumps(cfg)})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("free", resp.json()["detail"].lower())
        # y no se persistio
        saved = self.client.get("/api/settings").json()["settings"]["bots_config"]
        self.assertNotIn("deepseek-v4-flash-free", saved)


class TestFeedback(unittest.TestCase):
    """Feedback A/B/C: conversacion (logueado), contacto, reaccion publica (anonima)."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        import api_server, auth
        api_server.engine = self.engine
        auth.init_auth_tables(self.engine)  # crea la tabla feedback
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        import api_server
        api_server.engine = ConversationEngine()

    def test_feedback_conversacion(self):
        r = self.client.post("/api/feedback", json={"kind": "conversation", "conversation_id": "user_1_x", "vote": "up", "comment": "genial"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["success"])

    def test_feedback_contacto(self):
        r = self.client.post("/api/feedback", json={"kind": "contact", "contact_type": "duda", "comment": "cuanto cuesta?", "contact_email": "a@b.com"})
        self.assertEqual(r.status_code, 200)

    def test_feedback_publico_anonimo(self):
        r = self.client.post("/api/feedback", json={"kind": "public", "conversation_id": "Eugenesia.html", "vote": "down"})
        self.assertEqual(r.status_code, 200)

    def test_feedback_validaciones(self):
        self.assertEqual(self.client.post("/api/feedback", json={"kind": "x"}).status_code, 400)
        self.assertEqual(self.client.post("/api/feedback", json={"kind": "conversation", "vote": "maybe"}).status_code, 400)
        self.assertEqual(self.client.post("/api/feedback", json={"kind": "conversation"}).status_code, 400)
        self.assertEqual(self.client.post("/api/feedback", json={"kind": "contact"}).status_code, 400)

    def test_feedback_se_guarda_en_bd(self):
        self.client.post("/api/feedback", json={"kind": "conversation", "conversation_id": "t1", "vote": "up"})
        conn = self.engine._get_conn()
        n = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        conn.close()
        self.assertGreaterEqual(n, 1)

    def test_health_ok(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")


class TestAdminStats(unittest.TestCase):
    """Panel /admin: solo el email administrador (contact@h2aichat.com) ve las stats."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        import api_server, auth
        api_server.engine = self.engine
        auth.init_auth_tables(self.engine)
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        import api_server
        api_server.engine = ConversationEngine()

    def _register(self, email):
        r = self.client.post("/auth/register", json={"email": email, "password": "Test1234!", "name": "X", "accept_terms": True, "confirm_adult": True})
        return r.json().get("token")

    def test_admin_ve_stats(self):
        tok = self._register("contact@h2aichat.com")
        self.assertTrue(tok)
        r = self.client.get("/api/admin/stats", headers={"Authorization": "Bearer " + tok})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        for k in ("users_total", "orq_today", "orq_total", "tokens_total", "tokens_reasoning", "conversaciones", "mensajes", "fb_up", "recientes"):
            self.assertIn(k, d)

    def test_no_admin_403(self):
        tok = self._register("otro@example.com")
        r = self.client.get("/api/admin/stats", headers={"Authorization": "Bearer " + tok})
        self.assertEqual(r.status_code, 403)

    def test_sin_sesion_403(self):
        self.assertEqual(self.client.get("/api/admin/stats").status_code, 403)

    def test_pagina_admin_sirve(self):
        r = self.client.get("/admin")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Panel de control", r.text)


class TestTrialAbuse(unittest.TestCase):
    """Borrarse y re-registrarse con el mismo email NO debe reiniciar los creditos free."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        import auth
        auth.init_auth_tables(self.engine)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_delete_y_reregistro_no_resetea_creditos(self):
        import auth
        e = self.engine
        _, u = auth.register_user(e, "abuso@x.com", "Test1234!", "A", accept_terms=True, confirm_adult=True)
        for _ in range(auth.FREE_DEBATES_PER_MONTH):
            auth.record_debate(e, u, rounds=1, n_bots=2)
        ok, _m = auth.check_free_limits(e, u)
        self.assertFalse(ok)  # limite alcanzado
        self.assertTrue(auth.delete_account(e, u["user_id"]))
        _, u2 = auth.register_user(e, "abuso@x.com", "Test1234!", "A", accept_terms=True, confirm_adult=True)
        self.assertNotEqual(u["user_id"], u2["user_id"])  # cuenta nueva
        ok2, _m2 = auth.check_free_limits(e, u2)
        self.assertFalse(ok2)  # SIGUE limitado: no se reseteo


class TestShareConsent(unittest.TestCase):
    """Opt-in granular de publicación: default privado, consentimiento explícito y revocable."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        import api_server, auth
        api_server.engine = self.engine
        auth.init_auth_tables(self.engine)
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        import api_server
        api_server.engine = ConversationEngine()

    def test_opt_in_y_revocar(self):
        import auth
        tok, u = auth.register_user(self.engine, "a@x.com", "Test1234!", "A", accept_terms=True, confirm_adult=True)
        tid = auth.user_thread_prefix(u["user_id"]) + "demo"
        h = {"Authorization": "Bearer " + tok}
        # default: no compartida
        self.assertNotIn(tid, self.client.get("/api/threads", headers=h).json().get("shared", []))
        # opt-in
        r = self.client.post("/api/conversations/share", json={"thread_id": tid, "consent": True}, headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["shared"])
        self.assertIn(tid, self.client.get("/api/threads", headers=h).json().get("shared", []))
        # revocar
        r2 = self.client.post("/api/conversations/share", json={"thread_id": tid, "consent": False}, headers=h)
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json()["shared"])
        self.assertNotIn(tid, self.client.get("/api/threads", headers=h).json().get("shared", []))

    def test_no_puedes_compartir_hilo_ajeno(self):
        import auth
        tok, _u = auth.register_user(self.engine, "a@x.com", "Test1234!", "A", accept_terms=True, confirm_adult=True)
        r = self.client.post("/api/conversations/share", json={"thread_id": "user_999999_x", "consent": True},
                             headers={"Authorization": "Bearer " + tok})
        self.assertEqual(r.status_code, 403)

    def test_sin_sesion_401(self):
        r = self.client.post("/api/conversations/share", json={"thread_id": "user_1_x", "consent": True})
        self.assertEqual(r.status_code, 401)


class TestSettingsSecurity(unittest.TestCase):
    """Config global y endpoints destructivos: solo admin + topes sanos (PO 2026-06-19)."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        import api_server, auth
        api_server.engine = self.engine
        auth.init_auth_tables(self.engine)
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        import api_server
        api_server.engine = ConversationEngine()

    def _tok(self, email):
        return self.client.post("/auth/register",
                                json={"email": email, "password": "Test1234!", "name": "X", "accept_terms": True, "confirm_adult": True}).json().get("token")

    def test_usuario_normal_no_cambia_settings(self):
        h = {"Authorization": "Bearer " + self._tok("normal@example.com")}
        self.assertEqual(self.client.post("/api/settings", json={"orchestrate_rounds": "3"}, headers=h).status_code, 403)
        self.assertEqual(self.client.post("/api/settings/reset", headers=h).status_code, 403)
        self.assertEqual(self.client.post("/api/reset", headers=h).status_code, 403)
        self.assertEqual(self.client.post("/api/settings/profile?profile=opencode", headers=h).status_code, 403)

    def test_admin_cambia_settings(self):
        h = {"Authorization": "Bearer " + self._tok("contact@h2aichat.com")}
        self.assertEqual(self.client.post("/api/settings", json={"orchestrate_rounds": "5"}, headers=h).status_code, 200)

    def test_topes_rechazan_valores_absurdos(self):
        # sin cabecera -> testclient local = admin/dev; valida los topes
        self.assertEqual(self.client.post("/api/settings", json={"orchestrate_rounds": "99"}).status_code, 400)
        self.assertEqual(self.client.post("/api/settings", json={"llm_max_tokens": "4000"}).status_code, 400)
        self.assertEqual(self.client.post("/api/settings", json={"llm_temperature": "2"}).status_code, 400)
        self.assertEqual(self.client.post("/api/settings", json={"orchestrate_llm_timeout": "3500"}).status_code, 400)
        self.assertEqual(self.client.post("/api/settings", json={"orchestrate_context_limit": "20"}).status_code, 400)
        # dentro de rango -> OK
        self.assertEqual(self.client.post("/api/settings", json={"orchestrate_rounds": "5", "llm_max_tokens": "2000"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
