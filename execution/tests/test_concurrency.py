#!/usr/bin/env python3
"""
Tests de concurrencia real con multiprocessing.
"""
import unittest
import tempfile
import shutil
import time
import sys
from pathlib import Path
from multiprocessing import Process, Queue as MPQueue

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine


def _register_worker(test_dir_str, pid, result_queue):
    try:
        engine = ConversationEngine(base_path=Path(test_dir_str))
        ok = engine.register_participant(pid, "tester", "human", f"{pid}@t.com")
        result_queue.put((pid, ok))
    except Exception as e:
        result_queue.put((pid, f"ERROR: {e}"))


def _turn_worker(test_dir_str, pid, result_queue):
    try:
        engine = ConversationEngine(base_path=Path(test_dir_str))
        ok = engine.acquire_turn(pid)
        result_queue.put((pid, ok))
    except Exception as e:
        result_queue.put((pid, f"ERROR: {e}"))


def _messaging_reader(test_dir_str, pid, result_queue):
    try:
        engine = ConversationEngine(base_path=Path(test_dir_str))
        msgs = engine.get_messages(pid)
        result_queue.put((pid, len(msgs)))
    except Exception as e:
        result_queue.put((pid, f"ERROR: {e}"))


def _stress_worker(test_dir_str, pid, rounds, result_queue):
    try:
        engine = ConversationEngine(base_path=Path(test_dir_str))
        for _ in range(rounds):
            engine.acquire_turn(pid)
            engine.release_turn(pid)
        result_queue.put((pid, "OK"))
    except Exception as e:
        result_queue.put((pid, f"ERROR: {e}"))


class TestConcurrency(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_multi_process_registration(self):
        result_queue = MPQueue()
        test_dir_str = str(self.test_dir)
        processes = []
        for i in range(5):
            p = Process(target=_register_worker, args=(test_dir_str, f"user_{i}", result_queue))
            processes.append(p)
            p.start()

        for p in processes:
            p.join(timeout=10)

        results = []
        while not result_queue.empty():
            results.append(result_queue.get())

        participants = self.engine.get_participants()
        self.assertEqual(len(participants), 5)

    def test_multi_process_turn_race(self):
        self.engine.register_participant("alice", "t", "human", "a@t")
        self.engine.register_participant("bob", "t", "bot", "b@t")
        self.engine.register_participant("eve", "t", "bot", "e@t")

        result_queue = MPQueue()
        test_dir_str = str(self.test_dir)
        processes = []
        for pid in ["alice", "bob", "eve"]:
            p = Process(target=_turn_worker, args=(test_dir_str, pid, result_queue))
            processes.append(p)
            p.start()

        for p in processes:
            p.join(timeout=10)

        winners = 0
        while not result_queue.empty():
            pid, ok = result_queue.get()
            if ok:
                winners += 1

        self.assertEqual(winners, 1, f"Ganaron {winners}, solo 1 debio ganar")
        self.assertIsNotNone(self.engine.get_current_turn())

    def test_multi_process_messaging(self):
        self.engine.register_participant("sender", "t", "human", "s@t")
        self.engine.register_participant("receiver", "t", "bot", "r@t")
        self.engine.acquire_turn("sender")

        msg_count = 50
        for i in range(msg_count):
            self.engine.send_message("receiver", f"msg_{i}", "sender")
        self.engine.release_turn("sender")

        result_queue = MPQueue()
        p = Process(target=_messaging_reader, args=(str(self.test_dir), "receiver", result_queue))
        p.start()
        p.join(timeout=10)

        pid, count = result_queue.get()
        self.assertEqual(count, msg_count, f"Esperados {msg_count}, recibidos {count}")

    def test_process_isolation(self):
        self.engine.register_participant("proc_a", "t", "human", "a@t")
        self.engine.register_participant("proc_b", "t", "bot", "b@t")

        result_queue = MPQueue()
        test_dir_str = str(self.test_dir)

        p1 = Process(target=_turn_worker, args=(test_dir_str, "proc_a", result_queue))
        p2 = Process(target=_turn_worker, args=(test_dir_str, "proc_b", result_queue))
        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)

        winners = 0
        while not result_queue.empty():
            pid, ok = result_queue.get()
            if ok:
                winners += 1

        self.assertEqual(winners, 1)
        current = self.engine.get_current_turn()
        self.assertIn(current, ["proc_a", "proc_b"])

    def test_stress_multi_process(self):
        for i in range(4):
            self.engine.register_participant(f"p{i}", "t", "human", f"p{i}@t")

        result_queue = MPQueue()
        test_dir_str = str(self.test_dir)
        processes = []
        for i in range(4):
            p = Process(target=_stress_worker, args=(test_dir_str, f"p{i}", 5, result_queue))
            processes.append(p)
            p.start()

        for p in processes:
            p.join(timeout=30)

        results = []
        while not result_queue.empty():
            pid, status = result_queue.get()
            results.append((pid, status))

        errors = [r for r in results if r[1] != "OK"]
        self.assertEqual(len(errors), 0, f"Errores: {errors}")

        state = self.engine.read_state()
        self.assertEqual(state.get("state"), "idle")


if __name__ == "__main__":
    unittest.main()
