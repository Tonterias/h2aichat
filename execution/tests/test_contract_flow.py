#!/usr/bin/env python3
"""
Test script para Phase 5.3: Contract Viewer
Genera un contrato en JSONL y lo visualiza en el Dashboard.
"""

import sys
from pathlib import Path
import json
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine
from dashboard.contract_viewer import ContractViewer


def main():
    print("=" * 60)
    print("HUMANIA - TEST PHASE 5.3: CONTRACT VIEWER")
    print("=" * 60)

    # 1. Activar Gemma en turnfile.yaml
    print("\n[PASO 1] Activando Gemma...")

    engine = ConversationEngine()

    state = engine.read_state()
    print(f"  Estado actual: {state.get('state')}")
    print(f"  Turno actual: {state.get('current_turn')}")

    # Adquirir turno para Gemma
    success = engine.acquire_turn('gemma')
    if success:
        print("  [OK] Gemma tiene el turno")
    else:
        print("  [WARN] No se pudo adquirir turno para Gemma")

    state = engine.read_state()
    print(f"  Turno actual: {state.get('current_turn')}")

    # 2. Generar contrato en JSONL
    print("\n[PASO 2] Generando contrato en JSONL...")

    contracts_dir = Path('memory/contracts')
    contracts_dir.mkdir(parents=True, exist_ok=True)

    contract = {
        'id': f'contract_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}',
        'date': datetime.now(timezone.utc).isoformat(),
        'agents': ['gemma', 'miguel'],
        'summary': 'Acuerdo de narracion: Gemma narrara una historia de 1000 palabras',
        'status': 'active',
        'value': 1000,
        'terms': 'El agente Gemma narrara una historia de exactamente 1000 palabras sobre un bosque oscuro. El contrato esta sujeto a revision por Miguel.',
        'metadata': {
            'created_by': 'system_test',
            'session_id': 'test_001',
            'phase': '5.3'
        }
    }

    contract_file = contracts_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    with open(contract_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(contract) + '\n')

    print(f"  [OK] Contrato guardado en: {contract_file}")
    print(f"  ID: {contract['id']}")
    print(f"  Agentes: {contract['agents']}")
    print(f"  Resumen: {contract['summary']}")

    # 3. Verificar en Dashboard
    print("\n[PASO 3] Verificando en Dashboard...")

    viewer = ContractViewer()
    print("\n--- CONTRATOS ---")
    print(viewer.render_summary())

    # 4. Ver agentes en contratos
    print("\n--- AGENTES EN CONTRATOS ---")
    agents = viewer.get_agents_in_contracts()
    print(f"  {', '.join(agents)}")

    # 5. Detalle del contrato
    print(f"\n--- DETALLE DEL CONTRATO ---")
    print(viewer.render_contract_detail(contract['id']))

    print("\n" + "=" * 60)
    print("NOTIFICACION: Miguel - Contrato listo para visualizar")
    print("Ejecuta: python execution/dashboard.py")
    print("Comando: contracts")
    print("=" * 60)


if __name__ == '__main__':
    main()