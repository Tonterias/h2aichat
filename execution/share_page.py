#!/usr/bin/env python3
"""FASE 34 (T2) — Render SERVER-SIDE de una conversacion compartida.

La pagina publica /c/<token> se dibuja AQUI, a partir del snapshot (datos en crudo:
mensajes + nombre del moderador + idioma). El servidor escapa el texto el mismo
(anti-XSS, porque es una pagina publica) y aplica un markdown minimo. Reproduce la
estetica del export del chat (burbujas estilo WhatsApp) + tarjeta social (Open Graph)
+ marco i18n + pie "Hecho con H2AI Chat" para traer trafico.
"""
import re
import html as _html

from i18n import TRANSLATIONS

# Paleta portada del chat (execution/templates/index.html). Indice 0 = moderador.
PALETTE = [
    ("#333", "#FFF", "1.5px solid #999"),      # 0 moderador
    ("#6B4E8A", "#D6C7E8", "1px solid #6B4E8A"),
    ("#2D6A4F", "#C8E6D9", "1px solid #2D6A4F"),
    ("#3A6B99", "#BDD9ED", "1px solid #3A6B99"),
    ("#C47A3A", "#FFD9C0", "1px solid #C47A3A"),
    ("#8B7D2C", "#F9F0B8", "1px solid #8B7D2C"),
    ("#6B5E6E", "#D4CDD5", "1px solid #6B5E6E"),
    ("#B84C6E", "#F4D4E0", "1px solid #B84C6E"),
]

_CSS = (
    "*{margin:0;padding:0;box-sizing:border-box}"
    "body{font-family:system-ui,-apple-system,sans-serif;background:#F4F1EC;margin:0}"
    ".wrap{max-width:760px;margin:0 auto;padding:20px}"
    ".sharebar{position:sticky;top:0;z-index:10;background:rgba(246,245,242,.92);backdrop-filter:blur(12px);"
    "border-bottom:.5px solid #e0e0e0;display:flex;align-items:center;gap:8px;padding:10px 20px}"
    ".sharebar a.brand{display:flex;align-items:center;gap:8px;text-decoration:none;color:#1a1a1a;font-weight:700;font-size:14px}"
    ".sharebar img{width:24px;height:24px;object-fit:contain}"
    ".sharebar .cta{margin-left:auto;text-decoration:none;font-size:12px;font-weight:600;color:#fff;background:#E8186E;padding:6px 12px;border-radius:8px}"
    "header{text-align:center;margin-bottom:20px;padding:16px;background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.05)}"
    "header h1{font-size:18px;color:#D4537E;margin-bottom:4px}"
    ".qtitle{margin-bottom:4px}"
    ".qtitle summary{font-size:18px;font-weight:700;color:#D4537E;cursor:pointer;list-style:none;display:inline-block}"
    ".qtitle summary::-webkit-details-marker{display:none}"
    ".qtitle summary::after{content:' \\25BE';color:#999;font-size:12px}"
    ".qtitle[open] summary::after{content:' \\25B4'}"
    ".qtitle .qfull{font-size:14px;color:#5A5855;margin-top:8px;line-height:1.55;text-align:left}"
    "header p{font-size:11px;color:#999}"
    ".legend{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-bottom:16px}"
    ".legend-item{display:flex;align-items:center;gap:5px;font-size:11px;color:#555}"
    ".legend-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}"
    ".msg-row{display:flex;flex-direction:column;margin-bottom:10px;max-width:72%}"
    ".msg-row.left{align-items:flex-start;margin-right:auto}"
    ".msg-row.right{align-items:flex-end;margin-left:auto}"
    ".msg-row.center{align-items:center;margin:16px auto;max-width:74%}"
    ".bubble.wa{background:#fff;box-shadow:0 1px 1px rgba(0,0,0,.08);border:.5px solid rgba(0,0,0,.05);border-radius:10px;overflow:hidden;width:100%}"
    ".bubble-head{display:flex;align-items:center;gap:5px;font-size:11px;font-weight:700;padding:6px 12px}"
    ".bubble-head .bh-arrow,.bubble-head .bh-to{color:#999;font-weight:500}"
    ".bubble-body{padding:8px 12px 2px;font-size:12px;line-height:1.6;color:#333;word-break:break-word}"
    ".bubble-time{font-size:10px;color:#999;text-align:right;padding:0 12px 6px}"
    ".round-sep{text-align:center;font-size:9px;color:#ccc;text-transform:uppercase;letter-spacing:1px;margin:16px 0}"
    "footer{text-align:center;margin:24px 0 8px;font-size:12px;color:#888}"
    "footer a{color:#E8186E;text-decoration:none;font-weight:600}"
    ".bubble ul,.bubble ol{padding-left:18px;margin:4px 0}"
    ".bubble li{margin-bottom:2px}"
    ".bubble code{background:#f0f0f0;padding:1px 4px;border-radius:3px;font-size:11px}"
    ".bubble table{border-collapse:collapse;margin:6px 0;font-size:11px;width:100%;overflow-x:auto;display:block}"
    ".bubble th,.bubble td{border:1px solid #ddd;padding:4px 8px;text-align:left;vertical-align:top}"
    ".bubble th{background:#f5f5f5;font-weight:600}"
    ".bubble hr{border:none;border-top:1px solid #ddd;margin:8px 0}"
    ".bubble p{margin:0 0 4px}.bubble p:last-child{margin-bottom:0}"
)


