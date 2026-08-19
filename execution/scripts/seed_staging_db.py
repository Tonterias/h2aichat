"""FASE 30 — Siembra la BD de STAGING copiando la de PROD.

Uses SQLite's BACKUP API to make a CONSISTENT copy even when the source is in WAL mode:
a plain `cp` is not enough, because it would leave the -wal file behind. This is only safe
while every account belongs to the team, so there is no third-party data to anonymise.

IMPORTANTE:
  - Stop the staging service before seeding:  sudo systemctl stop humania-staging
  - The destination is staging's OWN file. The live production database is NEVER touched: it is opened read-only.

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
    # Start clean: delete the destination and any WAL/SHM files, so an old or corrupted
    # database cannot get mixed in and produce 'file is not a database'.
    if dest.exists():
        for p in (dest, Path(str(dest) + "-wal"), Path(str(dest) + "-shm")):
            p.unlink(missing_ok=True)
    # The source is opened READ-ONLY, so production cannot be touched by accident.
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
