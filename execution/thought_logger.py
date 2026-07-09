from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional


class ThoughtLogger:
    """Sistema de logs CoT estrictos en mailboxes/{id}/thoughts/"""

    THOUGHTS_DIR = 'thoughts'

    def __init__(self, agent_id: str, base_path: Path = None):
        self.agent_id = agent_id
        self.base_path = base_path or Path.cwd()
        self.thoughts_dir = self.base_path / 'mailboxes' / agent_id / self.THOUGHTS_DIR
        self.thoughts_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, text: str, max_len: int = 20) -> str:
        """Crea un filename seguro reemplazando espacios y caracteres invalidos."""
        sanitized = text[:max_len].replace(' ', '_').replace('\n', '_')
        sanitized = sanitized.replace('/', '_').replace('\\', '_')
        sanitized = sanitized.replace(':', '_').replace('*', '_')
        sanitized = sanitized.replace('?', '_').replace('"', '_')
        sanitized = sanitized.replace('<', '_').replace('>', '_')
        sanitized = sanitized.replace('|', '_')
        return sanitized

    def log(
        self,
        mode: str,
        input_msg: str,
        output: str,
        latency_ms: Optional[int] = None,
        model: Optional[str] = None
    ) -> Path:
        """
        Guarda pensamiento en archivo con formato estricto.

        Returns:
            Path al archivo de log creado.
        """
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')

        input_preview = self._sanitize_filename(input_msg)
        output_preview = self._sanitize_filename(output)

        filename = f"{timestamp}_{mode}_{input_preview}_{output_preview}.txt"
        filepath = self.thoughts_dir / filename

        content = f"""[TIMESTAMP] {datetime.now(timezone.utc).isoformat()}
[MODE] {mode}
[INPUT] {input_msg}
[OUTPUT] {output}
[AGENT] {self.agent_id}
[LATENCY_MS] {latency_ms if latency_ms is not None else 'N/A'}
[MODEL] {model if model else 'N/A'}
"""

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return filepath

    def get_thoughts(self, limit: int = 10) -> List[Path]:
        """Retorna ultimos N pensamientos ordenados por fecha."""
        thoughts = sorted(self.thoughts_dir.glob('*.txt'), reverse=True)
        return thoughts[:limit]

    def search_thoughts(self, pattern: str) -> List[Path]:
        """Busca pensamientos que contengan el patron."""
        results = []
        for thought_file in self.thoughts_dir.glob('*.txt'):
            try:
                with open(thought_file, 'r', encoding='utf-8') as f:
                    if pattern in f.read():
                        results.append(thought_file)
            except Exception:
                continue
        return results

    def get_thoughts_by_mode(self, mode: str) -> List[Path]:
        """Retorna pensamientos de un modo especifico."""
        return list(self.thoughts_dir.glob(f'*_{mode}_*.txt'))

    def clear_thoughts(self) -> int:
        """Elimina todos los pensamientos (para testing). Retorna count de archivos borrados."""
        count = 0
        for thought_file in self.thoughts_dir.glob('*.txt'):
            try:
                thought_file.unlink()
                count += 1
            except Exception:
                continue
        return count