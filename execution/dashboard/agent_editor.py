import os
import re
import shutil
import yaml
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Any


class AgentEditor:
    """
    Editor de configuracion de agentes.
    Permite cargar, modificar y guardar configuraciones de agentes de forma segura.
    """

    ALLOWED_MODELS = [
        'google/gemma-4-e4b',
        'qwen2.5-coder-7b-instruct',
        'local-model'
    ]

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or Path.cwd()
        self.agents_dir = self.base_path / 'memory' / 'agents'
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self._edit_buffer: Dict[str, Dict] = {}

    def list_agents(self) -> List[str]:
        """Lista agentes disponibles para edicion."""
        agents = []
        if self.agents_dir.exists():
            for item in self.agents_dir.iterdir():
                if item.is_dir() and (item / 'config.yaml').exists():
                    agents.append(item.name)
        return sorted(agents)

    def load_agent_config(self, agent_id: str) -> Dict:
        """Carga configuracion de un agente desde YAML."""
        config_path = self.agents_dir / agent_id / 'config.yaml'

        if not config_path.exists():
            return self._create_default_config(agent_id)

        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        return config

    def _create_default_config(self, agent_id: str) -> Dict:
        """Crea configuracion default para un agente."""
        return {
            'agent_id': agent_id,
            'type': 'bot',
            'role': 'ai_agent',
            'llm_config': {
                'provider': 'lm_studio',
                'model': 'google/gemma-4-e4b',
                'port': 1234,
                'temperature': 0.3,
                'max_tokens': 512
            },
            'system_prompt': f"Eres {agent_id}, un agente en el sistema HumanIA.",
            'personality': {
                'tone': 'neutral',
                'verbosity': 'medium',
                'creativity': 0.5
            },
            'metadata': {
                'created': datetime.now(timezone.utc).isoformat(),
                'modified': datetime.now(timezone.utc).isoformat(),
                'version': '1.0'
            }
        }

    def save_agent_config(self, agent_id: str, config: Dict) -> Tuple[bool, str]:
        """
        Guarda configuracion de forma atomica.
        Returns: (success, message)
        """
        agent_dir = self.agents_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        config_path = agent_dir / 'config.yaml'
        tmp_path = config_path.with_suffix('.tmp')

        is_valid, errors = self.validate_config(config)
        if not is_valid:
            return False, f"Config invalida: {errors}"

        config['metadata']['modified'] = datetime.now(timezone.utc).isoformat()

        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            os.replace(tmp_path, config_path)
            return True, f"Configuracion guardada para {agent_id}"

        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink()
            return False, f"Error al guardar: {e}"

    def validate_config(self, config: Dict) -> Tuple[bool, List[str]]:
        """
        Valida configuracion completa.
        Returns: (is_valid, list_of_errors)
        """
        errors = []

        agent_id = config.get('agent_id', '')
        if not re.match(r'^[a-zA-Z0-9_]+$', agent_id):
            errors.append("agent_id debe ser alphanumeric + underscore")
        if len(agent_id) > 32:
            errors.append("agent_id no puede exceder 32 caracteres")

        prompt = config.get('system_prompt', '')
        if len(prompt) < 10:
            errors.append("system_prompt debe tener al menos 10 caracteres")
        if len(prompt) > 10000:
            errors.append("system_prompt no puede exceder 10000 caracteres")

        llm_config = config.get('llm_config', {})

        temp = llm_config.get('temperature', None)
        if temp is None:
            errors.append("llm_config.temperature es requerido")
        elif not isinstance(temp, (int, float)) or not 0.0 <= temp <= 2.0:
            errors.append("llm_config.temperature debe estar entre 0.0 y 2.0")

        max_tokens = llm_config.get('max_tokens', None)
        if max_tokens is None:
            errors.append("llm_config.max_tokens es requerido")
        elif not isinstance(max_tokens, int) or not 64 <= max_tokens <= 8192:
            errors.append("llm_config.max_tokens debe estar entre 64 y 8192")

        model = llm_config.get('model', '')
        if model not in self.ALLOWED_MODELS:
            errors.append(f"llm_config.model debe ser uno de: {self.ALLOWED_MODELS}")

        agent_type = config.get('type', '')
        if agent_type not in ('bot', 'human'):
            errors.append("type debe ser 'bot' o 'human'")

        return (len(errors) == 0, errors)

    def sanitize_prompt(self, prompt: str) -> str:
        """Limpia el prompt para evitar injection."""
        prompt = re.sub(r'```[\s\S]*?```', '', prompt)
        prompt = re.sub(r'\n{3,}', '\n\n', prompt)
        prompt = re.sub(r'\t{2,}', '\t', prompt)
        prompt = prompt.strip()
        return prompt

    def validate_no_yaml_injection(self, config: Dict) -> bool:
        """Verifica que no haya injection de YAML."""
        for key, value in config.items():
            if isinstance(value, str):
                if value.startswith(('---', '...', '- ', ': ')):
                    return False
        return True

    def pre_save_verification(self, agent_id: str) -> Tuple[bool, str]:
        """Verificacion final antes de guardar."""
        config = self._edit_buffer.get(agent_id)
        if config is None:
            return False, "No hay cambios pendientes para guardar"

        if config.get('agent_id') != agent_id:
            return False, "agent_id no coincide"

        is_valid, errors = self.validate_config(config)
        if not is_valid:
            return False, f"Errores de validacion: {errors}"

        try:
            yaml_str = yaml.dump(config)
            yaml.safe_load(yaml_str)
        except Exception as e:
            return False, f"Error de serializacion YAML: {e}"

        return True, "OK"

    def start_edit(self, agent_id: str) -> str:
        """Inicia edicion de un agente. Carga config en buffer."""
        config = self.load_agent_config(agent_id)
        self._edit_buffer[agent_id] = config
        return self.render_edit_form(agent_id)

    def update_system_prompt(self, agent_id: str, new_prompt: str) -> Tuple[bool, str]:
        """Actualiza el system prompt en el buffer."""
        if agent_id not in self._edit_buffer:
            return False, "Sesion de edicion no iniciada. Usa 'edit <id>' primero."

        sanitized = self.sanitize_prompt(new_prompt)
        if len(sanitized) < 10:
            return False, "Prompt debe tener al menos 10 caracteres"

        self._edit_buffer[agent_id]['system_prompt'] = sanitized
        return True, "System prompt actualizado (sin guardar)"

    def update_temperature(self, agent_id: str, value: str) -> Tuple[bool, str]:
        """Actualiza temperature en el buffer."""
        if agent_id not in self._edit_buffer:
            return False, "Sesion de edicion no iniciada"

        try:
            temp = float(value)
            if not 0.0 <= temp <= 2.0:
                return False, "Temperature debe estar entre 0.0 y 2.0"
            self._edit_buffer[agent_id]['llm_config']['temperature'] = temp
            return True, f"Temperature: {temp} (sin guardar)"
        except ValueError:
            return False, "Valor invalido para temperature"

    def update_max_tokens(self, agent_id: str, value: str) -> Tuple[bool, str]:
        """Actualiza max_tokens en el buffer."""
        if agent_id not in self._edit_buffer:
            return False, "Sesion de edicion no iniciada"

        try:
            tokens = int(value)
            if not 64 <= tokens <= 8192:
                return False, "Max tokens debe estar entre 64 y 8192"
            self._edit_buffer[agent_id]['llm_config']['max_tokens'] = tokens
            return True, f"Max tokens: {tokens} (sin guardar)"
        except ValueError:
            return False, "Valor invalido para max_tokens"

    def update_model(self, agent_id: str, model: str) -> Tuple[bool, str]:
        """Actualiza el modelo en el buffer."""
        if agent_id not in self._edit_buffer:
            return False, "Sesion de edicion no iniciada"

        if model not in self.ALLOWED_MODELS:
            return False, f"Modelo debe ser uno de: {self.ALLOWED_MODELS}"

        self._edit_buffer[agent_id]['llm_config']['model'] = model
        return True, f"Model: {model} (sin guardar)"

    def render_preview(self, agent_id: str) -> str:
        """Renderiza preview de la config resultante."""
        if agent_id not in self._edit_buffer:
            return "[ERROR] Sesion de edicion no iniciada"

        config = self._edit_buffer[agent_id]
        return yaml.dump(config, default_flow_style=False, sort_keys=False)

    def save_current_config(self, agent_id: str) -> Tuple[bool, str]:
        """Guarda la config del buffer."""
        if agent_id not in self._edit_buffer:
            return False, "No hay cambios pendientes para guardar"

        is_valid, msg = self.pre_save_verification(agent_id)
        if not is_valid:
            return False, msg

        config = self._edit_buffer[agent_id]
        success, message = self.save_agent_config(agent_id, config)

        if success:
            del self._edit_buffer[agent_id]

        return success, message

    def discard_changes(self, agent_id: str) -> bool:
        """Descarta cambios en el buffer."""
        if agent_id in self._edit_buffer:
            del self._edit_buffer[agent_id]
            return True
        return False

    def render_edit_form(self, agent_id: str) -> str:
        """Renderiza formulario de edicion."""
        if agent_id not in self._edit_buffer:
            config = self.load_agent_config(agent_id)
            self._edit_buffer[agent_id] = config
        else:
            config = self._edit_buffer[agent_id]

        lines = [
            f"--- EDITANDO: {agent_id} ---",
            "",
            "System Prompt actual:",
            "---",
            config.get('system_prompt', '(vacio)'),
            "---",
            "",
            "Límites LLM:",
            f"  - Temperature: {config['llm_config']['temperature']} (0.0 - 2.0)",
            f"  - Max Tokens: {config['llm_config']['max_tokens']} (64 - 8192)",
            f"  - Model: {config['llm_config']['model']}",
            "",
            "Comandos:",
            "  prompt <texto>  - Actualizar system prompt",
            "  temp <valor>    - Cambiar temperature",
            "  tokens <valor>  - Cambiar max_tokens",
            "  model <nombre>  - Cambiar modelo",
            "  preview         - Ver config resultante",
            "  save            - Guardar cambios",
            "  discard         - Descartar cambios",
            "  quit             - Salir sin guardar",
            ""
        ]

        return "\n".join(lines)

    def render_agent_summary(self) -> str:
        """Muestra resumen de agentes disponibles."""
        agents = self.list_agents()

        if not agents:
            return "--- AGENTES CONFIGURABLES ---\n\n  (No hay agentes configurados)\n  Ejecuta 'sync' para sincronizar con turnfile.yaml"

        lines = ["--- AGENTES CONFIGURABLES ---", ""]

        for i, agent_id in enumerate(agents, 1):
            config = self.load_agent_config(agent_id)
            agent_type = config.get('type', 'unknown')
            role = config.get('role', 'unknown')
            lines.append(f"  {i}. {agent_id} ({agent_type}, {role})")

        lines.append("")
        lines.append("  Usa 'edit <id>' para editar un agente")

        return "\n".join(lines)

    def sync_with_turnfile(self) -> Dict[str, Any]:
        """Sincroniza agentes en config con participantes en turnfile."""
        from engine import ConversationEngine

        engine = ConversationEngine(base_path=self.base_path)
        state = engine.read_state()
        participants = state.get('participants', {})

        synced = []
        for pid, info in participants.items():
            config_path = self.agents_dir / pid / 'config.yaml'

            if not config_path.exists():
                default_config = self._create_default_config(pid)
                default_config['type'] = info.get('type', 'bot')
                default_config['role'] = info.get('role', 'ai_agent')
                default_config['metadata']['synced_from_turnfile'] = True

                self.save_agent_config(pid, default_config)
                synced.append(pid)

        return {'synced': synced, 'total': len(synced)}