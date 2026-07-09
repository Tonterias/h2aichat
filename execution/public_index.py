#!/usr/bin/env python3
"""FASE 36.2 — Catalogo publico ("banco de preguntas").

Reune TODAS las conversaciones publicas (curadas + el resto), menos el Nivel 0
(indices, hilo 'general' de prueba, debug, duplicados numerados). Las curadas usan su
titulo/desc de la galeria; el resto deriva su titulo de la PRIMERA pregunta del moderador
(los HTML horneados llevan los mensajes en un JSON oculto). Asi el banco se llena SOLO,
sin mantener una segunda lista a mano. Fuente compartida con el SEO de la Fase 36.
"""
import html as _html
import json
import re
from pathlib import Path

import chrome
import i18n
from i18n import TRANSLATIONS
from seo import _iso_date
from share_page import _plain, _truncate_words

CONV_BASE = (Path(__file__).parent.parent / "conversations").resolve()

# Nivel 0: NO son conversaciones publicables (indices, hilo 'general' de prueba, debug,
# duplicados numerados tipo conv2/conversa5). Se excluyen del banco y del sitemap.
_NIVEL0_RE = re.compile(r"(?i)(?:^|/)(?:conversationsindex|test_|browserdialog)|_general_|conv(?:ersa)?\d")
_MSG_RE = re.compile(r'<script type="application/json" id="messages-data">(.*?)</script>', re.DOTALL)
_NAME_DATE_RE = re.compile(r"(20\d{2})-?(\d{2})-?(\d{2})")


def is_nivel0(rel):
    return bool(_NIVEL0_RE.search(rel))


def _messages(path):
    try:
        m = _MSG_RE.search(path.read_text(encoding="utf-8"))
        return json.loads(m.group(1)) if m else None
    except Exception:
        return None


def derive_title(messages, n=90):
    """Titulo = primera pregunta (el primer mensaje suele ser del moderador), en texto plano
    y cortado por palabra completa."""
    if not messages:
        return ""
    short, _ = _truncate_words(_plain(messages[0].get("body", ""), 300), n)
    return short


def _iso_from_name(name):
    m = _NAME_DATE_RE.search(name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def _display_date(iso):
    """'2026-06-19' -> '19/06/2026' (vacio si no hay)."""
    if not iso:
        return ""
    y, mo, d = iso.split("-")
    return f"{d}/{mo}/{y}"


def build_catalog(base_url="", only_lang=None):
    """Lista de dicts (una por conversacion publica), ordenada por fecha desc.
    Cada item: rel, lang, title, desc, section, date (display), iso, curated, url.
    `only_lang` limita a un idioma (la pagina /preguntas muestra el idioma activo)."""
    idx = i18n.GALLERY_SEO_INDEX
    items = []
    langs = (only_lang,) if only_lang in ("es", "en") else ("es", "en")
    for lang in langs:
        d = CONV_BASE / lang
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.html")):
            rel = f"{lang}/{p.name}"
            if is_nivel0(rel):
                continue
            meta = idx.get(rel)
            if meta:
                iso = _iso_date(meta.get("meta", "")) or _iso_from_name(p.name)
                item = {"rel": rel, "lang": lang, "title": meta["label"],
                        "desc": meta.get("desc", ""), "section": meta.get("section", ""),
                        "iso": iso, "curated": True}
            else:
                msgs = _messages(p)
                title = derive_title(msgs)
                if not title:
                    continue  # sin contenido real -> fuera del banco
                item = {"rel": rel, "lang": lang, "title": title, "desc": "",
                        "section": "", "iso": _iso_from_name(p.name), "curated": False}
            item["date"] = _display_date(item["iso"])
            item["url"] = (base_url + "/conversations/" + rel) if base_url else ("/conversations/" + rel)
            items.append(item)
    items.sort(key=lambda x: (x["iso"], x["title"]), reverse=True)
    return items


def _t(lang, key):
    return TRANSLATIONS.get(lang, TRANSLATIONS["es"]).get(key, key)


# Solo lo ESPECIFICO del banco. El nav/footer/variables vienen de chrome.CHROME_CSS.
_BANK_CSS = (
    "*{margin:0;padding:0;box-sizing:border-box}"
    "body{font-family:var(--sans);background:var(--bg);color:var(--text);padding-top:60px}"
    ".wrap{max-width:1000px;margin:0 auto;padding:24px 20px 40px}"
    "h1{font-size:26px;color:#E8186E;margin:8px 0 4px}"
    ".sub{color:#5A5855;font-size:14px;margin-bottom:18px}"
    "#q{width:100%;padding:12px 14px;border:1px solid rgba(0,0,0,.14);border-radius:10px;"
    "font-size:15px;margin-bottom:6px;background:#fff}"
    ".count{color:#9A9793;font-size:12px;margin-bottom:16px}"
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}"
    ".card{display:block;text-decoration:none;color:inherit;background:#fff;border:1px solid "
    "rgba(0,0,0,.08);border-radius:12px;padding:14px 16px;transition:box-shadow .15s,transform .15s}"
    ".card:hover{box-shadow:0 4px 16px rgba(0,0,0,.08);transform:translateY(-2px)}"
    ".card h3{font-size:15px;line-height:1.35;margin-bottom:6px;color:#1A1A1A}"
    ".card .d{font-size:12.5px;color:#5A5855;line-height:1.45;margin-bottom:8px}"
    ".meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center}"
    ".chip{font-size:10.5px;background:#FFF0F6;color:#C9145F;border-radius:5px;padding:2px 7px;font-weight:600}"
    ".date{font-size:11px;color:#9A9793;margin-left:auto}"
    ".none{color:#9A9793;font-size:14px;padding:20px 0;display:none}"
    ".filters{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 14px}"
    ".fchip{border:1px solid rgba(0,0,0,.14);background:#fff;color:#5A5855;border-radius:20px;"
    "padding:5px 12px;font-size:12px;cursor:pointer;font-family:inherit}"
    ".fchip.on{background:#E8186E;color:#fff;border-color:#E8186E}"
    ".frow{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px}"
)


