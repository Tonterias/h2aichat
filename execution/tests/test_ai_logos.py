"""FASE 38.3 — Logos comerciales de las IAs (aro con nuestro color + logo real dentro).

- Guardas CI (sin navegador): los SVG de las marcas del catálogo por defecto están
  auto-alojados en execution/templates/logos/, y el frontend cablea el mapa
  modelo→logo (`logoFor`/`aiAvatar`/`LOGO_RULES`), referencia `/static/logos/` y
  conserva el PLAN B (caída a la inicial) para modelos sin logo.
- Test de navegador (Playwright, se salta en CI sin binario): el desplegable pinta
  un <img> de /static/logos/ para un bot conocido y la inicial para uno desconocido.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent            # execution/
LOGOS = ROOT / "templates" / "logos"
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

# Marcas del catálogo por defecto (BOTS_CONFIG) que DEBEN tener logo propio.
BRANDS = ["openai", "claude", "gemini", "qwen", "minimax", "deepseek", "kimi", "glm"]


class TestLogosAutoAlojados(unittest.TestCase):
    def test_svgs_de_marca_existen(self):
        for b in BRANDS:
            f = LOGOS / f"{b}.svg"
            self.assertTrue(f.exists(), f"falta el logo auto-alojado {f.name}")
            txt = f.read_text(encoding="utf-8", errors="ignore")
            self.assertIn("<svg", txt, f"{f.name} no parece un SVG")

    def test_no_se_enlazan_de_fuera(self):
        # los logos se sirven desde /static/logos/, nunca desde un dominio externo
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
        # cada marca del catálogo se resuelve por una regla que apunta a un SVG existente
        rules = re.search(r"const LOGO_RULES=\[(.*?)\];", INDEX, re.S)
        self.assertIsNotNone(rules, "no encuentro LOGO_RULES")
        block = rules.group(1)
        for b in BRANDS:
            self.assertIn(f"'{b}'", block, f"ninguna regla apunta a '{b}'")

    def test_plan_b_inicial(self):
        # aiAvatar cae a la inicial cuando no hay logo (modelo desconocido / moderador)
        self.assertIn("return null;", INDEX)           # logoFor sin coincidencia
        self.assertRegex(INDEX, r"opts\.name\|\|id.*\)\[0\]\.toUpperCase\(\)")

    def test_export_svg_en_linea(self):
        # los HTML exportados son autocontenidos: SVG embebido (AI_LOGO_SVG) via opts.inline,
        # no <img src="/static/logos/">. Cada marca del catálogo está en el diccionario embebido.
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
    # participantes de prueba: uno con logo (gpt) y uno sin logo (mimo -> inicial)
    parts = [
        {"id": "gpt", "role": "creativo", "type": "bot", "status": "active"},
        {"id": "mimo", "role": "analista", "type": "bot", "status": "active"},
    ]
    html = pg.evaluate(
        "(ps)=>{ participants=ps; buildSenderColors(); "
        "return ps.map(p=>renderAgentRow(p,false)).join(''); }", parts)
    assert '/static/logos/openai.svg' in html, "gpt debería pintar el logo de OpenAI"
    # mimo no tiene logo -> inicial 'M' en el aro, sin <img>
    row_mimo = html.split('data-id="mimo"')[1]
    assert "/static/logos/" not in row_mimo, "mimo no debería tener logo"
    assert ">M<" in row_mimo, "mimo debería caer a la inicial"


if __name__ == "__main__":
    unittest.main()
