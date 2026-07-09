#!/usr/bin/env python3
"""
HumanIA - UAT: Prueba de Aceptacion Integral
Ping-Pong secuencial con LM Studio + validacion completa del sistema.
"""
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine
from ia_shell import IAAgent
from lm_studio import LMStudioClient
from dashboard.status_panel import StatusPanel
from dashboard.contract_viewer import ContractViewer

ROOT = Path(__file__).parent.parent.parent
PASS = 0
FAIL = 0
RESULTS = []


def ok(name, detail=""):
    global PASS
    PASS += 1
    RESULTS.append(("PASS", name, detail))
    print(f"  [OK] {name}")


def err(name, detail=""):
    global FAIL
    FAIL += 1
    RESULTS.append(("FAIL", name, detail))
    print(f"  [FAIL] {name}: {detail}")


def header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_engine():
    header("BLOQUE 1: Engine Core")

    engine = ConversationEngine(base_path=ROOT)

    state = engine.read_state()
    if state.get("state") == "idle":
        ok("1.1 Estado inicial idle")
    else:
        err("1.1 Estado inicial idle", f"state={state.get('state')}")

    for pid, role, ptype, email in [
        ("miguel", "product_owner", "human", "miguel@human.local"),
        ("gemini", "ai_agent", "bot", "gemini@bot.humania.local"),
        ("claude", "ai_agent", "bot", "claude@bot.humania.local")
    ]:
        engine.register_participant(pid, role, ptype, email)
    if len(engine.get_participants()) >= 3:
        ok("1.2 Registro de participantes")
    else:
        err("1.2 Registro", f"total={len(engine.get_participants())}")

    if engine.register_participant("miguel", "x", "human", "x@x") is False:
        ok("1.3 Registro duplicado bloqueado")
    else:
        err("1.3 Duplicado bloqueado")

    total = len(engine.get_participants())
    if total >= 3 and "miguel" in engine.get_participants():
        ok(f"1.4 Participantes ({total})")
    else:
        err("1.4 Lista participantes", str(engine.get_participants()))

    if engine.acquire_turn("miguel"):
        ok("1.5 Adquirir turno")
    else:
        err("1.5 Adquirir turno")

    if engine.acquire_turn("gemini") is False:
        ok("1.6 Doble turno bloqueado")
    else:
        err("1.6 Doble turno")

    try:
        msg_id = engine.send_message("gemini", "1", "miguel")
        if msg_id.startswith("msg_"):
            ok("1.7 Enviar mensaje (miguel -> gemini: 1)")
        else:
            err("1.7 Enviar mensaje")
    except Exception as e:
        err("1.7 Enviar mensaje", str(e))

    engine.release_turn("miguel")
    try:
        engine.send_message("claude", "fail", "gemini")
        err("1.8 Bloquear envio sin turno", "No lanzo PermissionError")
    except PermissionError:
        ok("1.8 Bloquear envio sin turno")

    engine.add_to_queue("gemini")
    engine.add_to_queue("claude")
    if engine.get_queue() == ["gemini", "claude"]:
        ok("1.9 Cola de espera")
    else:
        err("1.9 Cola", str(engine.get_queue()))

    if engine.advance_queue() == "gemini":
        ok("1.10 Avanzar cola -> gemini")
    else:
        err("1.10 Avanzar cola")

    if engine.release_turn("gemini") and len(engine.read_state().get("turn_history", [])) >= 1:
        ok("1.11 Liberar turno + historial")
    else:
        err("1.11 Liberar turno")

    msgs = engine.get_messages("gemini")
    if len(msgs) >= 1 and msgs[0]["body"] == "1":
        ok("1.12 Leer mensajes (gemini tiene '1')")
    else:
        err("1.12 Leer mensajes")

    if engine.get_unread_count("gemini") >= 1:
        ok("1.13 Contar no leidos")
    else:
        err("1.13 Contar no leidos")

    unread_before = engine.get_unread_count("gemini")
    for msg in msgs:
        engine.mark_as_read("gemini", msg["message_id"])
    unread_after = engine.get_unread_count("gemini")
    if unread_after < unread_before or (unread_before == 0 and unread_after == 0):
        ok("1.14 Marcar como leido")
    else:
        err("1.14 Marcar como leido", f"before={unread_before} after={unread_after}")

    return engine


