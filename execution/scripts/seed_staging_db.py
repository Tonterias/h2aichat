"""FASE 30 — Siembra la BD de STAGING copiando la de PROD.

Usa la BACKUP API de SQLite: hace una copia CONSISTENTE aunque el origen esté en modo WAL
(no basta `cp` porque dejaría fuera el -wal). Hoy es seguro porque todas las cuentas son del
PO (no hay PII de terceros), así que no hace falta anonimizar.

IMPORTANTE:
  - Para el servicio de PRE antes de sembrar:  sudo systemctl stop humania-staging
  - El destino es el fichero PROPIO de PRE; NUNCA se toca la BD viva de PROD (se abre en RO).

Uso:
  python execution/scripts/seed_staging_db.py            # rutas por defecto, falla si destino existe
  python execution/scripts/seed_staging_db.py --force    # sobrescribe el destino
"""
import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_SRC = "/home/humania/HumaniaContract/memory/humania.db"
DEFAULT_DEST = "/home/humania/HumaniaContract-staging/memory/humania.db"


def seed(src: Path, dest: Path, force: bool) -> None:
    if not src.exists():
        sys.exit(f"ERROR: no existe la BD de origen (PROD): {src}")
    if dest.exists() and not force:
        sys.exit(f"ERROR: el destino ya existe: {dest}\n  Usa --force para sobrescribir.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Empezar limpio: borra el destino y sus ficheros WAL/SHM si los hubiera (evita
    # mezclar con una BD vieja o un fichero corrupto -> 'file is not a database').
    if dest.exists():
        for p in (dest, Path(str(dest) + "-wal"), Path(str(dest) + "-shm")):
            p.unlink(missing_ok=True)
    # Origen en SOLO LECTURA: imposible tocar PROD por accidente.
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    dest_conn = sqlite3.connect(str(dest))
    try:
        with dest_conn:
            src_conn.backup(dest_conn)  # copia consistente (maneja WAL)
    finally:
        src_conn.close()
        dest_conn.close()
    print(f"OK: BD sembrada {src} -> {dest} ({dest.stat().st_size} bytes)")
    print("Recuerda arrancar PRE de nuevo:  sudo systemctl start humania-staging")


def main() -> None:
    ap = argparse.ArgumentParser(description="Copia la BD de PROD a la de STAGING (PRE).")
    ap.add_argument("--src", default=DEFAULT_SRC, help=f"BD de PROD (def: {DEFAULT_SRC})")
    ap.add_argument("--dest", default=DEFAULT_DEST, help=f"BD de PRE (def: {DEFAULT_DEST})")
    ap.add_argument("--force", action="store_true", help="sobrescribir el destino si existe")
    a = ap.parse_args()
    seed(Path(a.src), Path(a.dest), a.force)


if __name__ == "__main__":
    main()