def _cap(s):
    s = s or ""
    return s[:1].upper() + s[1:]


def _truncate_words(s, n):
    """Corta por PALABRA completa a <= n chars (no parte palabras). Devuelve (texto, truncado?)."""
    s = (s or "").strip()
    if len(s) <= n:
        return s, False
    cut = s[:n].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return (cut or s[:n]) + "…", True


def _plain(s, n=600):
    """Texto plano (sin HTML ni markdown), espacios colapsados, cap generoso."""
    s = re.sub(r"<[^>]*>", "", s or "")
    s = re.sub(r"[*_`#>]", "", s)
    return re.sub(r"\s+", " ", s).strip()[:n]


def _t(lang, key, default):
    return TRANSLATIONS.get(lang, TRANSLATIONS["es"]).get(key, default)


def _inline(s):
    """Escapa el texto (anti-XSS) y aplica markdown en linea (negrita/cursiva/codigo)."""
    s = _html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def _is_table_sep(line):
    """Fila separadora de una tabla GFM (|---|---| con dos por celda; admite : de alineacion)."""
    s = (line or "").strip()
    return bool(s) and "-" in s and "|" in s and bool(_TABLE_SEP_RE.match(s))


def _table_cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _md(text):
    """Markdown minimo y SEGURO: parrafos, saltos, listas (- / 1.), negrita/cursiva/codigo,
    TABLAS (GFM) y regla horizontal (---/***/___)."""
    lines = (text or "").split("\n")
    out, para, list_type = [], [], None

    def flush_para():
        if para:
            out.append("<p>" + "<br>".join(para) + "</p>")
            para.clear()

    def flush_list():
        nonlocal list_type
        if list_type:
            out.append("</%s>" % list_type)
            list_type = None

    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].strip()
        # Tabla GFM: fila de cabecera seguida de fila separadora
        if "|" in stripped and i + 1 < n and _is_table_sep(lines[i + 1]):
            flush_para(); flush_list()
            head = "".join("<th>" + _inline(c) + "</th>" for c in _table_cells(stripped))
            i += 2
            rows = []
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append("<tr>" + "".join("<td>" + _inline(c) + "</td>"
                                             for c in _table_cells(lines[i])) + "</tr>")
                i += 1
            out.append("<table><tr>" + head + "</tr>" + "".join(rows) + "</table>")
            continue
        if not stripped:
            flush_para(); flush_list(); i += 1; continue
        if re.match(r"^([-*_])\1{2,}$", stripped):       # regla horizontal
            flush_para(); flush_list(); out.append("<hr>"); i += 1; continue
        m_ul = re.match(r"^[-*]\s+(.*)$", stripped)
        m_ol = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m_ul or m_ol:
            flush_para()
            want = "ul" if m_ul else "ol"
            if list_type != want:
                flush_list(); out.append("<%s>" % want); list_type = want
            out.append("<li>" + _inline((m_ul or m_ol).group(1)) + "</li>")
        else:
            flush_list()
            para.append(_inline(stripped))
        i += 1
    flush_para(); flush_list()
    return "".join(out)


def _assign_colors(messages, mod_sender):
    """Asigna color por sender: moderador -> indice 0; bots por orden de aparicion -> 1..7."""
    colors = {mod_sender: PALETTE[0]}
    idx = 1
    for m in messages:
        s = m.get("sender")
        if s and s != mod_sender and s not in colors:
            colors[s] = PALETTE[min(idx, len(PALETTE) - 1)]
            idx += 1
    return colors


def _name(sender, mod_sender, mod_name):
    return mod_name if sender == mod_sender else _cap(sender)


