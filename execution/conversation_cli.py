#!/usr/bin/env python3
"""
HumanIA - CLI Unificada
Reemplaza scripts sueltos del plan original.
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from engine import ConversationEngine


ROOT = Path(__file__).parent.parent
engine = ConversationEngine(base_path=ROOT)


def cmd_register(args):
    ok = engine.register_participant(args.id, args.role, args.type, args.email)
    if ok:
        print(f"[OK] {args.id} registrado")
    else:
        print(f"[WARN] {args.id} ya existe")


def cmd_turn_acquire(args):
    ok = engine.acquire_turn(args.id)
    if ok:
        print(f"[OK] Turno adquirido por {args.id}")
    else:
        print(f"[WARN] Turno ya ocupado. Actual: {engine.get_current_turn()}")


def cmd_turn_release(args):
    ok = engine.release_turn(args.id) or engine.force_release_turn(args.id)
    if ok:
        print(f"[OK] Turno liberado por {args.id}")
    else:
        print(f"[WARN] {args.id} no tiene el turno")


def cmd_turn_status(args):
    state = engine.read_state()
    print(f"Turno actual: {state.get('current_turn') or 'NINGUNO'}")
    print(f"Estado: {state.get('state')}")
    print(f"Cola: {state.get('queue', [])}")
    print(f"Historial: {len(state.get('turn_history', []))} turnos")


def cmd_queue_add(args):
    ok = engine.add_to_queue(args.id)
    print(f"[OK] {args.id} añadido a cola" if ok else f"[WARN] No se pudo añadir")


def cmd_queue_list(args):
    queue = engine.get_queue()
    if queue:
        for i, pid in enumerate(queue, 1):
            print(f"  {i}. {pid}")
    else:
        print("  (cola vacia)")


def cmd_send(args):
    try:
        msg_id = engine.send_message(args.to, args.body, args.from_id)
        print(f"[OK] Mensaje enviado: {msg_id}")
    except PermissionError as e:
        print(f"[ERROR] {e}")
    except ValueError as e:
        print(f"[ERROR] {e}")


def cmd_messages(args):
    msgs = engine.get_messages(args.id, unread_only=args.unread)
    print(f"Mensajes para {args.id}: {len(msgs)}")
    for m in msgs:
        read = " " if m.get("read") else "*"
        print(f"  [{read}] {m['sender']}: {m['body'][:60]}")


def cmd_status(args):
    state = engine.read_state()
    participants = state.get("participants", {})
    print(f"Estado: {state.get('state')}")
    print(f"Turno actual: {state.get('current_turn') or 'NINGUNO'}")
    print(f"Cola: {state.get('queue', [])}")
    print(f"Participantes: {len(participants)}")
    for pid, info in participants.items():
        icon = "(*)" if pid == state.get("current_turn") else "   "
        print(f"  {icon} {pid} ({info.get('type')}) - {info.get('role')}")


def cmd_daemon(args):
    from scripts.recovery_daemon import RecoveryDaemon
    daemon = RecoveryDaemon(base_path=ROOT, check_interval=args.interval or 30)
    if args.once:
        import json
        result = daemon.run_once()
        print(json.dumps(result, indent=2))
    else:
        daemon.start()


def cmd_clean(args):
    from dashboard.auto_janitor import AutoJanitor
    janitor = AutoJanitor(base_path=ROOT)
    result = janitor.clean_mailboxes(dry_run=args.dry_run)
    print(f"Huerfanos: {result['orphans_found']}")
    for d in result["deleted"]:
        print(f"  {d}")


def main():
    parser = argparse.ArgumentParser(description="HumanIA CLI Unificada")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("register", help="Registrar participante")
    p.add_argument("id")
    p.add_argument("role")
    p.add_argument("type", choices=["human", "bot"])
    p.add_argument("email")

    p = sub.add_parser("turn", help="Gestion de turnos")
    turn_sub = p.add_subparsers(dest="turn_cmd")
    pa = turn_sub.add_parser("acquire")
    pa.add_argument("id")
    pr = turn_sub.add_parser("release")
    pr.add_argument("id")
    turn_sub.add_parser("status")

    p = sub.add_parser("queue", help="Gestion de cola")
    q_sub = p.add_subparsers(dest="queue_cmd")
    qa = q_sub.add_parser("add")
    qa.add_argument("id")
    q_sub.add_parser("list")

    p = sub.add_parser("send", help="Enviar mensaje")
    p.add_argument("to")
    p.add_argument("body")
    p.add_argument("--from", dest="from_id", default=None)

    p = sub.add_parser("messages", help="Leer mensajes")
    p.add_argument("id")
    p.add_argument("--unread", action="store_true")

    sub.add_parser("status", help="Estado del sistema")

    p = sub.add_parser("daemon", help="Recovery daemon")
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=int)

    p = sub.add_parser("clean", help="Limpieza de buzones")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)

    args = parser.parse_args()

    if args.command == "register":
        cmd_register(args)
    elif args.command == "turn":
        if args.turn_cmd == "acquire":
            cmd_turn_acquire(args)
        elif args.turn_cmd == "release":
            cmd_turn_release(args)
        elif args.turn_cmd == "status":
            cmd_turn_status(args)
    elif args.command == "queue":
        if args.queue_cmd == "add":
            cmd_queue_add(args)
        elif args.queue_cmd == "list":
            cmd_queue_list(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "messages":
        cmd_messages(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "daemon":
        cmd_daemon(args)
    elif args.command == "clean":
        cmd_clean(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
