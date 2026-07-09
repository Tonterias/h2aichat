"""FASE 20.1-UX (Addendum UX3) — Guarda de la cabecera compartida (chrome.py).

Fija los invariantes de los retoques de cabecera en movil, para que no se rompan sin querer:
- la insignia Beta NO se muestra en el nav por defecto (Beta vive en el cuerpo de la home),
- pero SIGUE reapareciendo en STAGING como aviso azul (el color azul es la senal de PRE-PROD),
- el nav conserva el span `envBadge` (el JS de staging le pone el texto PRE-PROD),
- y hay reglas responsive para ocultar los enlaces de nav en pantalla estrecha.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import chrome


class TestChromeNav(unittest.TestCase):
    def test_nav_conserva_envBadge(self):
        # el span debe seguir existiendo para que STAGING_JS le ponga 'PRE-PROD'
        html = chrome.render_nav("es", mode="spa")
        self.assertIn('id="envBadge"', html)

    def test_beta_oculta_por_defecto(self):
        # UX3-2: en produccion la insignia Beta no va en el nav
        self.assertIn(".beta-badge{display:none", chrome.CHROME_CSS)

    def test_beta_reaparece_azul_en_staging(self):
        # el aviso de entorno de pruebas (azul) se conserva
        self.assertIn("body.staging-env .beta-badge{display:inline-block", chrome.CHROME_CSS)
        self.assertIn("#1A5FB4", chrome.CHROME_CSS)  # el azul

    def test_navlinks_se_ocultan_en_estrecho(self):
        # UX3-3: enlaces de nav ocultos cuando no caben (tablet portrait incluida)
        self.assertIn("@media(max-width:960px){.nav-links{display:none}}", chrome.CHROME_CSS)

    def test_langsw_vertical_en_movil(self):
        # UX3-2: ES/EN en columna en movil estrecho
        self.assertIn("flex-direction:column", chrome.CHROME_CSS)


if __name__ == "__main__":
    unittest.main()
