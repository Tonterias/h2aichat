#!/usr/bin/env python3
"""
Benchmarks de rendimiento para HumanIA.
"""
import unittest
import tempfile
import shutil
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine

MSG_THRESHOLD = 1.0
TURN_THRESHOLD = 5.0
RECOVERY_THRESHOLD = 30.0


class TestBenchmark(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_message_throughput(self):
        self.engine.register_participant("alice", "t", "human", "a@t")
        self.engine.register_participant("bob", "t", "bot", "b@t")
        self.engine.acquire_turn("alice")

        msg_count = 100
        start = time.perf_counter()
        for i in range(msg_count):
            self.engine.send_message("bob", f"bench_{i}", "alice")
        elapsed = time.perf_counter() - start
        throughput = msg_count / elapsed

        print(f"  Throughput: {throughput:.1f} msg/s ({msg_count} en {elapsed:.2f}s)")
        self.assertGreater(throughput, MSG_THRESHOLD, f"{throughput:.1f} <= {MSG_THRESHOLD}")

    def test_turn_acquisition_speed(self):
        self.engine.register_participant("alice", "t", "human", "a@t")
        self.engine.register_participant("bob", "t", "bot", "b@t")

        times = []
        for i in range(50):
            start = time.perf_counter()
            self.engine.acquire_turn("alice")
            self.engine.release_turn("alice")
            times.append(time.perf_counter() - start)

        avg = sum(times) / len(times)
        print(f"  Turno avg: {avg*1000:.1f}ms (max: {max(times)*1000:.1f}ms)")
        self.assertLess(avg, TURN_THRESHOLD, f"{avg:.2f}s >= {TURN_THRESHOLD}s")

    def test_recovery_time(self):
        self.engine.register_participant("alice", "t", "human", "a@t")
        self.engine.register_participant("bob", "t", "bot", "b@t")

        self.engine.acquire_turn("alice")
        self.engine.add_to_queue("bob")
        self.engine.set_turn_timeout(0)
        time.sleep(1)

        start = time.perf_counter()
        self.engine.force_release_turn("alice")
        elapsed = time.perf_counter() - start

        print(f"  Recovery: {elapsed*1000:.1f}ms")
        self.assertLess(elapsed, RECOVERY_THRESHOLD, f"{elapsed:.2f}s >= {RECOVERY_THRESHOLD}s")
        self.assertEqual(self.engine.get_current_turn(), "bob")

    def test_lock_contention(self):
        from concurrent.futures import ThreadPoolExecutor
        for i in range(10):
            self.engine.register_participant(f"u{i}", "t", "human", f"u{i}@t")

        errors = []
        def contend(i):
            try:
                if self.engine.acquire_turn(f"u{i}"):
                    self.engine.release_turn(f"u{i}")
            except Exception as e:
                errors.append(str(e))

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(contend, i) for i in range(10)]
            for f in futures:
                f.result(0.5)
        elapsed = time.perf_counter() - start

        print(f"  10 threads: {elapsed:.2f}s, errors: {len(errors)}")
        self.assertEqual(len(errors), 0, f"Errors: {errors}")

    def test_sustained_performance(self):
        self.engine.register_participant("alice", "t", "human", "a@t")
        self.engine.register_participant("bob", "t", "bot", "b@t")

        rounds = 20
        times = []
        for r in range(rounds):
            start = time.perf_counter()
            self.engine.acquire_turn("alice")
            self.engine.send_message("bob", f"round_{r}", "alice")
            self.engine.release_turn("alice")
            times.append(time.perf_counter() - start)

        avg = sum(times) / len(times)
        print(f"  {rounds} rondas: avg={avg*1000:.1f}ms, max={max(times)*1000:.1f}ms")
        self.assertLess(avg, TURN_THRESHOLD, f"Degradacion: {avg:.2f}s >= {TURN_THRESHOLD}s")


if __name__ == "__main__":
    unittest.main()
