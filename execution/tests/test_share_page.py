"""FASE 34 (T2) — Tests del render SERVER-SIDE de la conversacion compartida."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import share_page

SNAP = {
    "desc": "Depende de la estrategia y la salud financiera previa.",
    "date": "26/06/2026",
    "lang": "es",
    "mod_sender": "miguel",
    "mod_name": "Miguel",
    "messages": [
        {"sender": "miguel", "recipient": "qwen_plus",
         "body": "¿Es **inteligente** endeudarse?", "timestamp": "2026-06-26T08:29:05"},
        {"sender": "qwen_plus", "recipient": "minimax",
         "body": "Depende.\n\n- Sinergias reales\n- Flujos de caja", "timestamp": "2026-06-26T08:29:20"},
        {"sender": "minimax", "recipient": "miguel",
         "body": "El timing importa.", "timestamp": "2026-06-26T08:45:00"},
    ],
}


class RenderTest(unittest.TestCase):
    def render(self, lang="es", token="AbC123"):
        return share_page.render_shared_page(SNAP, lang, "https://h2aichat.com", token)

    def test_estructura_y_contenido(self):
        h = self.render()
        self.assertIn('<html lang="es">', h)
        self.assertIn('rel="icon"', h)            # favicon en la pestaña
        self.assertIn("msg-row", h)
        self.assertIn("bubble-head", h)
        self.assertIn("endeudarse", h)            # texto del mensaje
        self.assertIn("Miguel", h)                # moderador con su nombre de cuenta

    def test_tarjeta_social_open_graph(self):
        h = self.render(token="AbC123")
        self.assertIn('property="og:title" content="¿Es inteligente endeudarse?"', h)  # derivado del 1er mensaje
        self.assertIn('property="og:description" content="Depende de la estrategia', h)
        self.assertIn('property="og:image" content="https://h2aichat.com/static/og-share.png"', h)
        self.assertIn('property="og:url" content="https://h2aichat.com/c/AbC123"', h)
        self.assertIn('name="twitter:card" content="summary_large_image"', h)

    def test_markdown_minimo(self):
        h = self.render()
        self.assertIn("<strong>inteligente</strong>", h)   # **bold**
        self.assertIn("<li>Sinergias reales</li>", h)       # lista

    def test_markdown_tablas_y_hr(self):
        # La tabla va en una respuesta de bot (no en el 1er mensaje, que es la pregunta-titulo)
        body = "| Punto | Conclusion |\n|---|---|\n| ¿Funcionan? | Si, **justificado**. |\n\n---"
        snap = dict(SNAP, messages=[
            {"sender": "miguel", "recipient": "q", "body": "¿Funcionan los prompts?", "timestamp": "2026-06-28T08:00:00"},
            {"sender": "q", "recipient": "miguel", "body": body, "timestamp": "2026-06-28T08:00:10"},
        ])
        h = share_page.render_shared_page(snap, "es", "https://h2aichat.com", "x")
        self.assertIn("<table>", h)
        self.assertIn("<th>Punto</th>", h)
        self.assertIn("<td>¿Funcionan?</td>", h)
        self.assertIn("<strong>justificado</strong>", h)   # markdown dentro de la celda
        self.assertIn("<hr>", h)
        self.assertNotIn("|---|", h)                        # nada de markdown crudo

    def test_anti_xss(self):
        snap = dict(SNAP, messages=[{"sender": "miguel", "recipient": "qwen_plus",
                                     "body": "<script>alert(1)</script> hola", "timestamp": "2026-06-26T08:29:05"}])
        h = share_page.render_shared_page(snap, "es", "https://h2aichat.com", "x")
        self.assertNotIn("<script>alert(1)</script>", h)    # NO ejecuta
        self.assertIn("&lt;script&gt;", h)                  # escapado

    def test_colores_moderador_y_bot(self):
        h = self.render()
        self.assertIn("background:#FFF", h)       # moderador = PALETTE[0]
        self.assertIn("background:#D6C7E8", h)    # primer bot = PALETTE[1]

    def test_separadores_de_ronda(self):
        h = self.render()
        self.assertIn("Inicio · 08:29:05", h)
        self.assertIn("Nueva ronda · 08:45:00", h)

    def test_i18n_ingles(self):
        h = self.render(lang="en")
        self.assertIn("messages", h)                     # cabecera EN
        self.assertNotIn("mensajes", h)
        self.assertIn("Made with H2AIChat.com", h)       # pie EN
        self.assertIn("Start · 08:29:05", h)             # separador EN
        self.assertIn("New round · 08:45:00", h)

    def test_titulo_corto_sin_desplegable(self):
        h = self.render()  # SNAP tiene titulo corto
        self.assertIn("<h1>", h)
        self.assertNotIn("<details", h)

    def test_titulo_largo_con_desplegable(self):
        # El titulo se deriva del PRIMER mensaje; una pregunta larga -> resumen cortado + desplegable completo
        longq = ("La IA no va a reemplazar a los equipos de datos, y quien diga lo contrario no "
                 "entiende de negocio. (Debate) que opinas tu sobre esto, con mas texto para superar los 90 chars")
        snap = dict(SNAP, messages=[{"sender": "miguel", "recipient": "qwen_plus",
                                     "body": longq, "timestamp": "2026-06-28T08:00:00"}])
        h = share_page.render_shared_page(snap, "es", "https://h2aichat.com", "x")
        self.assertIn("<details", h)     # desplegable nativo
        self.assertIn("…", h)            # cortado por palabra, con puntos suspensivos
        self.assertIn(longq, h)          # el texto COMPLETO esta (en el desplegable)
        self.assertNotIn("opinas tu sobre", h.split("<summary>")[1].split("</summary>")[0])  # el resumen NO llega tan lejos

    def test_pie_enlaza_a_la_home(self):
        h = self.render()
        self.assertIn("Hecho con H2AIChat.com", h)
        self.assertIn('href="https://h2aichat.com/web"', h)


if __name__ == "__main__":
    unittest.main()
