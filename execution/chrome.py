#!/usr/bin/env python3
"""FASE 36.2 (refactor) — CHROME compartido: header (nav) y footer en UN solo sitio.

Antes el header/footer vivian DUPLICADOS: escritos a mano dentro de la landing
(`indexweb.html`) y COPIADOS en el banco (`public_index.py`) -> se desincronizaban (el PO
lo detecto: el banco no tenia About ni el tema PRE-PROD). Ahora ambos montan estos
componentes desde aqui. Dos modos:
  - "spa"    -> la landing (usa navTo() y los divs de estado de login; se inyecta en
               indexweb.html sustituyendo los marcadores <!--CHROME_NAV/FOOTER-->).
  - "static" -> paginas server-side sueltas (el banco /preguntas): enlaces reales.
La marca de PRE-PROD (tema azul + insignia) se enciende por hostname (`staging.*`) con el
MISMO snippet en todas las paginas -> el banco la hereda sin tocar nada.
"""
import html as _html

from i18n import TRANSLATIONS


def _t(lang, key):
    return TRANSLATIONS.get(lang, TRANSLATIONS["es"]).get(key, key)


def _e(s):
    return _html.escape(s or "", quote=True)


def render_nav(lang, active="", mode="static"):
    tagline, home = _t(lang, "web.nav.tagline"), _t(lang, "web.nav.home")
    about, convs = _t(lang, "web.nav.about"), _t(lang, "web.nav.conversations")
    login, register = _t(lang, "web.nav.login"), _t(lang, "web.nav.register")
    logo = ('<img src="/static/logo.png" alt="H2AI Chat" class="nav-logo-mark" '
            'style="background:none;object-fit:contain">')
    brand = ('<div style="display:flex;flex-direction:column;line-height:1.1">'
             '<div style="display:flex;align-items:center;gap:6px"><span class="nav-logo-text">H2AI Chat</span>'
             '<span class="beta-badge" id="envBadge">Beta</span></div>'
             f'<span class="nav-logo-tagline">{_e(tagline)}</span></div>')
    langsw = ('<div class="langsw" aria-label="Language">'
              '<a class="lang-es" href="?lang=es" title="Español">ES</a>'
              '<a class="lang-en" href="?lang=en" title="English">EN</a></div>')

    def cls(name):
        return "nav-link active" if active == name else "nav-link"

    if mode == "spa":
        logo_wrap = f'<div class="nav-logo" onclick="navTo(\'home\')">{logo}{brand}</div>'
        links = ('<div class="nav-links" id="navPublic">'
                 f'<a class="nav-link" href="#" data-nav="home" onclick="navTo(\'home\')">{_e(home)}</a>'
                 f'<a class="nav-link" href="#" data-nav="about" onclick="navTo(\'about\')">{_e(about)}</a>'
                 f'<a class="nav-link" href="/preguntas">{_e(convs)}</a></div>')
        actions = ('<div class="nav-actions" id="navPublicActions" style="display:none">'
                   f'<button class="btn-ghost" onclick="navTo(\'login\')">{_e(login)}</button>'
                   f'<button class="btn-primary" onclick="navTo(\'register\')">{_e(register)}</button></div>'
                   '<div class="nav-actions" id="navAuth" style="display:none">'
                   '<button class="btn-ghost"><i class="ti ti-bell"></i></button>'
                   '<div class="nav-logo-mark" style="width:26px;height:26px;border-radius:50%;font-size:11px">M</div></div>')
    else:
        logo_wrap = f'<a class="nav-logo" href="/web">{logo}{brand}</a>'
        links = ('<div class="nav-links">'
                 f'<a class="{cls("home")}" href="/web">{_e(home)}</a>'
                 f'<a class="{cls("about")}" href="/web#about">{_e(about)}</a>'
                 f'<a class="{cls("conversations")}" href="/preguntas">{_e(convs)}</a></div>')
        # id="navPublicActions" -> auth_js() lo intercambia por "Mi cuenta"/"Ir al chat" si hay sesion.
        actions = ('<div class="nav-actions" id="navPublicActions">'
                   f'<a class="btn-ghost" href="/web">{_e(login)}</a>'
                   f'<a class="btn-primary" href="/web">{_e(register)}</a></div>')
    return f'<nav class="nav" id="mainNav"><div class="nav-inner">{logo_wrap}{links}{langsw}{actions}</div></nav>'


