"""Brand logos for the AIs: a ring in our colour with the real logo inside.

- CI guards, with no browser: the SVGs for the default catalogue's brands are present,
  auto-alojados en execution/templates/logos/, y el frontend cablea el mapa
  modelo→logo (`logoFor`/`aiAvatar`/`LOGO_RULES`), referencia `/static/logos/` y
  and the FALLBACK to an initial is kept for models with no logo.
- Browser test (Playwright, skipped in CI without the binary): the dropdown paints
  an <img> from /static/logos/ for a known bot, and the initial for an unknown one.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent            # execution/
LOGOS = ROOT / "templates" / "logos"
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

# Brands in the default catalogue (BOTS_CONFIG) that MUST have their own logo.
BRANDS = ["openai", "claude", "gemini", "qwen", "minimax", "deepseek", "kimi", "glm"]


class TestLogosAutoAlojados(unittest.TestCase):
    def test_svgs_de_marca_existen(self):
        for b in BRANDS:
            f = LOGOS / f"{b}.svg"
            self.assertTrue(f.exists(), f"falta el logo auto-alojado {f.name}")
            txt = f.read_text(encoding="utf-8", errors="ignore")
            self.assertIn("<svg", txt, f"{f.name} no parece un SVG")

    def test_no_se_enlazan_de_fuera(self):
        # logos are served from /static/logos/, never from an external domain
        self.assertIn("/static/logos/", INDEX)
        self.assertNotRegex(
            INDEX, r'src="https?://[^"]*logos',
            "los logos deben ser auto-alojados, no enlazados de fuera",
        )


class TestCableadoFrontend(unittest.TestCase):
    def test_helpers_presentes(self):
        for token in ("LOGO_RULES", "function logoFor", "function aiAvatar", "ai-avatar"):
            self.assertIn(token, INDEX, f"falta '{token}' en index.html")

    def test_cada_marca_tiene_regla_y_fichero(self):
        # every brand in the catalogue resolves through a rule pointing at an existing SVG
        rules = re.search(r"const LOGO_RULES=\[(.*?)\];", INDEX, re.S)
        self.assertIsNotNone(rules, "no encuentro LOGO_RULES")
        block = rules.group(1)
        for b in BRANDS:
            self.assertIn(f"'{b}'", block, f"ninguna regla apunta a '{b}'")

    def test_plan_b_inicial(self):
        # aiAvatar falls back to the initial when there is no logo (unknown model, or the moderator)
        self.assertIn("return null;", INDEX)           # logoFor sin coincidencia
        self.assertRegex(INDEX, r"opts\.name\|\|id.*\)\[0\]\.toUpperCase\(\)")

    def test_export_svg_en_linea(self):
        # exported HTML is self-contained: the SVG is embedded (AI_LOGO_SVG) through opts.inline,
        # not <img src="/static/logos/">. Every catalogue brand is in the embedded dictionary.
        self.assertIn("const AI_LOGO_SVG=", INDEX)
        self.assertIn("opts.inline", INDEX)             # rama en línea de aiAvatar
        self.assertIn("inline:true", INDEX)             # export/galería la usan
        block = re.search(r"const AI_LOGO_SVG=\{(.*?)\};", INDEX, re.S)
        self.assertIsNotNone(block, "no encuentro AI_LOGO_SVG")
        for b in BRANDS:
            self.assertIn(f'"{b}"', block.group(1), f"AI_LOGO_SVG sin '{b}'")


# ── Test de navegador (fixtures de conftest: browser + server). Se salta en CI. ──
def test_desplegable_pinta_logo_y_fallback(browser, server):
    pg = browser.new_page()
    pg.goto(server, wait_until="load")
    pg.wait_for_timeout(800)
    # test participants: one with a logo (gpt) and one without (mimo, which falls back)
    parts = [
        {"id": "gpt", "role": "creativo", "type": "bot", "status": "active"},
        {"id": "mimo", "role": "analista", "type": "bot", "status": "active"},
    ]
    html = pg.evaluate(
        "(ps)=>{ participants=ps; buildSenderColors(); "
        "return ps.map(p=>renderAgentRow(p,false)).join(''); }", parts)
    assert '/static/logos/openai.svg' in html, "gpt debería pintar el logo de OpenAI"
    # mimo has no logo, so the ring shows the initial 'M' and no <img>
    row_mimo = html.split('data-id="mimo"')[1]
    assert "/static/logos/" not in row_mimo, "mimo no debería tener logo"
    assert ">M<" in row_mimo, "mimo debería caer a la inicial"


if __name__ == "__main__":
    unittest.main()
