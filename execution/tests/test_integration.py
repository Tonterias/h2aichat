#!/usr/bin/env python3
"""
Tests de integracion multi-participante con ThreadPoolExecutor.
"""
import unittest
import tempfile
import shutil
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_concurrent_registration(self):
        def register(i):
            return self.engine.register_participant(f"user_{i}", "tester", "human", f"user_{i}@t.com")

        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(register, i) for i in range(10)]
            results = [f.result() for f in futures]

        participants = self.engine.get_participants()
        self.assertEqual(len(participants), 10)

    def test_turn_race_condition(self):
        for i in range(5):
            self.engine.register_participant(f"user_{i}", "tester", "human", f"u{i}@t.com")

        winners = []

        def try_acquire(i):
            try:
                if self.engine.acquire_turn(f"user_{i}"):
                    winners.append(i)
            except (BlockingIOError, PermissionError, OSError):
                pass

        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(try_acquire, i) for i in range(5)]
            for f in futures:
                f.result()

        self.assertEqual(len(winners), 1, f"Solo 1 debe ganar, ganaron {len(winners)}")
        current = self.engine.get_current_turn()
        self.assertIsNotNone(current)
        self.assertTrue(current.startswith("user_"))

    def test_concurrent_messaging(self):
        self.engine.register_participant("alice", "t1", "human", "a@t")
        self.engine.register_participant("bob", "t2", "bot", "b@t")
        self.engine.register_participant("charlie", "t3", "bot", "c@t")

        self.engine.acquire_turn("alice")
        mid = self.engine.send_message("bob", "Hello Bob", "alice")
        self.engine.release_turn("alice")

        self.engine.acquire_turn("bob")
        mid2 = self.engine.send_message("charlie", "Hello Charlie", "bob")
        self.engine.release_turn("bob")

        self.engine.acquire_turn("charlie")
        mid3 = self.engine.send_message("alice", "Hello Alice", "charlie")
        self.engine.release_turn("charlie")

        self.assertEqual(len(self.engine.get_messages("bob")), 1)
        self.assertEqual(len(self.engine.get_messages("charlie")), 1)
        self.assertEqual(len(self.engine.get_messages("alice")), 1)

    def test_full_conversation_flow(self):
        participants = ["miguel", "gemini", "claude", "qwen", "gemma"]
        for pid in participants:
            ptype = "human" if pid == "miguel" else "bot"
            self.engine.register_participant(pid, "agent", ptype, f"{pid}@h.local")

        self.engine.acquire_turn("miguel")
        self.engine.send_message("gemini", "Start", "miguel")
        self.engine.release_turn("miguel")

        chain = ["gemini", "claude", "qwen", "gemma", "miguel"]
        for i, pid in enumerate(chain):
            self.engine.acquire_turn(pid)
            recipient = chain[(i + 1) % len(chain)]
            self.engine.send_message(recipient, f"msg_{i}", pid)
            self.engine.release_turn(pid)

        for pid in chain:
            msgs = self.engine.get_messages(pid)
            self.assertGreaterEqual(len(msgs), 1, f"{pid} should have messages")

        state = self.engine.read_state()
        self.assertGreaterEqual(len(state.get("turn_history", [])), 6)

    def test_no_message_loss(self):
        self.engine.register_participant("sender", "t", "human", "s@t")
        self.engine.register_participant("receiver", "t", "bot", "r@t")
        self.engine.acquire_turn("sender")

        msg_count = 50
        for i in range(msg_count):
            self.engine.send_message("receiver", f"msg_{i}", "sender")

        self.engine.release_turn("sender")
        msgs = self.engine.get_messages("receiver")
        self.assertEqual(len(msgs), msg_count)

    def test_queue_integrity(self):
        for i in range(20):
            self.engine.register_participant(f"u{i}", "t", "human", f"u{i}@t")

        def add_to_queue(i):
            self.engine.add_to_queue(f"u{i}")

        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(add_to_queue, i) for i in range(20)]
            for f in futures:
                f.result()

        queue = self.engine.get_queue()
        self.assertLessEqual(len(queue), 20)

        while self.engine.get_current_turn() is None and queue:
            self.engine.advance_queue()
            queue = self.engine.get_queue()

        self.assertIsNotNone(self.engine.get_current_turn())

    def test_stress_recovery(self):
        self.engine.register_participant("alice", "t", "human", "a@t")
        self.engine.register_participant("bob", "t", "bot", "b@t")

        self.engine.acquire_turn("alice")
        self.engine.add_to_queue("bob")
        self.engine.set_turn_timeout(0)
        time.sleep(1)

        self.engine.force_release_turn("alice")

        state_after = self.engine.read_state()
        self.assertEqual(state_after.get("current_turn"), "bob")
        self.assertEqual(len(state_after.get("queue", [])), 0)


if __name__ == "__main__":
    unittest.main()