def _js_str(s):
    return (s or "").replace("\\", "\\\\").replace("'", "\\'")


def auth_js(lang):
    """FASE 36.2 — en paginas SUELTAS (banco), refleja la sesion en el nav igual que la home:
    si hay token en localStorage, cambia Entrar/Probar gratis por Mi cuenta/Ir al chat.
    Mismo origen y misma clave 'h2ai_token' -> coherente con la landing (sin parecer deslogueo)."""
    account = _js_str(_t(lang, "web.nav.account"))
    gotochat = _js_str(_t(lang, "web.account.gotochat"))
    return ("<script>(function(){var a=document.getElementById('navPublicActions');"
            "if(a&&localStorage.getItem('h2ai_token')){"
            'a.innerHTML=\'<a class="btn-ghost" href="/web#cuenta">' + account + '</a>'
            '<a class="btn-primary" href="/chat">' + gotochat + '</a>\';}})();</script>')


def render_footer(lang, mode="static"):
    community = _t(lang, "web.footer.community")
    tagline = _t(lang, "web.footer.tagline")
    privacy, terms = _t(lang, "web.footer.privacy"), _t(lang, "web.footer.terms")
    nocookies, copyr = _t(lang, "web.footer.nocookies"), _t(lang, "web.footer.copyright")
    if mode == "spa":
        pv = f'<a href="#" onclick="navTo(\'privacidad\')" style="color:var(--text3);font-size:11px">{_e(privacy)}</a>'
        tm = f'<a href="#" onclick="navTo(\'terminos\')" style="color:var(--text3);font-size:11px">{_e(terms)}</a>'
        nc = f'<a href="#" onclick="navTo(\'privacidad\')" style="color:var(--text3);font-size:11px">{_e(nocookies)}</a>'
    else:
        pv = f'<a href="/web#privacidad" style="color:var(--text3);font-size:11px">{_e(privacy)}</a>'
        tm = f'<a href="/web#terminos" style="color:var(--text3);font-size:11px">{_e(terms)}</a>'
        nc = f'<a href="/web#privacidad" style="color:var(--text3);font-size:11px">{_e(nocookies)}</a>'
    icon = lambda i, t: f'<a href="#" style="color:var(--text2);font-size:20px" title="{t}"><i class="ti ti-{i}"></i></a>'
    return (
        '<footer class="footer" style="text-align:center;padding:60px 24px 40px;color:var(--text3);font-size:12px;line-height:2">'
        f'<div style="font-weight:700;color:var(--text);margin-bottom:20px">{_e(community)}</div>'
        '<div style="display:flex;justify-content:center;gap:16px;margin-bottom:24px">'
        + icon("brand-x", "X (Twitter)") + icon("brand-discord", "Discord")
        + icon("brand-github", "GitHub") + icon("mail", "Contacto") + '</div>'
        f'<p style="max-width:400px;margin:0 auto 30px;font-size:13px;color:var(--text2)">{_e(tagline)}</p>'
        '<div style="display:flex;justify-content:center;gap:16px;flex-wrap:wrap;margin-bottom:12px">'
        + pv + tm + nc + '</div>'
        f'<p>{_e(copyr)}</p></footer>'
    )


