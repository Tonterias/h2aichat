"""FASE 36.2 — Tests del banco de preguntas (catalogo publico + ruta /preguntas)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import public_index


class TestCatalog(unittest.TestCase):
    def test_nivel0(self):  # criterio 3
        self.assertTrue(public_index.is_nivel0("es/conversationsindex.html"))
        self.assertTrue(public_index.is_nivel0("es/h2aichat_general_2026-05-30_143151.html"))
        self.assertTrue(public_index.is_nivel0("es/h2aichat_conversa5_2026-06-10_111157.html"))
        self.assertTrue(public_index.is_nivel0("es/Test_OpenRouter_20260523.html"))
        self.assertFalse(public_index.is_nivel0("es/h2aichat_ConcienciaArtificial_2026-06-19.html"))
        self.assertFalse(public_index.is_nivel0("es/SciFi_Peliculas_20260613.html"))

    def test_derive_title(self):  # criterio 2
        msgs = [{"sender": "miguel", "body": "**¿Qué** es la conciencia? Explícalo."}]
        t = public_index.derive_title(msgs)
        self.assertIn("¿Qué es la conciencia?", t)
        self.assertNotIn("**", t)  # markdown limpiado
        self.assertEqual(public_index.derive_title([]), "")

    def test_catalog_incluye_curadas_y_derivadas_y_excluye_nivel0(self):  # criterios 1,2,3
        items = public_index.build_catalog()
        by_rel = {it["rel"]: it for it in items}
        # curada: titulo de galeria
        cur = by_rel.get("es/h2aichat_ConcienciaArtificial_2026-06-19.html")
        self.assertIsNotNone(cur)
        self.assertEqual(cur["title"], "Conciencia artificial")
        self.assertTrue(cur["curated"])
        # no curada pero real: titulo derivado de la primera pregunta
        sci = by_rel.get("es/SciFi_Peliculas_20260613.html")
        self.assertIsNotNone(sci)
        self.assertFalse(sci["curated"])
        self.assertIn("película", sci["title"].lower())
        # Nivel 0 fuera
        self.assertNotIn("es/conversationsindex.html", by_rel)
        self.assertFalse(any("_general_" in r for r in by_rel))

    def test_ninguna_curada_cae_en_nivel0(self):
        import i18n
        for rel in i18n.GALLERY_SEO_INDEX:
            self.assertFalse(public_index.is_nivel0(rel), f"curada excluida por error: {rel}")


class TestBankRoute(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import api_server
        self.client = TestClient(api_server.app)

    def test_preguntas_es(self):  # criterios 1,4
        r = self.client.get("/preguntas")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Banco de preguntas", r.text)
        self.assertIn("Conciencia artificial", r.text)      # una curada
        self.assertIn('id="q"', r.text)                      # buscador
        self.assertIn("h2aiApply", r.text)                   # filtrado client-side
        self.assertIn('class="fchip', r.text)                # chips de filtro (tema/año)
        self.assertIn('rel="canonical"', r.text)

    def test_preguntas_en(self):
        r = self.client.get("/preguntas?lang=en")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Question bank", r.text)
        self.assertIn('lang="en"', r.text)

    def test_sitemap_incluye_preguntas(self):  # criterio 5
        r = self.client.get("/sitemap.xml")
        self.assertIn("/preguntas", r.text)

    def test_home_usa_chrome_compartido(self):  # AC-12/AC-13: chrome inyectado en la landing
        r = self.client.get("/web")
        self.assertEqual(r.status_code, 200)
        self.assertIn('href="/preguntas"', r.text)          # enlaces a /preguntas (nav + boton)
        self.assertIn("Ver todas las conversaciones", r.text)  # boton destacado tras la galeria
        self.assertIn("Conversaciones", r.text)              # enlace en el nav
        # el chrome se inyecto (no queda marcador ni el nav conserva sus IDs de SPA)
        self.assertNotIn("<!--CHROME_NAV-->", r.text)
        self.assertNotIn("<!--CHROME_FOOTER-->", r.text)
        self.assertIn('id="navPublic"', r.text)              # SPA: divs de estado intactos
        self.assertIn('id="envBadge"', r.text)
        self.assertIn("navTo('about')", r.text)

    def test_banco_usa_mismo_chrome_que_home(self):  # AC-13: header/footer = componente compartido
        r = self.client.get("/preguntas")
        self.assertIn('class="nav"', r.text)                 # mismo nav que la home
        self.assertIn('class="nav-logo"', r.text)
        self.assertIn('class="langsw"', r.text)              # mismo selector de idioma
        self.assertIn('href="/web#about"', r.text)           # About (enlace real desde el banco)
        self.assertIn('class="footer"', r.text)              # MISMO footer que la home
        self.assertIn('nav-link active', r.text)             # "Conversaciones" marcado activo
        self.assertIn("staging-env", r.text)                 # snippet PRE-PROD por hostname

    def test_banco_refleja_sesion(self):  # bug PO: al ir al banco parecia deslogueo
        r = self.client.get("/preguntas")
        self.assertIn('id="navPublicActions"', r.text)       # bloque intercambiable
        self.assertIn("h2ai_token", r.text)                  # comprueba el token (como la home)
        self.assertIn("/web#cuenta", r.text)                 # logado -> Mi cuenta
        self.assertIn('href="/chat"', r.text)                # logado -> Ir al chat

    def test_menu_es_traducido(self):  # PO: menu coherente por idioma
        r = self.client.get("/preguntas?lang=es")
        self.assertIn(">Inicio<", r.text)
        self.assertIn(">Acerca de<", r.text)
        self.assertIn(">Entrar<", r.text)
        self.assertNotIn(">Home<", r.text)                   # ya no hay ingles suelto en ES


if __name__ == "__main__":
    unittest.main()
