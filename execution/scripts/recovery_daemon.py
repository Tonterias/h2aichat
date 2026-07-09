#!/usr/bin/env python3
"""
HumanIA - Recovery Daemon
Recupera turnos expirados automaticamente.
"""
import sys
import time
import json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine


class RecoveryDaemon:
    def __init__(self, base_path: Path = None, check_interval: int = 30):
        self.base_path = base_path or Path(__file__).parent.parent.parent
        self.engine = ConversationEngine(base_path=self.base_path)
        self.check_interval = check_interval
        self.running = False
        self.errors_dir = self.base_path / "errors"
        self.errors_dir.mkdir(parents=True, exist_ok=True)
        self.errors_file = self.errors_dir / "errors.jsonl"

    def _log(self, action: str, detail: str):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": "recovery_daemon",
            "action": action,
            "detail": detail
        }
        with open(self.errors_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')

    def run_once(self) -> dict:
        result = {"released": [], "errors": []}
        try:
            # FASE 24: el turno es por conversacion -> revisar TODAS las conversaciones activas
            for st in self.engine.read_all_states():
                thread = st.get("thread_id", "general")
                current = st.get("current_turn")
                if current is None:
                    continue
                if self.engine.is_turn_expired(thread):
                    self.engine.force_release_turn(current, thread)
                    result["released"].append({
                        "participant": current,
                        "thread_id": thread,
                        "action": "force_released",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    self._log("force_release", f"Turno expirado de {current} (hilo {thread}) liberado")
        except Exception as e:
            result["errors"].append(str(e))
            self._log("error", str(e))
        return result

    def start(self):
        self.running = True
        print(f"[DAEMON] Recovery Daemon iniciado (intervalo: {self.check_interval}s)")
        self._log("started", f"interval={self.check_interval}s")
        try:
            while self.running:
                result = self.run_once()
                if result["released"]:
                    for r in result["released"]:
                        print(f"[DAEMON] Turno expirado liberado: {r['participant']}")
                time.sleep(self.check_interval)
        except KeyboardInterrupt:
            print("\n[DAEMON] Detenido por el usuario")
        finally:
            self.running = False
            self._log("stopped", "daemon detenido")

    def stop(self):
        self.running = False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HumanIA Recovery Daemon")
    parser.add_argument("--once", action="store_true", help="Ejecutar un ciclo y salir")
    parser.add_argument("--interval", type=int, default=30, help="Intervalo en segundos")
    args = parser.parse_args()

    daemon = RecoveryDaemon(check_interval=args.interval)
    if args.once:
        result = daemon.run_once()
        print(json.dumps(result, indent=2))
    else:
        daemon.start()
