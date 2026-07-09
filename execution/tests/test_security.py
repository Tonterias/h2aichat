"""Tests de seguridad automatizados — HumanIA Contract — FASE 18.2"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from api_server import app
from fastapi.testclient import TestClient


BASE_HTTP = "http://127.0.0.1:8765"


@pytest.fixture
def client():
    import api_server
    original = api_server.engine
    from engine import ConversationEngine
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp())
    api_server.engine = ConversationEngine(base_path=tmp)
    c = TestClient(app)
    c._tmp = tmp
    yield c
    api_server.engine = original
    shutil.rmtree(tmp)


def api_post_raw(path, data, extra_headers=None):
    body = json.dumps(data).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(f"{BASE_HTTP}{path}", data=body, headers=headers, method="POST")
    return urllib.request.urlopen(req)


def api_get_raw(path, extra_headers=None):
    headers = extra_headers or {}
    req = urllib.request.Request(f"{BASE_HTTP}{path}", headers=headers)
    return urllib.request.urlopen(req)


class TestSecurityHeaders:
    """18.2: Verificar security headers en todas las respuestas."""

    def test_nosniff_header(self, client):
        r = client.get("/")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_xfo_header(self, client):
        r = client.get("/")
        assert r.headers.get("x-frame-options") == "DENY"

    def test_referrer_policy(self, client):
        r = client.get("/")
        assert "referrer-policy" in r.headers

    def test_permissions_policy(self, client):
        r = client.get("/")
        assert "permissions-policy" in r.headers

    def test_hsts_not_in_dev(self, client):
        r = client.get("/")
        assert "strict-transport-security" not in r.headers

    def test_csp_header(self, client):
        # FASE 20.1-A2 (+ origenes concretos permitidos tras hallazgo UAT PO 2026-06-12)
        r = client.get("/")
        csp = r.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "connect-src 'self'" in csp
        assert "frame-src https://player.vimeo.com" in csp     # video de la home dinamica
        assert "https://cdn.jsdelivr.net" in csp               # iconos Tabler
        assert "fonts.googleapis" not in csp                   # Google Fonts NO permitido (GDPR)

    def test_csp_on_api_routes(self, client):
        r = client.get("/status")
        assert "default-src 'self'" in r.headers.get("content-security-policy", "")

    def test_headers_on_api_routes(self, client):
        r = client.get("/status")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_headers_on_static(self, client):
        r = client.get("/static/marked.min.js")
        assert r.headers.get("x-content-type-options") == "nosniff"


class TestAuthRequired:
    """18.2: Auth middleware — 401 sin token en conexion externa."""

    def test_public_status_no_auth(self, client):
        r = client.get("/status")
        assert r.status_code == 200

    def test_protected_api_works_localhost(self, client):
        r = client.get("/api/turn-history")
        assert r.status_code == 200

    def test_protected_turn_works_localhost(self, client):
        client.post("/api/settings", json={"bots_config": json.dumps({"x": {"model": "x", "provider": "local", "role": "test", "email": "x@test.local", "max_tokens": 100}})})
        r = client.post("/orchestrate?rounds=0", json={
            "recipient_id": "x", "body": "test", "sender_id": "miguel", "thread_id": "sec"
        })
        assert r.status_code == 200

    def test_protected_message_works_localhost(self, client):
        r = client.post("/message/send", json={
            "recipient_id": "x", "body": "test", "sender_id": "x", "thread_id": "x"
        })
        assert r.status_code in (200, 400, 403)

    def test_orchestrate_works_localhost(self, client):
        r = client.post("/orchestrate?rounds=0", json={
            "recipient_id": "x", "body": "test", "sender_id": "miguel", "thread_id": "x"
        })
        assert r.status_code in (200, 400, 422)

    def test_localhost_bypass(self, server):
        r = api_get_raw("/api/turn-history")
        assert r.status == 200


class TestInputValidation:
    """18.2: Validacion de entrada — max_length, tipos, JSON."""

    def test_body_max_length_rejected(self, client):
        body = "A" * 20000
        r = client.post("/message/send", json={
            "recipient_id": "x", "body": body, "sender_id": "x", "thread_id": "x"
        })
        assert r.status_code == 422

    def test_body_normal_accepted(self, client):
        r = client.post("/message/send", json={
            "recipient_id": "x", "body": "hello", "sender_id": "x", "thread_id": "x"
        })
        assert r.status_code in (200, 400, 403)

    def test_body_boundary_9k(self, client):
        body = "A" * 9000
        r = client.post("/message/send", json={
            "recipient_id": "x", "body": body, "sender_id": "x", "thread_id": "x"
        })
        assert r.status_code in (200, 400, 403)

    def test_import_max_length_rejected(self, client):
        html = "X" * 6_000_000
        r = client.post("/api/import", json={"html": html})
        assert r.status_code == 422

    def test_import_normal_accepted(self, client):
        r = client.post("/api/import", json={"html": "<html></html>"})
        assert r.status_code in (200, 400)

    def test_settings_invalid_json(self, client):
        r = client.post("/api/settings", json={"bots_config": "not valid json{{{--"})
        assert r.status_code == 400
        data = r.json()
        assert "bots_config" in str(data.get("detail", ""))

    def test_settings_non_numeric(self, client):
        r = client.post("/api/settings", json={"orchestrate_rounds": "abc"})
        assert r.status_code == 400
        data = r.json()
        assert "numerico" in str(data.get("detail", ""))

    def test_settings_valid(self, client):
        r = client.post("/api/settings", json={"orchestrate_rounds": "5"})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_settings_valid_bots_config(self, client):
        r = client.post("/api/settings", json={"bots_config": json.dumps({"test_bot": {"model": "x", "provider": "local", "role": "test"}})})
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestInjectionPrevention:
    """18.2: Prevencion de inyecciones."""

    def test_sql_injection_params_safe(self, client):
        r = client.get("/messages/x", params={"thread_id": "' OR 1=1 --"})
        assert r.status_code in (200, 400)

    def test_xss_in_messages_safe(self, client):
        r = client.get("/messages/bob", params={"thread_id": "<script>alert(1)</script>"})
        assert r.status_code in (200, 400)

    def test_path_traversal_blocked(self, client):
        r = client.get("/conversations/../../../etc/passwd")
        assert r.status_code == 404

    def test_path_traversal_html_only(self, client):
        r = client.get("/conversations/test.txt")
        assert r.status_code == 404


class TestRateLimiting:
    """18.2: Rate limiting en /orchestrate (solo en servidor real)."""

    def test_rate_limit_localhost_not_applied(self, client):
        for _ in range(15):
            r = client.post("/orchestrate?rounds=0", json={
                "recipient_id": "x", "body": "fuzz", "sender_id": "miguel", "thread_id": "x"
            })
            assert r.status_code in (200, 400, 422)
