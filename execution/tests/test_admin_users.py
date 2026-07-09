"""FASE 23 — Tests de gestion de usuarios desde el panel admin.

Cubre las funciones de auth.py (23.1a) y los endpoints /api/admin/users (23.1b),
incluyendo el corte de sesiones vivas al banear (sessions_invalid_before)."""
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


class AdminBase(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        auth.init_auth_tables(self.engine)
        api_server.engine = self.engine
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        os.environ.pop("HUMANIA_AUTH", None)
        api_server.engine = ConversationEngine()

    def mkuser(self, email="ana@test.com", password="secreta123", name="Ana"):
        token, user = auth.register_user(self.engine, email, password, name,
                                         accept_terms=True, confirm_adult=True)
        return token, user["user_id"]


# ── Backend (auth.py) ────────────────────────────────────────────────────────

class TestBackendUsers(AdminBase):
    def test_list_users_devuelve_total_y_uso(self):
        self.mkuser("a@test.com")
        self.mkuser("b@test.com")
        out = auth.list_users(self.engine)
        self.assertEqual(out["total"], 2)
        self.assertEqual(len(out["users"]), 2)
        self.assertIn("debates_month", out["users"][0])
        self.assertIn("plan", out["users"][0])

    def test_list_users_filtra_por_query(self):
        self.mkuser("ana@test.com", name="Ana")
        self.mkuser("beto@test.com", name="Beto")
        out = auth.list_users(self.engine, query="beto")
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["users"][0]["email"], "beto@test.com")

    def test_set_plan_cambia_tarifa(self):
        _, uid = self.mkuser()
        self.assertTrue(auth.set_plan(self.engine, uid, "premium"))
        self.assertEqual(auth.get_user(self.engine, uid)["plan"], "premium")

    def test_set_plan_invalido_lanza(self):
        _, uid = self.mkuser()
        with self.assertRaises(ValueError):
            auth.set_plan(self.engine, uid, "oro")

    def test_set_plan_usuario_inexistente_false(self):
        self.assertFalse(auth.set_plan(self.engine, 9999, "premium"))

    def test_set_status_suspende_y_reactiva(self):
        _, uid = self.mkuser()
        self.assertTrue(auth.set_status(self.engine, uid, "suspended"))
        self.assertEqual(auth.get_user(self.engine, uid)["status"], "suspended")
        self.assertTrue(auth.set_status(self.engine, uid, "active"))
        self.assertEqual(auth.get_user(self.engine, uid)["status"], "active")

    def test_banear_invalida_sesiones_vivas(self):
        """El gotcha del plan: el JWT ya emitido deja de valer al suspender."""
        token, uid = self.mkuser()
        self.assertIsNotNone(auth.decode_token(self.engine, token))  # valido antes
        auth.set_status(self.engine, uid, "suspended")
        self.assertIsNone(auth.decode_token(self.engine, token))     # cortado despues

    def test_reactivar_no_revive_token_viejo(self):
        token, uid = self.mkuser()
        auth.set_status(self.engine, uid, "suspended")
        auth.set_status(self.engine, uid, "active")
        # el sello sessions_invalid_before permanece: el token viejo sigue invalido
        self.assertIsNone(auth.decode_token(self.engine, token))

    def test_reset_usage_borra_mes(self):
        _, uid = self.mkuser()
        auth.record_debate(self.engine, {"user_id": uid, "plan": "free"}, rounds=2, n_bots=3)
        self.assertGreater(auth.get_usage(self.engine, uid)["debates"], 0)
        self.assertTrue(auth.reset_usage(self.engine, uid))
        self.assertEqual(auth.get_usage(self.engine, uid)["debates"], 0)

    def test_admin_verify_email(self):
        _, uid = self.mkuser()
        self.assertEqual(auth.get_user(self.engine, uid)["email_verified"], 0)
        self.assertTrue(auth.admin_verify_email(self.engine, uid))
        self.assertEqual(auth.get_user(self.engine, uid)["email_verified"], 1)

    def test_get_user_detail(self):
        _, uid = self.mkuser()
        d = auth.get_user_detail(self.engine, uid)
        self.assertEqual(d["user_id"], uid)
        self.assertIn("usage_current", d)
        self.assertIn("usage_history", d)
        self.assertIn("feedback", d)

    def test_get_user_detail_inexistente(self):
        self.assertIsNone(auth.get_user_detail(self.engine, 9999))

    def test_admin_create_password_reset(self):
        _, uid = self.mkuser()
        res = auth.admin_create_password_reset(self.engine, uid)
        self.assertIsNotNone(res)
        token, email = res
        self.assertTrue(token)
        self.assertEqual(email, "ana@test.com")

    def test_delete_account_corta_sesiones(self):
        token, uid = self.mkuser()
        self.assertTrue(auth.delete_account(self.engine, uid))
        self.assertIsNone(auth.get_user(self.engine, uid))


