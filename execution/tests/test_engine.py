#!/usr/bin/env python3
"""
Tests unitarios para ConversationEngine.
"""
import unittest
import tempfile
import shutil
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine


class TestEngineLocks(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_lock_acquire_release(self):
        lock = self.engine._acquire_lock("test")
        self.assertTrue(Path(lock).exists())
        self.engine._release_lock(lock)
        self.assertFalse(Path(lock).exists())

    def test_double_lock_blocked(self):
        self.engine._acquire_lock("test")
        # FASE 25: el 2º acquire (mismo hilo) ya no entra; con timeout corto falla rapido
        # en vez de colgarse para siempre. Verifica la exclusion mutua.
        with self.assertRaises(BlockingIOError):
            self.engine._acquire_lock("test", timeout=0.3)


class TestEngineParticipants(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_register_participant(self):
        ok = self.engine.register_participant("alice", "tester", "human", "alice@test.com")
        self.assertTrue(ok)
        info = self.engine.get_participant_info("alice")
        self.assertEqual(info["role"], "tester")
        self.assertEqual(info["type"], "human")

    def test_duplicate_registration_blocked(self):
        self.engine.register_participant("alice", "tester", "human", "a@t.com")
        dup = self.engine.register_participant("alice", "x", "x", "x@x")
        self.assertFalse(dup)

    def test_sanitize_invalid_id(self):
        with self.assertRaises(ValueError):
            self.engine.sanitize_participant_id("invalid/id")

    def test_get_participants_list(self):
        self.engine.register_participant("alice", "t1", "human", "a@t")
        self.engine.register_participant("bob", "t2", "bot", "b@t")
        self.assertIn("alice", self.engine.get_participants())
        self.assertIn("bob", self.engine.get_participants())

    def test_update_participant_status(self):
        self.engine.register_participant("alice", "t", "human", "a@t")
        self.engine.update_participant_status("alice", "inactive")
        info = self.engine.get_participant_info("alice")
        self.assertEqual(info["status"], "inactive")

    def test_is_participant_registered(self):
        self.engine.register_participant("alice", "t", "human", "a@t")
        self.assertTrue(self.engine.is_participant_registered("alice"))
        self.assertFalse(self.engine.is_participant_registered("nobody"))


class TestEngineTurns(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        self.engine.register_participant("alice", "t1", "human", "a@t")
        self.engine.register_participant("bob", "t2", "bot", "b@t")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_acquire_turn(self):
        self.assertTrue(self.engine.acquire_turn("alice"))
        self.assertEqual(self.engine.get_current_turn(), "alice")

    def test_acquire_turn_busy(self):
        self.engine.acquire_turn("alice")
        self.assertFalse(self.engine.acquire_turn("bob"))

    def test_release_turn(self):
        self.engine.acquire_turn("alice")
        self.assertTrue(self.engine.release_turn("alice"))
        self.assertIsNone(self.engine.get_current_turn())

    def test_release_not_owner(self):
        self.engine.acquire_turn("alice")
        self.assertFalse(self.engine.release_turn("bob"))

    def test_force_release_advances_queue(self):
        self.engine.acquire_turn("alice")
        self.engine.add_to_queue("bob")
        self.engine.force_release_turn("alice")
        self.assertEqual(self.engine.get_current_turn(), "bob")

    def test_turn_history_recorded(self):
        self.engine.acquire_turn("alice")
        self.engine.release_turn("alice")
        state = self.engine.read_state()
        self.assertGreaterEqual(len(state.get("turn_history", [])), 1)

    def test_turn_expiration(self):
        self.engine.acquire_turn("alice")
        self.engine.set_turn_timeout(0)
        time.sleep(1)
        self.assertTrue(self.engine.is_turn_expired())


class TestEngineMessages(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        self.engine.register_participant("alice", "t1", "human", "a@t")
        self.engine.register_participant("bob", "t2", "bot", "b@t")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_send_message(self):
        self.engine.acquire_turn("alice")
        msg_id = self.engine.send_message("bob", "Hello", "alice")
        self.assertTrue(msg_id.startswith("msg_"))

    def test_send_message_no_turn(self):
        with self.assertRaises(PermissionError):
            self.engine.send_message("alice", "fail", "bob")

    def test_get_messages(self):
        self.engine.acquire_turn("alice")
        self.engine.send_message("bob", "Msg1", "alice")
        self.engine.release_turn("alice")
        msgs = self.engine.get_messages("bob")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["body"], "Msg1")

    def test_unread_filter(self):
        self.engine.acquire_turn("alice")
        self.engine.send_message("bob", "Unread", "alice")
        self.engine.release_turn("alice")
        unread = self.engine.get_messages("bob", unread_only=True)
        self.assertEqual(len(unread), 1)

    def test_mark_as_read(self):
        self.engine.acquire_turn("alice")
        self.engine.send_message("bob", "Read me", "alice")
        self.engine.release_turn("alice")
        msgs = self.engine.get_messages("bob", unread_only=True)
        self.engine.mark_as_read("bob", msgs[0]["message_id"])
        unread_after = self.engine.get_messages("bob", unread_only=True)
        self.assertEqual(len(unread_after), 0)

    def test_get_unread_count(self):
        self.engine.acquire_turn("alice")
        self.engine.send_message("bob", "Test", "alice")
        self.engine.release_turn("alice")
        self.assertEqual(self.engine.get_unread_count("bob"), 1)


class TestEngineQueue(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        self.engine.register_participant("alice", "t1", "human", "a@t")
        self.engine.register_participant("bob", "t2", "bot", "b@t")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_add_to_queue(self):
        self.engine.add_to_queue("alice")
        self.assertIn("alice", self.engine.get_queue())

    def test_cant_queue_when_turn_holder(self):
        self.engine.acquire_turn("alice")
        self.assertFalse(self.engine.add_to_queue("alice"))

    def test_remove_from_queue(self):
        self.engine.add_to_queue("alice")
        self.engine.remove_from_queue("alice")
        self.assertNotIn("alice", self.engine.get_queue())

    def test_queue_position(self):
        self.engine.add_to_queue("alice")
        self.engine.add_to_queue("bob")
        self.assertEqual(self.engine.get_queue_position("alice"), 1)
        self.assertEqual(self.engine.get_queue_position("bob"), 2)

    def test_advance_queue_empty(self):
        self.assertIsNone(self.engine.advance_queue())


if __name__ == "__main__":
    unittest.main()
