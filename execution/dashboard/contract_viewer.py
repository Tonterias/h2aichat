import json
from pathlib import Path
from typing import Dict, List, Optional


class ContractViewer:
    """
    Visualizador de contratos JSONL.
    Permite lectura secuencial, filtrado y formateo.
    """

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or Path.cwd()
        self.contracts_dir = self.base_path / 'memory' / 'contracts'
        self.contracts_dir.mkdir(parents=True, exist_ok=True)

    def list_contracts(self, agent_id: str = None,
                      limit: int = 10) -> List[Dict]:
        """
        Lista contratos del mas reciente al mas antiguo.
        Opcionalmente filtra por agente.
        """
        if not self.contracts_dir.exists():
            return []

        all_contracts = []

        for jsonl_file in sorted(self.contracts_dir.glob('*.jsonl'), reverse=True):
            try:
                with open(jsonl_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            contract = json.loads(line)
                            all_contracts.append(contract)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                continue

        if agent_id:
            all_contracts = [
                c for c in all_contracts
                if agent_id in c.get('agents', [])
            ]

        all_contracts.sort(
            key=lambda x: x.get('date', ''),
            reverse=True
        )

        return all_contracts[:limit]

    def load_contract(self, contract_id: str) -> Optional[Dict]:
        """Carga un contrato especifico por ID."""
        contracts = self.list_contracts(limit=1000)

        for contract in contracts:
            if contract.get('id') == contract_id:
                return contract

        return None

    def get_agents_in_contracts(self) -> List[str]:
        """Retorna lista de agentes que aparecen en contratos."""
        all_agents = set()
        contracts = self.list_contracts(limit=1000)

        for contract in contracts:
            all_agents.update(contract.get('agents', []))

        return sorted(all_agents)

    def render_summary(self, agent_id: str = None,
                     limit: int = 10) -> str:
        """Renderiza resumen de contratos en formato tabla."""
        contracts = self.list_contracts(agent_id=agent_id, limit=limit)

        if not contracts:
            return "--- CONTRATOS ---\n\n  (No hay contratos)"

        lines = ["--- CONTRATOS ---", ""]
        lines.append(f"Total: {len(contracts)} contrato(s)")

        if agent_id:
            lines.append(f"Filtrado por: {agent_id}")

        lines.append("")
        lines.append(f"{'ID':<25} {'Fecha':<12} {'Agentes':<15} {'Resumen':<35} {'Estado':<10}")
        lines.append("-" * 100)

        for contract in contracts:
            contract_id = contract.get('id', 'N/A')[:23]
            date = contract.get('date', '')[:10]
            agents = ','.join(contract.get('agents', []))[:13]
            summary = contract.get('summary', 'N/A')[:33]
            status = contract.get('status', 'N/A')[:8]

            lines.append(
                f"{contract_id:<25} {date:<12} {agents:<15} {summary:<35} {status:<10}"
            )

        lines.append("")
        lines.append("  Usa 'contract <id>' para ver detalle")

        return "\n".join(lines)

    def render_contract_detail(self, contract_id: str) -> str:
        """Renderiza detalle de un contrato."""
        contract = self.load_contract(contract_id)

        if not contract:
            return f"[ERROR] Contrato '{contract_id}' no encontrado"

        lines = [
            f"--- CONTRATO: {contract_id} ---",
            "",
            f"Fecha: {contract.get('date', 'N/A')}",
            f"Estado: {contract.get('status', 'N/A')}",
            f"Valor: {contract.get('value', 'N/A')}",
            "",
            "Agentes participantes:"
        ]

        for agent in contract.get('agents', []):
            lines.append(f"  - {agent}")

        lines.extend([
            "",
            f"Resumen: {contract.get('summary', 'N/A')}",
            "",
            "Terminos:",
            str(contract.get('terms', 'N/A')),
            "",
            f"Metadata: {json.dumps(contract.get('metadata', {}), indent=2)}"
        ])

        return "\n".join(lines)