def _render_body(snapshot, lang):
    """Leyenda + burbujas, replicando el export (estilo WhatsApp). `lang` = idioma del
    VISITANTE (para las etiquetas de ronda); el texto de los mensajes va tal cual."""
    messages = snapshot.get("messages", [])
    mod_sender = snapshot.get("mod_sender", "miguel")
    mod_name = snapshot.get("mod_name") or "Moderador"
    colors = _assign_colors(messages, mod_sender)

    # Leyenda (en orden: moderador + bots por aparicion)
    seen, legend_items = [], []
    for s in [mod_sender] + [m.get("sender") for m in messages]:
        if s and s not in seen and s in colors:
            seen.append(s)
            legend_items.append((colors[s][0], _name(s, mod_sender, mod_name)))
    legend = '<div class="legend">' + "".join(
        '<div class="legend-item"><div class="legend-dot" style="background:%s"></div>%s</div>'
        % (fg, _html.escape(nm)) for fg, nm in legend_items) + "</div>"

    start_lbl = _t(lang, "export.start", "Inicio")
    round_lbl = _t(lang, "export.new_round", "Nueva ronda")
    rows, c, last_hour = [], 0, None
    for i, m in enumerate(messages):
        sender = m.get("sender", "")
        recipient = m.get("recipient", "")
        ts = m.get("timestamp") or ""
        time = ts[11:19]
        hour = ts[11:16]
        is_mod = sender == mod_sender
        if not is_mod:
            c += 1
        side = "center" if is_mod else ("left" if c % 2 == 1 else "right")
        sep = ""
        if i == 0:
            sep = '<div class="round-sep">%s · %s</div>' % (_html.escape(start_lbl), time)
        elif hour != last_hour and not is_mod:
            sep = '<div class="round-sep">%s · %s</div>' % (_html.escape(round_lbl), time)
        last_hour = hour
        fg, bg, _border = colors.get(sender, PALETTE[0])
        if is_mod:
            head = ('<div class="bubble-head" style="background:%s"><span style="color:%s">%s</span></div>'
                    % (bg, fg, _html.escape(_name(sender, mod_sender, mod_name))))
        else:
            head = ('<div class="bubble-head" style="background:%s"><span style="color:%s">%s</span>'
                    '<span style="font-size:8px;font-weight:700;color:#fff;background:#6B4E00;border-radius:3px;padding:1px 4px;margin-left:4px">%s</span>'
                    '<span class="bh-arrow">&#8594;</span><span class="bh-to">%s</span></div>'
                    % (bg, fg, _html.escape(_cap(sender)), _html.escape(_t(lang, "ai.tag", "IA")),
                       _html.escape(_name(recipient, mod_sender, mod_name))))
        rows.append(
            '%s<div class="msg-row %s"><div class="bubble wa %s">%s<div class="bubble-body">%s</div>'
            '<div class="bubble-time">%s</div></div></div>'
            % (sep, side, side, head, _md(m.get("body", "")), time))
    return legend + "<main>" + "".join(rows) + "</main>"