# CSS del chrome (nav + footer + variables) para PAGINAS SUELTAS (el banco). La landing ya
# lleva su copia inline; aqui vive la version para lo demas. Incluye el tema PRE-PROD.
CHROME_CSS = (
    ":root{--pink:#E8186E;--pink-light:#FFF0F6;--pink-border:#F9A8C9;--pink-dark:#C9145F;"
    "--bg:#F6F5F2;--surface:#FFFFFF;--surface2:#F0EEE9;--border:rgba(0,0,0,0.08);"
    "--border2:rgba(0,0,0,0.14);--text:#1A1A1A;--text2:#5A5855;--text3:#9A9793;--r-sm:8px;"
    "--sans:'Syne',sans-serif;--shadow-pink:0 4px 20px rgba(232,24,110,0.22)}"
    "a{text-decoration:none;color:inherit}"
    ".nav{position:fixed;top:0;left:0;right:0;z-index:100;height:60px;background:rgba(246,245,242,0.85);"
    "backdrop-filter:blur(12px);border-bottom:0.5px solid var(--border);display:flex;align-items:center;padding:0 24px}"
    ".nav-inner{display:flex;align-items:center;width:100%;max-width:1200px;margin:0 auto}"
    ".nav-logo{display:flex;align-items:center;gap:9px;margin-right:auto}"
    ".nav-logo-mark{width:30px;height:30px;border-radius:8px;flex-shrink:0}"
    ".nav-logo-text{font-size:15px;font-weight:700;letter-spacing:-0.3px}"
    ".nav-logo-tagline{font-size:9px;font-weight:500;color:var(--text2);letter-spacing:0.1px}"
    # UX3-2: la insignia Beta NO se muestra en el nav (Beta vive en el cuerpo de la home). Solo
    # reaparece en STAGING como aviso AZUL de PRE-PROD (el azul es la senal de entorno de pruebas del PO).
    ".beta-badge{display:none;font-size:9px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;color:var(--pink);"
    "background:var(--pink-light);border:0.5px solid var(--pink-border);border-radius:5px;padding:2px 5px;margin-left:7px}"
    "body.staging-env .nav{background:rgba(214,228,251,0.92);border-bottom-color:#bcd3f5}"
    "body.staging-env .beta-badge{display:inline-block;color:#1A5FB4;background:#D6E4FB;border-color:#bcd3f5}"
    ".nav-links{display:flex;align-items:center;gap:4px;margin:0 24px}"
    ".nav-link{padding:6px 12px;font-size:13px;font-weight:500;color:var(--text2);border-radius:var(--r-sm);transition:all .15s}"
    ".nav-link:hover{background:var(--surface2);color:var(--text)}.nav-link.active{color:var(--pink)}"
    ".langsw{display:flex;align-items:center;gap:4px;font-size:13px;font-weight:600;margin:0 14px}"
    ".langsw a{color:var(--text2);opacity:0.5;padding:2px 5px;border-radius:var(--r-sm);transition:all .15s}"
    ".langsw a:hover{opacity:0.85}"
    'html[lang="es"] .langsw .lang-es,html[lang="en"] .langsw .lang-en{opacity:1;color:var(--pink)}'
    ".nav-actions{display:flex;align-items:center;gap:8px}"
    ".btn-ghost{display:inline-block;padding:7px 16px;font-size:13px;font-weight:500;color:var(--text2);border-radius:var(--r-sm)}"
    ".btn-ghost:hover{background:var(--surface2);color:var(--text)}"
    ".btn-primary{display:inline-block;padding:8px 18px;font-size:13px;font-weight:600;color:#fff;background:var(--pink);"
    "border-radius:var(--r-sm);box-shadow:var(--shadow-pink)}.btn-primary:hover{background:var(--pink-dark)}"
    ".footer{border-top:0.5px solid var(--border)}.footer a{color:var(--pink)}"
    # UX3-3: los enlaces Inicio/Acerca de/Conversaciones se ocultan cuando no caben (tablet portrait
    # incluida); reaparecen en ancho (landscape/escritorio). UX3-2: ES/EN en columna en movil estrecho.
    "@media(max-width:960px){.nav-links{display:none}}"
    "@media(max-width:768px){.langsw{flex-direction:column;gap:0;line-height:1.05;margin:0 8px}.nav-logo-text{white-space:nowrap}}"
)

# Marca de PRE-PROD por hostname (mismo snippet que la landing) -> tema azul + insignia.
STAGING_JS = ("<script>if(/^staging\\./.test(location.hostname)){document.body.classList.add('staging-env');"
              "document.title='[PRE-PROD] '+document.title;var b=document.getElementById('envBadge');"
              "if(b)b.textContent='PRE-PROD';}</script>")
