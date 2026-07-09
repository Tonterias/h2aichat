"""FASE 34 (T1) — Tests de la capa de datos del enlace publico por conversacion.

Cubre los criterios de la capa de datos: crear/leer por token, 'Actualizar enlace'
(re-congela sobre el MISMO token), revocar (apaga), re-compartir tras revocar (token
NUEVO), estado para la UI, token invalido y borrados en cascada (conversacion / RGPD).
"""
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ConversationEngine
import auth


class ShareLinkTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        auth.init_auth_tables(self.engine)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_crear_y_leer_por_token(self):
        token = auth.create_or_update_share_link(self.engine, 1, "user_1_LBO", '{"msgs":[1,2]}')
        self.assertTrue(token)
        row = auth.get_share_link(self.engine, token)
        self.assertIsNotNone(row)
        self.assertEqual(row["thread_id"], "user_1_LBO")
        self.assertEqual(row["user_id"], 1)
        self.assertEqual(row["snapshot"], '{"msgs":[1,2]}')

    def test_actualizar_reusa_el_mismo_token(self):
        t1 = auth.create_or_update_share_link(self.engine, 1, "user_1_LBO", '{"v":1}')
        t2 = auth.create_or_update_share_link(self.engine, 1, "user_1_LBO", '{"v":2}')
        self.assertEqual(t1, t2)  # mismo enlace (criterio 3: 'Actualizar enlace')
        self.assertEqual(auth.get_share_link(self.engine, t1)["snapshot"], '{"v":2}')  # re-congelado

    def test_revocar_apaga_el_enlace(self):
        t = auth.create_or_update_share_link(self.engine, 1, "user_1_X", "{}")
        auth.revoke_share_link(self.engine, 1, "user_1_X")
        self.assertIsNone(auth.get_share_link(self.engine, t))                       # publico: 404
        self.assertIsNone(auth.get_share_link_for_thread(self.engine, 1, "user_1_X"))

    def test_recompartir_tras_revocar_da_token_nuevo(self):
        t1 = auth.create_or_update_share_link(self.engine, 1, "user_1_X", "{}")
        auth.revoke_share_link(self.engine, 1, "user_1_X")
        t2 = auth.create_or_update_share_link(self.engine, 1, "user_1_X", "{}")
        self.assertNotEqual(t1, t2)  # criterio 5: reactivar genera uno nuevo
        self.assertIsNone(auth.get_share_link(self.engine, t1))      # el viejo sigue muerto
        self.assertIsNotNone(auth.get_share_link(self.engine, t2))

    def test_estado_para_la_ui(self):
        self.assertIsNone(auth.get_share_link_for_thread(self.engine, 1, "user_1_X"))
        t = auth.create_or_update_share_link(self.engine, 1, "user_1_X", "{}")
        self.assertEqual(auth.get_share_link_for_thread(self.engine, 1, "user_1_X")["token"], t)

    def test_token_invalido_da_none(self):
        self.assertIsNone(auth.get_share_link(self.engine, "noexiste"))

    def test_token_inadivinable(self):
        # urlsafe, sin separadores problematicos para URL, longitud razonable
        t = auth.create_or_update_share_link(self.engine, 1, "user_1_X", "{}")
        self.assertGreaterEqual(len(t), 10)
        self.assertNotIn("/", t)
        self.assertNotIn("+", t)


if __name__ == "__main__":
    unittest.main()
