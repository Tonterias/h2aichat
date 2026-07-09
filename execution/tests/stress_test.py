#!/usr/bin/env python3
"""
Stress test: 100 turnos + 1000 mensajes sin deadlocks.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine


def stress_test():
    import tempfile
    import shutil

    test_dir = Path(tempfile.mkdtemp())
    engine = ConversationEngine(base_path=test_dir)

    engine.register_participant("alice", "t1", "human", "a@t")
    engine.register_participant("bob", "t2", "bot", "b@t")

    print("=== STRESS TEST ===")

    print("100 turnos consecutivos...")
    start = time.time()
    for i in range(100):
        pid = "alice" if i % 2 == 0 else "bob"
        engine.acquire_turn(pid)
        engine.release_turn(pid)
    turn_time = time.time() - start
    print(f"  {100} turnos en {turn_time:.2f}s ({100/turn_time:.0f} turnos/s)")

    print("1000 mensajes...")
    engine.acquire_turn("alice")
    start = time.time()
    for i in range(1000):
        engine.send_message("bob", f"msg_{i}", "alice")
    msg_time = time.time() - start
    engine.release_turn("alice")
    print(f"  1000 mensajes en {msg_time:.2f}s ({1000/msg_time:.0f} msg/s)")

    msgs = engine.get_messages("bob")
    print(f"  Mensajes recibidos: {len(msgs)}")

    state = engine.read_state()
    history = state.get("turn_history", [])
    print(f"  Turnos en historial: {len(history)}")

    assert len(msgs) == 1000, f"Expected 1000 messages, got {len(msgs)}"
    assert len(history) >= 100, f"Expected >=100 turns, got {len(history)}"
    assert state.get("state") == "idle"

    shutil.rmtree(test_dir)
    print("STRESS TEST PASSED")
    return True


if __name__ == "__main__":
    success = stress_test()
    sys.exit(0 if success else 1)