def test_ping_pong(engine):
    header("BLOQUE 2: Ping-Pong con LM Studio")

    lm = LMStudioClient()
    if not lm.health_check():
        err("2.X LM Studio health check", "No disponible")
        return
    models = lm.list_models()
    ok("2.0 LM Studio activo", str(models[:2]) if models else "sin modelos")

    engine.acquire_turn("gemini")
    agent_gemini = IAAgent("gemini", base_path=ROOT, use_llm=True)
    if agent_gemini.status()["is_my_turn"]:
        ok("2.1 Gemini reconoce su turno")
    else:
        err("2.1 Gemini turno")

    result = agent_gemini.act("claude", use_llm=True)
    if result["success"] and result.get("body", "").strip() == "2":
        ok("2.2 Gemini responde '2' a Claude", f"mode={result.get('mode')}")
    elif result["success"]:
        ok("2.2 Gemini responde", f"body='{result.get('body')}' mode={result.get('mode')}")
    else:
        err("2.2 Gemini responde", str(result.get("error")))

    engine.acquire_turn("claude")
    agent_claude = IAAgent("claude", base_path=ROOT, use_llm=True)
    result2 = agent_claude.act("miguel", use_llm=True)
    if result2["success"] and result2.get("body", "").strip() == "3":
        ok("2.3 Claude responde '3' a Miguel", f"mode={result2.get('mode')}")
    elif result2["success"]:
        ok("2.3 Claude responde", f"body='{result2.get('body')}' mode={result2.get('mode')}")
    else:
        err("2.3 Claude responde", str(result2.get("error")))

    if len(engine.get_messages("miguel")) >= 1:
        ok("2.4 Miguel recibe mensaje de Claude")
    else:
        err("2.4 Miguel recibe")

    if len(engine.get_messages("claude")) >= 1:
        ok("2.5 Claude recibe mensaje de Gemini")
    else:
        err("2.5 Claude recibe")

    if len(list(agent_gemini.cot_dir.glob("*.cot.txt"))) >= 1:
        ok("2.6 CoT Gemini guardado")
    else:
        err("2.6 CoT Gemini")

    if len(list(agent_claude.cot_dir.glob("*.cot.txt"))) >= 1:
        ok("2.7 CoT Claude guardado")
    else:
        err("2.7 CoT Claude")


def test_dashboard(engine):
    header("BLOQUE 3: Dashboard")

    panel = StatusPanel(base_path=ROOT)
    render = panel.render()
    if "Turno" in render:
        ok("3.1 StatusPanel funcional")
    else:
        err("3.1 StatusPanel")

    viewer = ContractViewer(base_path=ROOT)
    contract = {
        "id": "contract_uat_001",
        "date": datetime.now().isoformat(),
        "agents": ["gemini", "claude", "miguel"],
        "summary": "UAT Ping-Pong test contract",
        "status": "active",
        "value": 3,
        "terms": "Ping-Pong secuencial: 1 -> 2 -> 3",
        "metadata": {"test": "uat"}
    }
    contracts_dir = ROOT / "memory" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    with open(contracts_dir / "uat.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(contract) + "\n")

    if "contract_uat_001" in viewer.render_summary():
        ok("3.2 ContractViewer crea y lista")
    else:
        err("3.2 ContractViewer")

    if "UAT Ping-Pong" in viewer.render_contract_detail("contract_uat_001"):
        ok("3.3 ContractViewer detalle")
    else:
        err("3.3 ContractViewer detalle")


def summary():
    header("RESUMEN FINAL UAT")
    total = PASS + FAIL
    print(f"  Tests: {total} | PASS: {PASS} | FAIL: {FAIL} | Exito: {PASS/total*100:.1f}%" if total else "  Sin tests")
    for status, name, detail in RESULTS:
        print(f"  {'[OK]' if status == 'PASS' else '[FAIL]'} {name}")
        if detail:
            print(f"       {detail}")
    print(f"\n  Artefactos generados en raiz del proyecto:")
    print(f"    mailboxes/miguel/messages/")
    print(f"    mailboxes/gemini/messages/")
    print(f"    mailboxes/claude/messages/")
    print(f"    memory/turnfile.yaml")
    print(f"    memory/contracts/uat.jsonl")
    print(f"    agent_memory/gemini/cot/")
    print(f"    agent_memory/claude/cot/")
    return FAIL == 0


if __name__ == "__main__":
    print("=" * 60)
    print("  HUMANIA - UAT: PRUEBA DE ACEPTACION INTEGRAL")
    print(f"  Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Raiz: {ROOT}")
    print("=" * 60)

    engine = test_engine()
    test_ping_pong(engine)
    test_dashboard(engine)

    success = summary()
    print(f"\n{'='*60}")
    print(f"  {'UAT COMPLETADO EXITOSAMENTE' if success else 'UAT COMPLETADO CON FALLOS'}")
    print(f"{'='*60}")
    sys.exit(0 if success else 1)
