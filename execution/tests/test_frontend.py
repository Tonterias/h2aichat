import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine
from api_server import app
from fastapi.testclient import TestClient


class TestFrontend(unittest.TestCase):
    def setUp(self):
        import api_server
        self.engine = api_server.engine
        self.client = TestClient(app)

    def test_frontend_serves_html(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("<!DOCTYPE html>", resp.text)
        self.assertIn("H2AI Chat", resp.text)

    def test_api_turn_history(self):
        resp = self.client.get("/api/turn-history")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("history", data)
        self.assertIn("queue", data)

    def test_api_participants(self):
        resp = self.client.get("/api/participants")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("participants", data)
        self.assertIsInstance(data["participants"], list)

    def test_frontend_no_500(self):
        resp = self.client.get("/")
        self.assertNotEqual(resp.status_code, 500)

    def test_all_messages_endpoint(self):
        resp = self.client.get("/api/all-messages")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("messages", data)
        self.assertIn("count", data)
        self.assertIsInstance(data["messages"], list)

    def test_html_has_sender_recipient(self):
        resp = self.client.get("/")
        self.assertIn("Conversacion completa", resp.text)
        self.assertIn("CONVERSACIONES", resp.text)


if __name__ == "__main__":
    unittest.main()
