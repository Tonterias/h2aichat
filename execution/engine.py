#!/usr/bin/env python3
"""
HumanIA - Conversation Engine (SQLite)
"""
import sqlite3
import re
import os
import time
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


class ConversationEngine:
    LOCK_DIR = ".locks"
    DB_FILE = "humania.db"
    LOCK_TIMEOUT = 10.0  # FASE 25: tope para el lock entre hilos (sección crítica es sub-ms; nunca colgar)

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or Path(__file__).parent.parent
        self.memory_dir = self.base_path / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.memory_dir / self.DB_FILE
        self.lock_dir = self.memory_dir / self.LOCK_DIR
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self._lockwait = threading.local()  # FASE 25: espera de lock acumulada por hilo/petición (métrica C)
        self._thread_lock = threading.Lock()  # FASE 25: serializa HILOS del proceso (justo, sin inanición)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS participants (
                id TEXT PRIMARY KEY, role TEXT, type TEXT, email TEXT,
                status TEXT DEFAULT 'active', public_key TEXT,
                registered_at TEXT, last_seen TEXT, provider TEXT DEFAULT 'local'
            );
            CREATE TABLE IF NOT EXISTS turns (
                thread_id TEXT PRIMARY KEY,
                current_turn TEXT, state TEXT DEFAULT 'idle',
                started_at TEXT, max_duration INTEGER DEFAULT 300,
                stop_flag INTEGER DEFAULT 0,
                FOREIGN KEY (current_turn) REFERENCES participants(id)
            );
            CREATE TABLE IF NOT EXISTS turn_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant TEXT, started TEXT, ended TEXT,
                force_released INTEGER DEFAULT 0, thread_id TEXT DEFAULT 'general'
            );
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id TEXT, position INTEGER, thread_id TEXT DEFAULT 'general'
            );
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY, sender TEXT, recipient TEXT,
                body TEXT, timestamp TEXT, sequence INTEGER,
                read INTEGER DEFAULT 0, content_type TEXT DEFAULT 'text/plain',
                thread_id TEXT DEFAULT 'general'
            );
            CREATE INDEX IF NOT EXISTS idx_msg_thread ON messages(thread_id);
            CREATE INDEX IF NOT EXISTS idx_msg_recipient ON messages(recipient);
            CREATE INDEX IF NOT EXISTS idx_msg_timestamp ON messages(timestamp);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT
            );
        """)
        self._migrate_schema(conn)
        conn.commit()
        conn.close()

    def _migrate_schema(self, conn):
        """FASE 24: turno/cola/historial pasan de GLOBALES a estar indexados por
        thread_id. Migración idempotente que preserva la fila única como hilo 'general'."""
        tcols = [r[1] for r in conn.execute("PRAGMA table_info(turns)").fetchall()]
        if tcols and "thread_id" not in tcols:
            # Esquema viejo (fila unica CHECK id=1) -> recrear por thread_id
            has_stop = "stop_flag" in tcols
            old = conn.execute(
                "SELECT current_turn, state, started_at, max_duration"
                + (", stop_flag" if has_stop else "") + " FROM turns WHERE id=1").fetchone()
            conn.execute("""
                CREATE TABLE turns_new (
                    thread_id TEXT PRIMARY KEY,
                    current_turn TEXT, state TEXT DEFAULT 'idle',
                    started_at TEXT, max_duration INTEGER DEFAULT 300,
                    stop_flag INTEGER DEFAULT 0,
                    FOREIGN KEY (current_turn) REFERENCES participants(id)
                )
            """)
            if old:
                conn.execute(
                    "INSERT INTO turns_new (thread_id, current_turn, state, started_at, max_duration, stop_flag) "
                    "VALUES ('general',?,?,?,?,?)",
                    (old["current_turn"], old["state"], old["started_at"], old["max_duration"],
                     (old["stop_flag"] if has_stop else 0)))
            conn.execute("DROP TABLE turns")
            conn.execute("ALTER TABLE turns_new RENAME TO turns")
        qcols = [r[1] for r in conn.execute("PRAGMA table_info(queue)").fetchall()]
        if qcols and "thread_id" not in qcols:
            conn.execute("ALTER TABLE queue ADD COLUMN thread_id TEXT DEFAULT 'general'")
        hcols = [r[1] for r in conn.execute("PRAGMA table_info(turn_history)").fetchall()]
        if hcols and "thread_id" not in hcols:
            conn.execute("ALTER TABLE turn_history ADD COLUMN thread_id TEXT DEFAULT 'general'")

    @staticmethod
    def _norm_thread(thread_id: str) -> str:
        """Normaliza el thread_id para clave de turno/cola. Vacío -> 'general'; cap 128."""
        t = (thread_id or "general").strip() or "general"
        return t[:128]

    def _ensure_turn_row(self, conn, thread_id: str):
        conn.execute("INSERT OR IGNORE INTO turns (thread_id, state, max_duration, stop_flag) "
                     "VALUES (?, 'idle', 300, 0)", (thread_id,))

    def _acquire_lock(self, lock_name: str = "turnfile", timeout: float = None) -> str:
        # FASE 25: bajo concurrencia, varios HILOS competian por el mismo os.mkdir y agotaban
        # los reintentos -> BlockingIOError -> HTTP 500 (lo destapo la prueba de tiempos con 2
        # conversaciones). Ahora los hilos del proceso se serializan con un Lock JUSTO (sin
        # inanicion) y CON timeout (ante un doble-acquire o un bug falla fuerte, nunca cuelga).
        # os.mkdir queda solo para exclusion ENTRE PROCESOS (servidor vs recovery_daemon), donde
        # la contencion es minima y breve.
        _t0 = time.time()
        if not self._thread_lock.acquire(timeout=(self.LOCK_TIMEOUT if timeout is None else timeout)):
            raise BlockingIOError(f"No se pudo adquirir lock '{lock_name}' (hilos) a tiempo")
        try:
            lock_path = self.lock_dir / f"{lock_name}.lock"
            for attempt in range(30):  # solo contencion ENTRE PROCESOS, que es breve
                try:
                    os.mkdir(lock_path)
                    self._add_lockwait((time.time() - _t0) * 1000)  # FASE 25: métrica C (contención)
                    return str(lock_path)
                except (FileExistsError, PermissionError):  # Windows lanza ambos (leccion conocida)
                    time.sleep(0.05)
            raise BlockingIOError(f"No se pudo adquirir lock '{lock_name}' (proceso) despues de 30 intentos")
        except BaseException:
            self._thread_lock.release()
            raise

    def _release_lock(self, lock_path: str):
        try:
            if os.path.exists(lock_path):
                os.rmdir(lock_path)
        finally:
            self._thread_lock.release()

    # FASE 25: medición de espera del lock (métrica C). Thread-local: cada petición /orchestrate
    # corre en su propio hilo del threadpool de FastAPI, así no se mezclan conversaciones.
    def lockwait_reset(self):
        self._lockwait.ms = 0.0

    def lockwait_ms(self) -> float:
        return getattr(self._lockwait, "ms", 0.0)

    def _add_lockwait(self, ms: float):
        self._lockwait.ms = getattr(self._lockwait, "ms", 0.0) + ms

    def read_state(self, thread_id: str = "general") -> Dict[str, Any]:
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
        participants = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM participants").fetchall()}
        queue = [r["participant_id"] for r in conn.execute(
            "SELECT participant_id FROM queue WHERE thread_id=? ORDER BY position", (thread_id,)).fetchall()]
        history = [dict(r) for r in conn.execute(
            "SELECT * FROM turn_history WHERE thread_id=?", (thread_id,)).fetchall()]
        conn.close()
        return {
            "version": "2.0",
            "state": row["state"] if row else "idle",
            "current_turn": row["current_turn"] if row else None,
            "current_turn_started": row["started_at"] if row else None,
            "queue": queue,
            "max_turn_duration_minutes": (row["max_duration"] if row else 300) / 60,
            "turn_history": history,
            "participants": participants
        }

    def get_current_turn(self, thread_id: str = "general") -> Optional[str]:
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        row = conn.execute("SELECT current_turn FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
        conn.close()
        return row["current_turn"] if row else None

    def acquire_turn(self, participant_id: str, thread_id: str = "general") -> bool:
        thread_id = self._norm_thread(thread_id)
        lock = self._acquire_lock()
        try:
            pid = self.sanitize_participant_id(participant_id)
            conn = self._get_conn()
            self._ensure_turn_row(conn, thread_id)
            row = conn.execute("SELECT current_turn FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
            if row["current_turn"] is not None:
                conn.close()
                return False
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE turns SET current_turn=?, state='active', started_at=? WHERE thread_id=?",
                         (pid, now, thread_id))
            conn.commit()
            conn.close()
            return True
        finally:
            self._release_lock(lock)

    def release_turn(self, participant_id: str, thread_id: str = "general") -> bool:
        thread_id = self._norm_thread(thread_id)
        lock = self._acquire_lock()
        try:
            pid = self.sanitize_participant_id(participant_id)
            conn = self._get_conn()
            row = conn.execute("SELECT current_turn, started_at FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
            if not row or row["current_turn"] != pid:
                conn.close()
                return False
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("INSERT INTO turn_history (participant, started, ended, force_released, thread_id) VALUES (?,?,?,0,?)",
                         (pid, row["started_at"], now, thread_id))
            conn.execute("UPDATE turns SET current_turn=NULL, started_at=NULL, state='idle' WHERE thread_id=?", (thread_id,))
            conn.commit()
            conn.close()
            return True
        finally:
            self._release_lock(lock)

    def add_to_queue(self, participant_id: str, thread_id: str = "general") -> bool:
        thread_id = self._norm_thread(thread_id)
        lock = self._acquire_lock()
        try:
            pid = self.sanitize_participant_id(participant_id)
            conn = self._get_conn()
            row = conn.execute("SELECT current_turn FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
            if row and row["current_turn"] == pid:
                conn.close()
                return False
            if conn.execute("SELECT 1 FROM queue WHERE participant_id=? AND thread_id=?", (pid, thread_id)).fetchone():
                conn.close()
                return False
            if not conn.execute("SELECT 1 FROM participants WHERE id=?", (pid,)).fetchone():
                conn.close()
                return False
            max_pos = conn.execute("SELECT MAX(position) FROM queue WHERE thread_id=?", (thread_id,)).fetchone()[0] or 0
            conn.execute("INSERT INTO queue (participant_id, position, thread_id) VALUES (?,?,?)", (pid, max_pos + 1, thread_id))
            conn.commit()
            conn.close()
            return True
        finally:
            self._release_lock(lock)

    def remove_from_queue(self, participant_id: str, thread_id: str = "general") -> bool:
        thread_id = self._norm_thread(thread_id)
        lock = self._acquire_lock()
        try:
            pid = self.sanitize_participant_id(participant_id)
            conn = self._get_conn()
            if not conn.execute("SELECT 1 FROM queue WHERE participant_id=? AND thread_id=?", (pid, thread_id)).fetchone():
                conn.close()
                return False
            conn.execute("DELETE FROM queue WHERE participant_id=? AND thread_id=?", (pid, thread_id))
            conn.commit()
            conn.close()
            return True
        finally:
            self._release_lock(lock)

    def get_queue(self, thread_id: str = "general") -> List[str]:
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        rows = conn.execute("SELECT participant_id FROM queue WHERE thread_id=? ORDER BY position", (thread_id,)).fetchall()
        conn.close()
        return [r["participant_id"] for r in rows]

    def get_queue_position(self, participant_id: str, thread_id: str = "general") -> Optional[int]:
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        row = conn.execute("SELECT position FROM queue WHERE participant_id=? AND thread_id=?", (participant_id, thread_id)).fetchone()
        conn.close()
        return row["position"] if row else None

    def is_in_queue(self, participant_id: str, thread_id: str = "general") -> bool:
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        exists = conn.execute("SELECT 1 FROM queue WHERE participant_id=? AND thread_id=?", (participant_id, thread_id)).fetchone()
        conn.close()
        return exists is not None

    def clear_queue(self, thread_id: str = "general") -> None:
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        conn.execute("DELETE FROM queue WHERE thread_id=?", (thread_id,))
        conn.commit()
        conn.close()

    def is_turn_expired(self, thread_id: str = "general") -> bool:
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        row = conn.execute("SELECT current_turn, started_at, max_duration FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
        conn.close()
        if not row or row["current_turn"] is None or row["started_at"] is None:
            return False
        started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - started).total_seconds()
        return age > row["max_duration"]

    def force_release_turn(self, participant_id: str, thread_id: str = "general") -> bool:
        thread_id = self._norm_thread(thread_id)
        lock = self._acquire_lock()
        try:
            pid = self.sanitize_participant_id(participant_id)
            conn = self._get_conn()
            row = conn.execute("SELECT current_turn, started_at FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
            if not row or row["current_turn"] != pid:
                conn.close()
                return False
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("INSERT INTO turn_history (participant, started, ended, force_released, thread_id) VALUES (?,?,?,1,?)",
                         (pid, row["started_at"], now, thread_id))
            next_row = conn.execute("SELECT participant_id FROM queue WHERE thread_id=? ORDER BY position LIMIT 1", (thread_id,)).fetchone()
            if next_row:
                conn.execute("UPDATE turns SET current_turn=?, started_at=?, state='active' WHERE thread_id=?", (next_row["participant_id"], now, thread_id))
                conn.execute("DELETE FROM queue WHERE participant_id=? AND thread_id=?", (next_row["participant_id"], thread_id))
            else:
                conn.execute("UPDATE turns SET current_turn=NULL, started_at=NULL, state='idle' WHERE thread_id=?", (thread_id,))
            conn.commit()
            conn.close()
            return True
        finally:
            self._release_lock(lock)

    def get_turn_time_remaining(self, thread_id: str = "general") -> Optional[float]:
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        row = conn.execute("SELECT current_turn, started_at, max_duration FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
        conn.close()
        if not row or row["current_turn"] is None or row["started_at"] is None:
            return None
        started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - started).total_seconds()
        return max(0, row["max_duration"] - age)

    def advance_queue(self, thread_id: str = "general") -> Optional[str]:
        thread_id = self._norm_thread(thread_id)
        lock = self._acquire_lock()
        try:
            conn = self._get_conn()
            self._ensure_turn_row(conn, thread_id)
            row = conn.execute("SELECT current_turn, started_at FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
            if row and row["current_turn"] is not None:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute("INSERT INTO turn_history (participant, started, ended, thread_id) VALUES (?,?,?,?)",
                             (row["current_turn"], row["started_at"], now, thread_id))
            next_row = conn.execute("SELECT participant_id FROM queue WHERE thread_id=? ORDER BY position LIMIT 1", (thread_id,)).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if next_row:
                conn.execute("UPDATE turns SET current_turn=?, started_at=?, state='active' WHERE thread_id=?", (next_row["participant_id"], now, thread_id))
                conn.execute("DELETE FROM queue WHERE participant_id=? AND thread_id=?", (next_row["participant_id"], thread_id))
                conn.commit()
                conn.close()
                return next_row["participant_id"]
            else:
                conn.execute("UPDATE turns SET current_turn=NULL, started_at=NULL, state='idle' WHERE thread_id=?", (thread_id,))
                conn.commit()
                conn.close()
                return None
        finally:
            self._release_lock(lock)

    def get_next_in_queue(self, thread_id: str = "general") -> Optional[str]:
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        row = conn.execute("SELECT participant_id FROM queue WHERE thread_id=? ORDER BY position LIMIT 1", (thread_id,)).fetchone()
        conn.close()
        return row["participant_id"] if row else None

    def sanitize_participant_id(self, participant_id: str) -> str:
        # FASE 31: se admiten emails como id (el moderador es por-usuario = su email), por eso
        # el charset incluye @ . + - además de alfanuméricos y _. Solo va a la BD (por parámetros,
        # sin riesgo de inyección) y a JSON, nunca a rutas de fichero.
        if not re.match(r'^[a-zA-Z0-9_@.+\-]+$', participant_id):
            raise ValueError(f"Invalid participant_id '{participant_id}': must match ^[a-zA-Z0-9_@.+-]+$")
        if len(participant_id) > 254:
            raise ValueError(f"participant_id '{participant_id}' exceeds 254 characters")
        return participant_id

    def register_participant(self, participant_id: str, role: str, participant_type: str,
                             email: str, public_key: str = None, provider: str = "local") -> bool:
        lock = self._acquire_lock()
        try:
            pid = self.sanitize_participant_id(participant_id)
            conn = self._get_conn()
            if conn.execute("SELECT 1 FROM participants WHERE id=?", (pid,)).fetchone():
                conn.close()
                return False
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("INSERT INTO participants (id,role,type,email,status,public_key,registered_at,last_seen,provider) VALUES (?,?,?,?,?,?,?,?,?)",
                         (pid, role, participant_type, email, "active", public_key, now, now, provider))
            conn.commit()
            conn.close()
            return True
        finally:
            self._release_lock(lock)

    def unregister_participant(self, participant_id: str) -> bool:
        lock = self._acquire_lock()
        try:
            pid = self.sanitize_participant_id(participant_id)
            conn = self._get_conn()
            if not conn.execute("SELECT 1 FROM participants WHERE id=?", (pid,)).fetchone():
                conn.close()
                return False
            conn.execute("DELETE FROM participants WHERE id=?", (pid,))
            conn.commit()
            conn.close()
            return True
        finally:
            self._release_lock(lock)

    def set_participant_active(self, participant_id: str) -> bool:
        """FASE 27: reactivar un bot (p. ej. uno de OpenRouter que un perfil marco inactivo,
        pero que un usuario premium ha elegido). Su seleccion manda sobre el estado global."""
        conn = self._get_conn()
        if not conn.execute("SELECT 1 FROM participants WHERE id=?", (participant_id,)).fetchone():
            conn.close()
            return False
        conn.execute("UPDATE participants SET status='active' WHERE id=?", (participant_id,))
        conn.commit()
        conn.close()
        return True

    def set_participant_inactive(self, participant_id: str) -> bool:
        """FASE 27: apagar un bot sin borrarlo (reversible). Se usa para los fantasmas
        de perfiles antiguos (ids fuera del catalogo) que salian 'activos' con 0 turnos."""
        conn = self._get_conn()
        if not conn.execute("SELECT 1 FROM participants WHERE id=?", (participant_id,)).fetchone():
            conn.close()
            return False
        conn.execute("UPDATE participants SET status='inactive' WHERE id=?", (participant_id,))
        conn.commit()
        conn.close()
        return True

    def backup_db(self, keep: int = 10):
        """FASE 28: copia EN CALIENTE de la BD (API .backup de sqlite3, segura con WAL
        aunque haya tráfico) a memory/backups/. Conserva las últimas `keep`.
        Devuelve (ruta, tamaño_bytes)."""
        backups_dir = self.memory_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = backups_dir / f"humania_{ts}.db"
        src = self._get_conn()
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        files = sorted(backups_dir.glob("humania_*.db"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[int(keep):]:
            try:
                f.unlink()
            except OSError:
                pass
        return str(dest), dest.stat().st_size

    def get_participants(self) -> List[str]:
        conn = self._get_conn()
        rows = conn.execute("SELECT id FROM participants").fetchall()
        conn.close()
        return [r["id"] for r in rows]

    def get_participant_info(self, participant_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM participants WHERE id=?", (participant_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def update_participant_status(self, participant_id: str, status: str) -> bool:
        valid = ['active', 'inactive', 'pending']
        if status not in valid:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {valid}")
        conn = self._get_conn()
        if not conn.execute("SELECT 1 FROM participants WHERE id=?", (participant_id,)).fetchone():
            conn.close()
            return False
        conn.execute("UPDATE participants SET status=?, last_seen=? WHERE id=?",
                     (status, datetime.now(timezone.utc).isoformat(), participant_id))
        conn.commit()
        conn.close()
        return True

    def is_participant_registered(self, participant_id: str) -> bool:
        conn = self._get_conn()
        exists = conn.execute("SELECT 1 FROM participants WHERE id=?", (participant_id,)).fetchone()
        conn.close()
        return exists is not None

    def send_message(self, recipient_id: str, body: str, sender_id: str = None,
                     thread_id: str = "general") -> str:
        lock = self._acquire_lock()
        try:
            conn = self._get_conn()
            if sender_id is None:
                row = conn.execute("SELECT current_turn FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
                sender_id = row["current_turn"] if row else None
                if sender_id is None:
                    conn.close()
                    raise PermissionError("No active turn to send messages")
            ct_row = conn.execute("SELECT current_turn FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
            current_turn = ct_row["current_turn"] if ct_row else None
            # FASE 31: el MODERADOR está exento de tener el turno (puede intervenir cuando quiera).
            # Antes se cableaba el id 'miguel'; ahora el moderador es por-usuario (su email), así que
            # se identifica por ROL/tipo (moderador/human), no por un id fijo.
            _is_mod = conn.execute("SELECT 1 FROM participants WHERE id=? AND (role='moderador' OR type='human')",
                                   (sender_id,)).fetchone()
            if sender_id != current_turn and not _is_mod:
                conn.close()
                raise PermissionError(f"Participant '{sender_id}' does not have the turn")
            if not conn.execute("SELECT 1 FROM participants WHERE id=?", (recipient_id,)).fetchone():
                conn.close()
                raise ValueError(f"Recipient '{recipient_id}' not registered")
            if sender_id == recipient_id:
                conn.close()
                raise ValueError("Cannot send message to yourself")
            timestamp = datetime.now(timezone.utc).isoformat()
            seq_row = conn.execute("SELECT MAX(sequence) FROM messages WHERE sender=?", (sender_id,)).fetchone()
            seq = (seq_row[0] or 0) + 1
            msg_id = f"msg_{int(datetime.now(timezone.utc).timestamp())}_{sender_id}_{seq:03d}"
            conn.execute("INSERT INTO messages (message_id,sender,recipient,body,timestamp,sequence,read,content_type,thread_id) VALUES (?,?,?,?,?,?,0,?,?)",
                         (msg_id, sender_id, recipient_id, body, timestamp, seq, "text/plain", thread_id))
            conn.commit()
            conn.close()
            return msg_id
        finally:
            self._release_lock(lock)

    def get_messages(self, recipient_id: str, unread_only: bool = False,
                     thread_id: str = None) -> List[Dict]:
        conn = self._get_conn()
        query = "SELECT * FROM messages WHERE recipient=?"
        params = [recipient_id]
        if unread_only:
            query += " AND read=0"
        if thread_id:
            query += " AND thread_id=?"
            params.append(thread_id)
        query += " ORDER BY timestamp"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def mark_as_read(self, recipient_id: str, message_id: str) -> bool:
        conn = self._get_conn()
        row = conn.execute("SELECT 1 FROM messages WHERE message_id=? AND recipient=?", (message_id, recipient_id)).fetchone()
        if not row:
            conn.close()
            return False
        conn.execute("UPDATE messages SET read=1 WHERE message_id=?", (message_id,))
        conn.commit()
        conn.close()
        return True

    def get_unread_count(self, recipient_id: str) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM messages WHERE recipient=? AND read=0", (recipient_id,)).fetchone()
        conn.close()
        return row[0]

    def get_thread_context(self, thread_id: str, limit: int = 3) -> List[Dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM messages WHERE thread_id=? ORDER BY timestamp DESC LIMIT ?",
            (thread_id, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in reversed(rows)]

    def set_turn_timeout(self, seconds: int, thread_id: str = "general"):
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        self._ensure_turn_row(conn, thread_id)
        conn.execute("UPDATE turns SET max_duration=? WHERE thread_id=?", (seconds, thread_id))
        conn.commit()
        conn.close()

    def request_stop(self, thread_id: str = "general"):
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        self._ensure_turn_row(conn, thread_id)
        conn.execute("UPDATE turns SET stop_flag = 1 WHERE thread_id=?", (thread_id,))
        conn.commit()
        conn.close()

    def should_stop(self, thread_id: str = "general") -> bool:
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        row = conn.execute("SELECT stop_flag FROM turns WHERE thread_id=?", (thread_id,)).fetchone()
        conn.close()
        return bool(row) and row["stop_flag"] == 1

    def hard_reset(self, thread_id: str = "general"):
        thread_id = self._norm_thread(thread_id)
        conn = self._get_conn()
        self._ensure_turn_row(conn, thread_id)
        conn.execute("UPDATE turns SET state = 'idle', current_turn = NULL, stop_flag = 0 WHERE thread_id=?", (thread_id,))
        conn.execute("DELETE FROM queue WHERE thread_id=?", (thread_id,))
        conn.commit()
        conn.close()

    def hard_reset_all(self):
        """FASE 24: reinicia el turno y vacia la cola de TODAS las conversaciones (reset de admin)."""
        conn = self._get_conn()
        conn.execute("UPDATE turns SET state = 'idle', current_turn = NULL, stop_flag = 0")
        conn.execute("DELETE FROM queue")
        conn.commit()
        conn.close()

    def clear_all_queues(self):
        conn = self._get_conn()
        conn.execute("DELETE FROM queue")
        conn.commit()
        conn.close()

    def read_all_states(self) -> List[Dict[str, Any]]:
        """FASE 24: estado de turno de todas las conversaciones (dashboard/recovery)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT thread_id, current_turn, state, started_at, max_duration, stop_flag FROM turns").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_setting(self, key: str, default: str = None) -> str:
        conn = self._get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                     (key, str(value), now))
        conn.commit()
        conn.close()

    def get_all_settings(self, defaults: Dict[str, str] = None) -> Dict[str, str]:
        conn = self._get_conn()
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        conn.close()
        result = dict(defaults or {})
        for r in rows:
            result[r["key"]] = r["value"]
        return result


if __name__ == "__main__":
    engine = ConversationEngine()
    print("HumanIA Engine (SQLite) initialized")
    print(f"DB: {engine.db_path}")
