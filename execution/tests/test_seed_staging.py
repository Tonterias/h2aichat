"""FASE 30 — Test del sembrado de la BD de staging (copia consistente de PROD)."""
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from seed_staging_db import seed


class TestSeedStaging(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_db(self, path: Path):
        c = sqlite3.connect(str(path))
        c.execute("CREATE TABLE t(x INTEGER)")
        c.execute("INSERT INTO t VALUES (42)")
        c.commit()
        c.close()

    def test_copia_consistente_y_crea_directorio(self):
        src = self.tmp / "prod.db"
        dest = self.tmp / "staging" / "humania.db"  # subdir inexistente: lo crea
        self._make_db(src)
        seed(src, dest, force=False)
        self.assertTrue(dest.exists())
        d = sqlite3.connect(str(dest))
        val = d.execute("SELECT x FROM t").fetchone()[0]
        d.close()
        self.assertEqual(val, 42)

    def test_no_sobrescribe_sin_force(self):
        src = self.tmp / "prod.db"
        dest = self.tmp / "dest.db"
        self._make_db(src)
        dest.write_text("no me pises")
        with self.assertRaises(SystemExit):
            seed(src, dest, force=False)

    def test_force_sobrescribe(self):
        src = self.tmp / "prod.db"
        dest = self.tmp / "dest.db"
        self._make_db(src)
        dest.write_text("viejo")
        seed(src, dest, force=True)  # no lanza
        d = sqlite3.connect(str(dest))
        self.assertEqual(d.execute("SELECT x FROM t").fetchone()[0], 42)
        d.close()

    def test_falla_si_no_existe_origen(self):
        with self.assertRaises(SystemExit):
            seed(self.tmp / "no_existe.db", self.tmp / "dest.db", force=False)


if __name__ == "__main__":
    unittest.main()