def render_bank(lang, base_url=""):
    """FASE 36.2 (T3/T4) — pagina /preguntas server-side (SEO real) + buscador y filtros
    (tema/año) client-side. Muestra el idioma activo (como la galeria)."""
    lang = lang if lang in TRANSLATIONS else "es"
    items = build_catalog(base_url, only_lang=lang)
    e = lambda s: _html.escape(s or "", quote=True)
    sections, years = [], []
    cards = []
    for it in items:
        sec = it["section"] or ("Otras" if lang == "es" else "Others")
        year = (it["iso"][:4] if it["iso"] else "")
        if sec not in sections:
            sections.append(sec)
        if year and year not in years:
            years.append(year)
        blob = e((it["title"] + " " + it["desc"] + " " + sec).lower())
        chips = f'<span class="chip">{e(sec)}</span>'
        date = f'<span class="date">{e(it["date"])}</span>' if it["date"] else ""
        desc = f'<div class="d">{e(it["desc"])}</div>' if it["desc"] else ""
        cards.append(
            f'<a class="card" href="{e(it["url"])}" data-s="{blob}" '
            f'data-sec="{e(sec)}" data-year="{e(year)}">'
            f'<h3>{e(it["title"])}</h3>{desc}'
            f'<div class="meta">{chips}{date}</div></a>'
        )
    sections.sort()
    years.sort(reverse=True)
    all_lbl = _t(lang, "web.bank.all")

    def _chips(field, values):
        out = [f'<button class="fchip on" data-f="{field}" data-v="" onclick="h2aiPick(this)">{e(all_lbl)}</button>']
        for v in values:
            out.append(f'<button class="fchip" data-f="{field}" data-v="{e(v)}" onclick="h2aiPick(this)">{e(v)}</button>')
        return '<div class="frow">' + "".join(out) + "</div>"

    filters = '<div class="filters">' + _chips("sec", sections) + _chips("year", years) + "</div>"
    title = _t(lang, "web.bank.title")
    sub = _t(lang, "web.bank.sub")
    head = (
        f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">'
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css">'
        f"<title>{e(title)} · H2AI Chat</title>"
        f'<meta name="description" content="{e(sub)}">'
        f'<link rel="canonical" href="{e(base_url + "/preguntas")}">'
        f"<style>{chrome.CHROME_CSS}{_BANK_CSS}</style></head><body>"
    )
    # Header y footer = COMPONENTE compartido (chrome), el MISMO que la home.
    header = chrome.render_nav(lang, active="conversations", mode="static")
    footer = chrome.render_footer(lang, mode="static")
    body = (
        '<div class="wrap">'
        f"<h1>{e(title)}</h1><div class='sub'>{e(sub)}</div>"
        f'<input id="q" type="search" placeholder="{e(_t(lang, "web.bank.search_ph"))}" '
        'oninput="h2aiApply()" autocomplete="off">'
        f'{filters}'
        f'<div class="count"><span id="n">{len(items)}</span> {e(_t(lang, "web.bank.count"))}</div>'
        f'<div class="none" id="none">{e(_t(lang, "web.bank.none"))}</div>'
        f'<div class="grid" id="grid">{"".join(cards)}</div>'
        "</div>"
    )
    script = (
        "<script>var h2aiF={sec:'',year:''};"
        "function h2aiPick(b){var f=b.getAttribute('data-f');h2aiF[f]=b.getAttribute('data-v');"
        "document.querySelectorAll('.fchip[data-f=\"'+f+'\"]').forEach(function(x){x.classList.remove('on');});"
        "b.classList.add('on');h2aiApply();}"
        "function h2aiApply(){var q=(document.getElementById('q').value||'').toLowerCase().trim();"
        "var cards=document.querySelectorAll('#grid .card'),n=0;"
        "cards.forEach(function(c){"
        "var ok=(!q||c.getAttribute('data-s').indexOf(q)>=0)"
        "&&(!h2aiF.sec||c.getAttribute('data-sec')===h2aiF.sec)"
        "&&(!h2aiF.year||c.getAttribute('data-year')===h2aiF.year);"
        "c.style.display=ok?'':'none';if(ok)n++;});"
        "document.getElementById('n').textContent=n;"
        "document.getElementById('none').style.display=n?'none':'block';}</script>"
    )
    return (head + header + body + footer + script
            + chrome.auth_js(lang) + chrome.STAGING_JS + "</body></html>")

