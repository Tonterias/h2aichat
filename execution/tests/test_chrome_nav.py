"""FASE 20.1-UX (Addendum UX3) — Guarda de la cabecera compartida (chrome.py).

Pins the invariants of the mobile header tweaks so they do not break by accident:
- the Beta badge is NOT shown in the nav by default (Beta lives in the home page body),
- but it DOES come back on STAGING as a blue notice, blue being the signal for staging,
- el nav conserva el span `envBadge` (el JS de staging le pone el texto PRE-PROD),
- and there are responsive rules hiding the nav links on a narrow screen.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import chrome


class TestChromeNav(unittest.TestCase):
    def test_nav_conserva_envBadge(self):
        # the span must still exist so STAGING_JS can put 'PRE-PROD' in it
        html = chrome.render_nav("es", mode="spa")
        self.assertIn('id="envBadge"', html)

    def test_beta_oculta_por_defecto(self):
        # in production the Beta badge does not belong in the nav
        self.assertIn(".beta-badge{display:none", chrome.CHROME_CSS)

    def test_beta_reaparece_azul_en_staging(self):
        # the staging notice, in blue, is kept
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
