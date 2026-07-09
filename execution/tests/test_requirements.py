"""FASE 37.1 — Guarda del sistema de dependencias con versiones fijadas.

Impide que se rompa la reproducibilidad:
- que `requirements.txt` / `requirements-dev.txt` existan y estén TODOS fijados con `==`,
- que la versión instalada coincida con la fijada (sin deriva),
- y, lo más importante, que **todo lo que el código de la app importa esté declarado**
  (para que "en mi máquina funciona porque lo instalé a mano" no vuelva a pasar).
"""
import ast
import importlib.metadata as im
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # raíz del repo
EXEC = ROOT / "execution"

# nombre en requirements -> nombre con el que se importa
PKG_TO_IMPORT = {"pyjwt": "jwt", "pyyaml": "yaml", "psycopg[binary]": "psycopg"}


def _deps(path: Path):
    """Líneas de dependencia (paquete==version), ignorando comentarios y `-r`."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        out.append(line)
    return out


class TestRequirements(unittest.TestCase):
    def setUp(self):
        self.runtime = ROOT / "requirements.txt"
        self.dev = ROOT / "requirements-dev.txt"

    def test_ficheros_existen(self):
        self.assertTrue(self.runtime.exists(), "falta requirements.txt")
        self.assertTrue(self.dev.exists(), "falta requirements-dev.txt")

    def test_todo_fijado_con_doble_igual(self):
        for f in (self.runtime, self.dev):
            for dep in _deps(f):
                self.assertIn("==", dep, f"{f.name}: '{dep}' no está fijado con ==")
                self.assertNotIn(">=", dep, f"{f.name}: '{dep}' usa rango, debe ser ==")
                self.assertNotIn("<", dep, f"{f.name}: '{dep}' usa rango, debe ser ==")

    def test_dev_incluye_el_runtime(self):
        self.assertIn("-r requirements.txt", self.dev.read_text(encoding="utf-8"))

    def test_version_instalada_coincide_con_la_fijada(self):
        for f in (self.runtime, self.dev):
            for dep in _deps(f):
                name, ver = dep.split("==")
                name = name.split("[")[0]  # psycopg[binary] -> psycopg
                try:
                    inst = im.version(name)
                except im.PackageNotFoundError:
                    self.fail(f"{name} declarado en {f.name} pero NO instalado")
                self.assertEqual(inst, ver, f"{name}: instalado {inst} != fijado {ver} ({f.name})")

    def test_todo_import_de_la_app_esta_declarado(self):
        """Cada módulo de terceros que importa el código de la app debe estar en requirements.txt."""
        declared = set()
        for dep in _deps(self.runtime):
            pkg = dep.split("==")[0].lower()
            declared.add(PKG_TO_IMPORT.get(pkg, pkg.split("[")[0]))
        # módulos locales (ficheros y subpaquetes de execution/)
        local = {p.stem for p in EXEC.rglob("*.py")}
        local |= {d.name for d in EXEC.iterdir() if d.is_dir()}
        stdlib = set(sys.stdlib_module_names)

        thirdparty = set()
        for py in EXEC.glob("*.py"):  # código de la app (nivel raíz de execution/)
            tree = ast.parse(py.read_text(encoding="utf-8-sig"))  # utf-8-sig tolera BOM
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for n in node.names:
                        thirdparty.add(n.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        thirdparty.add(node.module.split(".")[0])
        thirdparty -= stdlib
        thirdparty -= local
        faltan = sorted(m for m in thirdparty if m not in declared)
        self.assertEqual(faltan, [], f"imports de la app SIN declarar en requirements.txt: {faltan}")


if __name__ == "__main__":
    unittest.main()
