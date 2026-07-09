"""Importa mensajes desde un HTML exportado de HumanIA a la base de datos SQLite.

Uso:
    python execution/scripts/import_from_html.py <archivo.html>
    python execution/scripts/import_from_html.py conversaciones/humania_general_2026-05-26.html
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "memory" / "humania.db"


def extract_messages(html_path):
    html = Path(html_path).read_text(encoding="utf-8")
    match = re.search(r'<script type="application/json" id="messages-data">(.*?)</script>', html, re.DOTALL)
    if not match:
        print("ERROR: No se encontro el bloque messages-data en el HTML.")
        return None
    return json.loads(match.group(1))


def import_messages(messages):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id TEXT PRIMARY KEY, role TEXT, type TEXT, email TEXT,
            status TEXT DEFAULT 'active', public_key TEXT,
            registered_at TEXT, last_seen TEXT, provider TEXT DEFAULT 'cloud'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY, sender TEXT, recipient TEXT,
            body TEXT, timestamp TEXT, sequence INTEGER, read INTEGER,
            content_type TEXT DEFAULT 'text/plain', thread_id TEXT DEFAULT 'general'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_thread ON messages(thread_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_recipient ON messages(recipient)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_timestamp ON messages(timestamp)")

    participants_seen = set()
    for m in messages:
        participants_seen.add(m.get("sender"))
        participants_seen.add(m.get("recipient"))

    for pid in participants_seen:
        if pid and not pid.startswith("msg_"):
            conn.execute(
                "INSERT OR IGNORE INTO participants (id, role, type, email, provider) VALUES (?, ?, ?, ?, ?)",
                (pid, "importado", "bot", f"{pid}@importado.local", "cloud"),
            )

    imported = 0
    for m in messages:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO messages
                   (message_id, sender, recipient, body, timestamp, sequence, read, content_type, thread_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    m.get("message_id", ""),
                    m.get("sender", ""),
                    m.get("recipient", ""),
                    m.get("body", ""),
                    m.get("timestamp", ""),
                    m.get("sequence", 0),
                    m.get("read", 0),
                    m.get("content_type", "text/plain"),
                    m.get("thread_id", "general"),
                ),
            )
            imported += 1
        except Exception as e:
            print(f"  [skip] {m.get('message_id','?')}: {e}")

    conn.commit()
    conn.close()
    return imported


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    html_file = sys.argv[1]
    if not Path(html_file).exists():
        print(f"ERROR: No existe {html_file}")
        sys.exit(1)

    print(f"Extrayendo mensajes de {html_file}...")
    msgs = extract_messages(html_file)
    if msgs is None:
        sys.exit(1)

    print(f"Encontrados {len(msgs)} mensajes. Importando a {DB_PATH}...")
    count = import_messages(msgs)
    print(f"OK: {count} mensajes importados. {len(msgs) - count} ya existian.")
