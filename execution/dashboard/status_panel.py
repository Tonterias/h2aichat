import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine


class StatusPanel:
    """Muestra el estado actual de todos los agentes."""

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or Path(__file__).parent.parent
        self.engine = ConversationEngine(base_path=self.base_path)

    def render(self) -> str:
        lines = ["--- ESTADO DE AGENTES ---", ""]

        state = self.engine.read_state()

        current_turn = state.get('current_turn')
        queue = state.get('queue', [])

        lines.append(f"Turno actual: {current_turn or 'NINGUNO'}")
        lines.append(f"Cola de espera: {len(queue)} participante(s)")
        lines.append("")

        participants = state.get('participants', {})

        for pid in sorted(participants.keys()):
            info = participants[pid]
            status_icon = "[*]" if pid == current_turn else "[ ]"
            agent_type = info.get('type', 'unknown')
            role = info.get('role', 'unknown')
            lines.append(f"  {status_icon} {pid} ({agent_type}) - {role}")

        lines.append("")
        lines.append("Mensajes pendientes:")

        for pid in sorted(participants.keys()):
            unread = self.engine.get_unread_count(pid)
            lines.append(f"  {pid}: {unread} no leido(s)")

        return "\n".join(lines)