# ── Endpoints (api_server.py) ────────────────────────────────────────────────

class TestAdminEndpoints(AdminBase):
    def test_list_users_endpoint(self):
        self.mkuser("a@test.com")
        r = self.client.get("/api/admin/users")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 1)

    def test_no_admin_recibe_403(self):
        token, _ = self.mkuser()  # usuario normal (no admin)
        r = self.client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 403)

    def test_set_plan_endpoint(self):
        _, uid = self.mkuser()
        r = self.client.post(f"/api/admin/users/{uid}/plan", json={"plan": "premium"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(auth.get_user(self.engine, uid)["plan"], "premium")

    def test_set_plan_invalido_400(self):
        _, uid = self.mkuser()
        r = self.client.post(f"/api/admin/users/{uid}/plan", json={"plan": "oro"})
        self.assertEqual(r.status_code, 400)

    def test_set_plan_usuario_inexistente_404(self):
        r = self.client.post("/api/admin/users/9999/plan", json={"plan": "premium"})
        self.assertEqual(r.status_code, 404)

    def test_set_status_endpoint(self):
        _, uid = self.mkuser()
        r = self.client.post(f"/api/admin/users/{uid}/status", json={"status": "suspended"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(auth.get_user(self.engine, uid)["status"], "suspended")

    def test_reset_usage_endpoint(self):
        _, uid = self.mkuser()
        r = self.client.post(f"/api/admin/users/{uid}/reset-usage")
        self.assertEqual(r.status_code, 200)

    def test_verify_email_endpoint(self):
        _, uid = self.mkuser()
        r = self.client.post(f"/api/admin/users/{uid}/verify-email")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(auth.get_user(self.engine, uid)["email_verified"], 1)

    def test_user_detail_endpoint(self):
        _, uid = self.mkuser()
        r = self.client.get(f"/api/admin/users/{uid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user_id"], uid)

    def test_delete_user_endpoint(self):
        _, uid = self.mkuser()
        r = self.client.delete(f"/api/admin/users/{uid}")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(auth.get_user(self.engine, uid))

    def test_plan_limits_get_defaults(self):
        r = self.client.get("/api/admin/plan-limits")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["limits"]["free"]["max_rounds"], 3)
        self.assertEqual(d["limits"]["premium"]["max_rounds"], 20)
        self.assertTrue(d["limits"]["premium"]["openrouter"])
        self.assertFalse(d["limits"]["free"]["openrouter"])
        self.assertTrue(d["fields"])

    def test_plan_limits_guardar_y_releer(self):
        d = self.client.get("/api/admin/plan-limits").json()["limits"]
        d["free"]["max_rounds"] = 2
        d["basic"]["max_models"] = 7
        r = self.client.post("/api/admin/plan-limits", json=d)
        self.assertEqual(r.status_code, 200)
        again = self.client.get("/api/admin/plan-limits").json()["limits"]
        self.assertEqual(again["free"]["max_rounds"], 2)
        self.assertEqual(again["basic"]["max_models"], 7)

    def test_plan_limits_no_admin_403(self):
        token, _ = self.mkuser()
        r = self.client.get("/api/admin/plan-limits", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 403)


class TestUserPrefs(AdminBase):
    def test_set_user_name(self):  # FASE 29
        token, uid = self.mkuser()
        r = self.client.post("/api/me/profile", json={"name": "h2aichat.com"},
                             headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "h2aichat.com")
        self.assertEqual(auth.get_user(self.engine, uid)["name"], "h2aichat.com")

    def test_guardar_prefs_se_acota_al_plan(self):
        token, _ = self.mkuser()  # plan free: rondas≤3, tokens≤800, creatividad≤2
        r = self.client.post("/api/me/prefs", json={"rounds": 99, "max_tokens": 5000, "creativity": 5},
                             headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        p = r.json()["prefs"]
        self.assertEqual(p["rounds"], 3)
        self.assertEqual(p["max_tokens"], 800)
        self.assertEqual(p["creativity"], 2)

    def test_get_prefs_incluye_plan_y_limites(self):
        token, _ = self.mkuser()
        d = self.client.get("/api/me/prefs", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual(d["plan"], "free")
        self.assertEqual(d["limits"]["max_rounds"], 3)
        self.assertTrue(d["creativity_labels"])

    def test_effective_config_usa_pref_acotada(self):
        import api_server
        _, uid = self.mkuser()
        auth.set_user_prefs(self.engine, uid, {"rounds": 99, "creativity": 1})
        settings = self.engine.get_all_settings(api_server.SETTINGS_DEFAULTS)
        eff = api_server.effective_user_config(self.engine, {"user_id": uid, "plan": "free"}, settings)
        self.assertEqual(eff["rounds"], 3)       # acotado a free
        self.assertAlmostEqual(eff["temperature"], 0.5)  # creatividad 1 = equilibrada

    def test_system_prompt_extra_por_usuario(self):  # Opción A: instrucciones extra del usuario
        import api_server
        token, uid = self.mkuser()
        # se guarda y se acota a 2000 chars
        r = self.client.post("/api/me/prefs", json={"system_prompt_extra": "Responde breve. " + "x" * 3000},
                             headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.json()["prefs"]["system_prompt_extra"]), 2000)
        # GET lo devuelve y effective_user_config lo expone para la orquestación
        d = self.client.get("/api/me/prefs", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertIn("Responde breve.", d["prefs"]["system_prompt_extra"])
        settings = self.engine.get_all_settings(api_server.SETTINGS_DEFAULTS)
        eff = api_server.effective_user_config(self.engine, {"user_id": uid, "plan": "free"}, settings)
        self.assertTrue(eff["system_prompt_extra"].startswith("Responde breve."))

    def test_modelos_disponibles_filtrados_por_plan(self):
        token, _ = self.mkuser()  # free: sin OpenRouter
        md = self.client.get("/api/me/models", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertNotIn("openrouter", set(m["provider"] for m in md["available"]))
        self.assertEqual(md["max_models"], 3)
        self.assertFalse(md["openrouter"])

    def test_guardar_modelos_filtra_openrouter_en_free(self):
        token, _ = self.mkuser()
        r = self.client.post("/api/me/prefs", json={"models": ["qwen_plus", "gpt", "minimax"]},
                             headers={"Authorization": f"Bearer {token}"})
        saved = r.json()["prefs"]["models"]
        self.assertIn("qwen_plus", saved)
        self.assertNotIn("gpt", saved)  # OpenRouter: un free no puede

    def test_kimi_lleva_reasoning_effort_none(self):  # FASE: Kimi razona menos
        import api_server
        _, uid = self.mkuser()
        auth.set_user_prefs(self.engine, uid, {"models": ["kimi"]})
        bots = api_server.effective_user_bots(self.engine, {"user_id": uid, "plan": "free"}, {"glob": {}})
        self.assertEqual(bots["kimi"].get("reasoning_effort"), "none")
        self.assertNotIn("reasoning_effort", bots.get("qwen_plus", {}))  # los demas no lo llevan

    def test_effective_user_bots_usa_la_seleccion(self):
        import api_server
        _, uid = self.mkuser()
        auth.set_user_prefs(self.engine, uid, {"models": ["qwen_plus", "deepseek_flash"]})
        bots = api_server.effective_user_bots(self.engine, {"user_id": uid, "plan": "free"}, {"glob": {}})
        self.assertEqual(set(bots.keys()), {"qwen_plus", "deepseek_flash"})


if __name__ == "__main__":
    unittest.main()
