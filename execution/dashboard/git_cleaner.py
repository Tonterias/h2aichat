from pathlib import Path
from datetime import datetime
import subprocess
import shutil


class GitCleaner:
    """
    Limpia marcas de Git (untracked files, pycache, etc).
    """

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or Path.cwd()
        self.git_dir = self.base_path / '.git'

    def _run_git(self, *args) -> subprocess.CompletedProcess:
        """Ejecuta un comando git."""
        result = subprocess.run(
            ['git', '-C', str(self.base_path)] + list(args),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        return result

    def get_status(self) -> dict:
        """Obtiene el estado actual del repositorio."""
        result = self._run_git('status', '--porcelain')

        untracked = []
        modified = []
        staged = []

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue

            status = line[:2]
            filepath = line[3:]

            if status == '??':
                untracked.append(filepath)
            elif 'M' in status:
                modified.append(filepath)
            elif status in ('A ', 'M '):
                staged.append(filepath)

        return {
            'untracked': untracked,
            'modified': modified,
            'staged': staged,
            'clean': len(untracked) == 0 and len(modified) == 0
        }

    def clean_untracked(self, force: bool = False) -> dict:
        """Limpia archivos sin tracking de Git."""
        if force:
            result = self._run_git('clean', '-fd')
        else:
            result = self._run_git('clean', '-nd')

        return {
            'output': result.stdout,
            'errors': result.stderr,
            'returncode': result.returncode
        }

    def clean_pycache(self, force: bool = False) -> list:
        """Elimina todos los __pycache__ del repositorio."""
        deleted = []
        pycache_dirs = list(self.base_path.rglob('__pycache__'))

        for pc_dir in pycache_dirs:
            try:
                if force:
                    shutil.rmtree(pc_dir)
                    deleted.append(str(pc_dir))
                    print(f"  [DEL] {pc_dir}")
            except Exception as e:
                print(f"  [ERR] {pc_dir}: {e}")

        return deleted

    def clean_all(self, dry_run: bool = True) -> dict:
        """
        Ejecuta limpieza completa.
        Elimina untracked files y __pycache__.
        """
        summary = {
            'pycache_deleted': [],
            'git_clean_output': '',
            'total_deleted': 0
        }

        summary['pycache_deleted'] = self.clean_pycache(force=not dry_run)

        if dry_run:
            result = self._run_git('clean', '-nd')
        else:
            result = self._run_git('clean', '-fd')

        summary['git_clean_output'] = result.stdout
        summary['total_deleted'] = len(summary['pycache_deleted'])

        return summary