from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent))

from dashboard.status_panel import StatusPanel
from dashboard.auto_janitor import AutoJanitor
from dashboard.agent_editor import AgentEditor
from dashboard.contract_viewer import ContractViewer


class HumaniaDashboard:
    """
    Panel principal de monitorizacion.
    Muestra estado de agentes, contratos y limpieza.
    """

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or Path(__file__).parent
        self.status_panel = StatusPanel(base_path)
        self.auto_janitor = AutoJanitor(base_path)
        self.agent_editor = AgentEditor(base_path)
        self.contract_viewer = ContractViewer(base_path)

    def render(self) -> str:
        """Renderiza el dashboard completo."""
        sections = [
            self.status_panel.render(),
            self.auto_janitor.render_status()
        ]

        return "\n".join([
            "=" * 60,
            "HUMANIA - DASHBOARD DE MONITORIZACION",
            "=" * 60,
            "",
            *sections,
            "",
            f"Ultima actualizacion: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ])

    def handle_command(self, cmd: str) -> str:
        """Procesa un comando del usuario."""
        if cmd == 'status':
            return self.status_panel.render()

        if cmd == 'janitor':
            return self.auto_janitor.render_status()

        if cmd == 'agents':
            return self.agent_editor.render_agent_summary()

        if cmd.startswith('edit '):
            agent_id = cmd.split(' ', 1)[1]
            return self.agent_editor.start_edit(agent_id)

        if cmd == 'sync':
            result = self.agent_editor.sync_with_turnfile()
            return f"Sync completado: {result['total']} agente(s) sincronizado(s)"

        if cmd == 'contracts':
            return self.contract_viewer.render_summary()

        if cmd.startswith('contracts '):
            agent_filter = cmd.split(' ', 1)[1]
            return self.contract_viewer.render_summary(agent_id=agent_filter)

        if cmd.startswith('contract '):
            contract_id = cmd.split(' ', 1)[1]
            return self.contract_viewer.render_contract_detail(contract_id)

        if cmd == 'agents_contracts':
            agents = self.contract_viewer.get_agents_in_contracts()
            return f"Agentes en contratos: {', '.join(agents)}"

        if cmd == 'scan':
            import json
            scan_results = self.auto_janitor.scan()
            return json.dumps(
                {k: [str(p) for p in v] for k, v in scan_results.items()},
                indent=2
            )

        if cmd == 'clean':
            return self.auto_janitor.clean(dry_run=True)

        if cmd == 'clean!':
            return self.auto_janitor.clean(dry_run=False)

        if cmd == 'git_status':
            import json
            return json.dumps(self.auto_janitor.git_cleaner.get_status(), indent=2)

        if cmd == 'git_clean':
            return self.auto_janitor.git_cleaner.clean_all(dry_run=False)

        if cmd == 'refresh':
            return self.render()

        if cmd == 'help':
            return self._show_help()

        if cmd == 'quit':
            return "EXIT"

        return f"Comando desconocido: {cmd}. Escribe 'help' para ayuda."

    def _show_help(self) -> str:
        return """
Comandos disponibles:
  status          - Ver estado de agentes
  agents          - Listar agentes configurables
  edit <id>       - Editar agente especifico
  sync            - Sincronizar agentes con turnfile.yaml
  contracts       - Ver todos los contratos
  contracts <id>  - Filtrar contratos por agente
  contract <id>   - Ver detalle de un contrato
  agents_contracts - Ver agentes en contratos
  janitor          - Ver estado del conserje
  scan             - Escanear archivos limpiables
  clean           - Simular limpieza (dry run)
  clean!          - Ejecutar limpieza real
  git_status       - Ver estado de Git
  git_clean        - Limpiar archivos sin versionar
  refresh          - Actualizar dashboard
  help             - Mostrar este mensaje
  quit             - Salir
"""


def run_interactive():
    """Ejecuta el dashboard en modo interactivo."""
    dashboard = HumaniaDashboard()

    print("HUMANIA Dashboard - Escribe 'help' para comandos")
    print("-" * 40)

    while True:
        try:
            cmd = input("\n> ").strip()

            if cmd == 'quit':
                print("Saliendo...")
                break

            result = dashboard.handle_command(cmd)
            if result == "EXIT":
                break
            print(result)

        except KeyboardInterrupt:
            print("\nSaliendo...")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--once':
        dashboard = HumaniaDashboard()
        print(dashboard.render())
    else:
        run_interactive()