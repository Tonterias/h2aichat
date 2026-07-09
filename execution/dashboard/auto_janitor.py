from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any
from .git_cleaner import GitCleaner
import shutil
import yaml


class AutoJanitor:
    """
    Sistema de limpieza automatica.
    Detecta y limpia archivos temporales, marcas de Git y caches.
    """

    CLEANABLE_PATTERNS = [
        '__pycache__',
        '*.pyc',
        '*.pyo',
        '.pytest_cache',
        '*.tmp',
        '*.log',
        '.DS_Store',
        'Thumbs.db',
        '*.bak'
    ]

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or Path.cwd()
        self.git_cleaner = GitCleaner(base_path)
        self.last_clean = None
        self.clean_count = 0

    def scan(self) -> Dict[str, List[Path]]:
        """Escanea y retorna archivos que pueden ser limpiados."""
        results = {
            'pycache': [],
            'temp': [],
            'logs': [],
            'git_untracked': []
        }

        for pattern in self.CLEANABLE_PATTERNS:
            if '*' in pattern:
                for path in self.base_path.rglob(pattern):
                    if path.is_file():
                        results['temp'].append(path)
            else:
                if pattern == '__pycache__':
                    for path in self.base_path.rglob(pattern):
                        if path.is_dir():
                            results['pycache'].append(path)

        git_status = self.git_cleaner.get_status()
        for filepath in git_status.get('untracked', []):
            results['git_untracked'].append(Path(filepath))

        return results

    def clean(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        Limpia archivos.

        Args:
            dry_run: Si True, solo muestra lo que se limpiaria

        Returns:
            Dict con summary de limpieza
        """
        scan_results = self.scan()
        deleted = {
            'files': [],
            'dirs': [],
            'size_freed': 0,
            'pycache_dirs': []
        }

        for path in scan_results.get('pycache', []):
            try:
                if dry_run:
                    print(f"  [DRY] Eliminaria directorio: {path}")
                else:
                    import shutil
                    shutil.rmtree(path)
                    deleted['pycache_dirs'].append(str(path))
                    print(f"  [DEL] Eliminado: {path}")
            except Exception as e:
                print(f"  [ERR] Error: {path} - {e}")

        for path in scan_results.get('temp', []):
            try:
                if dry_run:
                    print(f"  [DRY] Eliminaria archivo: {path}")
                else:
                    size = path.stat().st_size
                    path.unlink()
                    deleted['files'].append(str(path))
                    deleted['size_freed'] += size
                    print(f"  [DEL] Eliminado: {path}")
            except Exception as e:
                print(f"  [ERR] Error: {path} - {e}")

        if not dry_run:
            git_result = self.git_cleaner.clean_untracked(force=True)
            deleted['git_clean_output'] = git_result.get('output', '')

        self.last_clean = datetime.now()
        self.clean_count += 1

        return deleted

    def _get_registered_participants(self) -> set:
        try:
            from engine import ConversationEngine
            engine = ConversationEngine(base_path=self.base_path)
            return set(engine.get_participants())
        except Exception:
            return set()

    def scan_orphan_mailboxes(self) -> List[str]:
        registered = self._get_registered_participants()
        mailboxes_dir = self.base_path / "mailboxes"
        if not mailboxes_dir.exists():
            return []
        orphans = []
        for item in mailboxes_dir.iterdir():
            if item.is_dir() and item.name not in registered:
                orphans.append(item.name)
        return sorted(orphans)

    def scan_inactive_participants(self, days: int = 30) -> List[str]:
        try:
            from engine import ConversationEngine
            engine = ConversationEngine(base_path=self.base_path)
            now = datetime.now(timezone.utc)
            inactive = []
            for pid in engine.get_participants():
                info = engine.get_participant_info(pid)
                if not info:
                    continue
                last_seen_str = info.get("last_seen", "")
                if not last_seen_str:
                    inactive.append(pid)
                    continue
                try:
                    last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))
                    if (now - last_seen).days > days:
                        inactive.append(pid)
                except (ValueError, TypeError):
                    inactive.append(pid)
            return inactive
        except Exception:
            return []

    def clean_mailboxes(self, dry_run: bool = True) -> Dict[str, Any]:
        orphans = self.scan_orphan_mailboxes()
        mailboxes_dir = self.base_path / "mailboxes"
        result = {
            "orphans_found": orphans,
            "deleted": [],
            "errors": [],
            "dry_run": dry_run
        }
        for orphan in orphans:
            orphan_path = mailboxes_dir / orphan
            try:
                if dry_run:
                    result["deleted"].append(f"[DRY] {orphan}")
                else:
                    shutil.rmtree(orphan_path)
                    result["deleted"].append(orphan)
            except Exception as e:
                result["errors"].append(str(e))
        return result

    def render_mailbox_status(self) -> str:
        orphans = self.scan_orphan_mailboxes()
        inactive = self.scan_inactive_participants()
        registered = self._get_registered_participants()

        lines = [
            "--- BUZONES ---",
            "",
            f"Participantes registrados: {len(registered)}",
            f"Buzones huerfanos (sin registro): {len(orphans)}",
            f"Inactivos >30 dias: {len(inactive)}",
            ""
        ]
        if orphans:
            lines.append("Huerfanos:")
            for o in orphans:
                lines.append(f"  - {o}")
            lines.append("")
        if inactive:
            lines.append("Inactivos:")
            for i in inactive:
                lines.append(f"  - {i}")
            lines.append("")
        lines.append("  Ejecutar: dashboard.clean_mailboxes(dry_run=True)")
        return "\n".join(lines)

    def render_status(self) -> str:
        """Renderiza el estado del conserje."""
        scan_results = self.scan()

        total_cleanable = (
            len(scan_results.get('pycache', [])) +
            len(scan_results.get('temp', [])) +
            len(scan_results.get('git_untracked', []))
        )

        lines = [
            "--- CONSERJE AUTOMATICO ---",
            "",
            f"Archivos limpiables: {total_cleanable}",
            f"  - Directorios __pycache__: {len(scan_results.get('pycache', []))}",
            f"  - Archivos temporales: {len(scan_results.get('temp', []))}",
            f"  - Sin versionar Git: {len(scan_results.get('git_untracked', []))}",
            ""
        ]

        if self.last_clean:
            lines.append(f"Ultima limpieza: {self.last_clean.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append(f"Total limpiezas: {self.clean_count}")
        else:
            lines.append("Nunca se ha ejecutado limpieza")

        lines.append("")
        lines.append("  Ejecutar: dashboard.clean(dry_run=False)")
        lines.append("  Simular: dashboard.clean(dry_run=True)")

        return "\n".join(lines)