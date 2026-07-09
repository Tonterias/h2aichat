#!/usr/bin/env python3
"""
Tests para RecoveryDaemon.
"""
import unittest
import tempfile
import shutil
import time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine
from scripts.recovery_daemon import RecoveryDaemon


class TestRecoveryDaemon(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        self.daemon = RecoveryDaemon(base_path=self.test_dir, check_interval=1)
        self.engine.register_participant("miguel", "po", "human", "m@h.local")
        self.engine.register_participant("gemini", "ai", "bot", "g@b.local")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_no_turn_idle(self):
        result = self.daemon.run_once()
        self.assertEqual(len(result["released"]), 0)
        self.assertEqual(len(result["errors"]), 0)

    def test_active_turn_not_touched(self):
        self.engine.acquire_turn("miguel")
        result = self.daemon.run_once()
        state = self.engine.read_state()
        self.assertEqual(state["current_turn"], "miguel")
        self.assertEqual(len(result["released"]), 0)

    def test_expired_turn_released(self):
        self.engine.acquire_turn("miguel")
        self.engine.set_turn_timeout(0)
        time.sleep(1)
        result = self.daemon.run_once()
        state_after = self.engine.read_state()
        self.assertIsNone(state_after["current_turn"])
        self.assertEqual(len(result["released"]), 1)
        self.assertEqual(result["released"][0]["participant"], "miguel")

    def test_expired_turn_advances_queue(self):
        self.engine.acquire_turn("miguel")
        self.engine.add_to_queue("gemini")
        self.engine.set_turn_timeout(0)
        time.sleep(1)
        self.daemon.run_once()
        state_after = self.engine.read_state()
        self.assertEqual(state_after["current_turn"], "gemini")
        self.assertEqual(len(state_after.get("queue", [])), 0)

    def test_errors_logged(self):
        self.engine.acquire_turn("miguel")
        self.engine.set_turn_timeout(0)
        time.sleep(1)
        self.daemon.run_once()
        errors_file = self.test_dir / "errors" / "errors.jsonl"
        self.assertTrue(errors_file.exists())
        with open(errors_file, 'r') as f:
            lines = f.read().strip().split('\n')
        self.assertGreaterEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["component"], "recovery_daemon")


if __name__ == "__main__":
    unittest.main()
