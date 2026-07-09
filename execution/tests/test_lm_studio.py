#!/usr/bin/env python3
"""
Tests para LMStudioClient con mock de requests.
"""
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lm_studio import LMStudioClient, LMStudioError


class TestLMStudioClient(unittest.TestCase):
    def setUp(self):
        self.client = LMStudioClient()

    @patch('lm_studio.requests.Session.get')
    def test_health_check_ok(self, mock_get):
        mock_get.return_value.status_code = 200
        self.assertTrue(self.client.health_check())

    @patch('lm_studio.requests.Session.get')
    def test_health_check_fail(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        self.assertFalse(self.client.health_check())

    @patch('lm_studio.requests.Session.get')
    def test_list_models(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"data": [{"id": "model-a"}, {"id": "model-b"}]}
        mock_get.return_value = mock_resp
        models = self.client.list_models()
        self.assertEqual(models, ["model-a", "model-b"])

    @patch('lm_studio.requests.Session.post')
    def test_chat_completion(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Hola"}}],
            "model": "test-model",
            "usage": {}
        }
        mock_post.return_value = mock_resp
        result = self.client.chat_completion([{"role": "user", "content": "hi"}])
        self.assertEqual(result["content"], "Hola")

    @patch('lm_studio.requests.Session.post')
    def test_connection_error_retry(self, mock_post):
        mock_post.side_effect = ConnectionError("fail")
        with self.assertRaises(LMStudioError):
            self.client.chat_completion([{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()