def render_shared_page(snapshot, lang, base_url, token, embed=False):
    """Pagina publica completa: cabecera i18n + tarjeta social (OG/Twitter) + conversacion + pie.
    FASE 36.2: `embed=True` -> version "desnuda" (sin barra) para incrustar en blogs."""
    messages = snapshot.get("messages", [])
    count = snapshot.get("count", len(messages))
    # El titulo es la primera pregunta del moderador, derivada de los mensajes (siempre completa,
    # tambien en enlaces antiguos) -> no depende de un campo "title" que pudiera estar truncado.
    mod_sender = snapshot.get("mod_sender", "miguel")
    _first_q = next((m.get("body", "") for m in messages if m.get("sender") == mod_sender),
                    (messages[0].get("body", "") if messages else ""))
    title_full = _plain(_first_q) or "H2AI Chat"
    title_short, _trunc = _truncate_words(title_full, 90)
    desc = (snapshot.get("desc") or "").strip()[:200]
    date = snapshot.get("date", "")
    content_lang = snapshot.get("lang", "es")

    msgs_lbl = _t(lang, "export.messages", "mensajes")
    made = _t(lang, "web.share.made_with", "Hecho con H2AI Chat")
    cta = _t(lang, "web.share.cta", "Crea tu propio debate entre IAs")

    og_img = base_url + "/static/og-share.png"
    og_url = base_url + "/c/" + token
    e = lambda s: _html.escape(s or "", quote=True)

    head = (
        '<!DOCTYPE html><html lang="%s"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">'
        '<meta name="ai-generated" content="true">'
        "<title>%s &middot; H2AI Chat</title>"
        '<meta name="description" content="%s">'
        '<meta property="og:type" content="article"><meta property="og:title" content="%s">'
        '<meta property="og:description" content="%s"><meta property="og:image" content="%s">'
        '<meta property="og:url" content="%s">'
        '<meta name="twitter:card" content="summary_large_image">'
        '<meta name="twitter:title" content="%s"><meta name="twitter:description" content="%s">'
        '<meta name="twitter:image" content="%s">'
        "<style>%s</style></head><body>"
        % (e(content_lang), e(title_short), e(desc), e(title_short), e(desc), e(og_img), e(og_url),
           e(title_short), e(desc), e(og_img), _CSS)
    )
    # FASE 36.2 (T5/T6): la pagina embebida no debe indexarse (canonical -> version normal).
    if embed:
        head = head.replace(
            "</head>",
            '<meta name="robots" content="noindex,follow">'
            '<link rel="canonical" href="%s"></head>' % e(og_url), 1)
    # FASE 36.2 (T7): boton "Insertar" + recuadro con el <iframe> (solo en la pagina normal).
    embed_url = base_url + "/c/" + token + "?embed=1"
    iframe = ('<iframe src="%s" width="100%%" height="600" '
              'style="border:1px solid #eee;border-radius:8px" loading="lazy"></iframe>' % embed_url)
    embed_lbl = "Embed" if lang == "en" else "Insertar"
    copy_lbl = "Copy" if lang == "en" else "Copiar"
    bar = (
        '<div class="sharebar"><a class="brand" href="%s/web">'
        '<img src="/static/logo.png" alt="H2AI Chat"> H2AI Chat</a>'
        '<button onclick="h2aiEmbedToggle()" style="margin-left:auto;border:1px solid #e0e0e0;'
        'background:#fff;border-radius:8px;padding:6px 12px;cursor:pointer;font-size:12px;font-weight:600">'
        '&lt;/&gt; %s</button>'
        '<a class="cta" href="%s/web" style="margin-left:8px">%s</a></div>'
        % (base_url, embed_lbl, base_url, e(cta))
    )
    embed_box = (
        '<div id="h2aiEmbedBox" style="display:none;background:#fff;border-bottom:1px solid #e0e0e0;padding:12px 20px">'
        '<div style="max-width:760px;margin:0 auto;display:flex;gap:8px;align-items:center">'
        '<textarea id="h2aiEmbedCode" readonly style="flex:1;height:46px;font-family:monospace;font-size:11px;'
        'border:1px solid #e0e0e0;border-radius:6px;padding:8px;resize:none">%s</textarea>'
        '<button onclick="h2aiEmbedCopy()" style="border:0;background:#E8186E;color:#fff;border-radius:6px;'
        'padding:8px 14px;cursor:pointer;font-size:12px;white-space:nowrap">%s</button></div></div>'
        '<script>function h2aiEmbedToggle(){var b=document.getElementById("h2aiEmbedBox");'
        'b.style.display=b.style.display==="none"?"block":"none";}'
        'function h2aiEmbedCopy(){var t=document.getElementById("h2aiEmbedCode");t.select();'
        'try{navigator.clipboard.writeText(t.value);}catch(e){document.execCommand("copy");}}</script>'
        % (e(iframe), copy_lbl)
    )
    if _trunc:
        title_html = ('<details class="qtitle"><summary>%s</summary>'
                      '<div class="qfull">%s</div></details>' % (e(title_short), e(title_full)))
    else:
        title_html = '<h1>%s</h1>' % e(title_full)
    header = ('<div class="wrap"><header>%s<p>%s %s%s</p></header>'
              % (title_html, count, e(msgs_lbl), (" &middot; " + e(date)) if date else ""))
    footer = ('<footer><a href="%s/web">%s</a></footer></div></body></html>'
              % (base_url, e(made)))
    # FASE 35 (AI Act Art. 50): aviso de contenido generado por IA, arriba (scrollea con la pagina).
    notice = ('<div style="background:#FFF3D6;border-bottom:1px solid #EBCF8A;color:#6B4E00;'
              'font-size:12px;line-height:1.5;padding:9px 18px;text-align:center">&#9888; %s</div>'
              % e(_t(lang, "ai.notice", "")))
    if embed:
        # Embebido: sin barra (ni boton) — solo aviso AI Act + conversacion + pie con enlace de vuelta.
        return head + notice + header + _render_body(snapshot, lang) + footer
    return head + bar + embed_box + notice + header + _render_body(snapshot, lang) + footer
