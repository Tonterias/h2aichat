#!/usr/bin/env python3
"""FASE 36 — SEO server-side de las conversaciones publicadas.

The /conversations/... pages are served from exported files whose <title> and <h1> are
generic branding, with no <meta description>: invisible to search engines. Here the
<head> and the <h1> are rewritten so crawlers and social cards see the real TOPIC. The
texts come from the gallery (i18n.GALLERY_SEO_INDEX): one place, the same promise the
visitor sees. A single injection point, like the navigation bar. Idempotent: everything
derives from the raw gallery data, so fixing one entry also fixes the pages already
published, without regenerating them.

Tres niveles (decision del PO, Fase 36):
  - Curated (it is in the gallery) -> full SEO, indexable  ..... inject_seo()
  - No curada (pruebas/duplicados/debug)                    ..... inject_noindex()
"""
import html as _html
import json
import re

BRAND = "H2AI Chat"

# Per-language <title> suffix.
_SUFFIX = {
    "es": "Diálogo entre Humanos e IAs · H2AI Chat",
    "en": "Dialogue between humans and AIs · H2AI Chat",
}

# A fragment that tolerates '>' inside quoted values: messages can contain '>' in an
# og:description from the export. Either a normal character, or a whole "..." string.
_ATTR = r'(?:[^>"]|"[^"]*")*'
_META_TAG_RE = re.compile(r"<meta" + _ATTR + r">", re.I)
_LINK_TAG_RE = re.compile(r"<link" + _ATTR + r">", re.I)
_SOCIAL_RE = re.compile(r'property="og:|name="twitter:|name="description"', re.I)
_TITLE_RE = re.compile(r"<title>.*?</title>", re.I | re.S)
_H1_RE = re.compile(r"<h1[^>]*>.*?</h1>", re.I | re.S)
_DATE_RE = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})\s*$")


def seo_title(label, lang):
    return f"{label} — {_SUFFIX.get(lang, _SUFFIX['es'])}"


def _iso_date(meta):
    """'19/06/2026' -> '2026-06-19' (datePublished). '' si no encaja el formato."""
    m = _DATE_RE.match(meta or "")
    if not m:
        return ""
    d, mo, y = m.groups()
    return f"{y}-{mo}-{d}"


def _strip_old_social(html):
    """Strips any og:*, twitter:* and description the export carried, avoiding duplicates and
    making injection idempotent when the page is served again."""
    html = _META_TAG_RE.sub(lambda m: "" if _SOCIAL_RE.search(m.group(0)) else m.group(0), html)
    html = _LINK_TAG_RE.sub(
        lambda m: "" if 'rel="canonical"' in m.group(0).lower() else m.group(0), html)
    return html


def build_head_tags(*, title, desc, canonical, lang, image_url, jsonld):
    e = lambda s: _html.escape(s or "", quote=True)
    parts = [
        f'<meta name="description" content="{e(desc)}">',
        f'<link rel="canonical" href="{e(canonical)}">',
        '<meta property="og:type" content="article">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:url" content="{e(canonical)}">',
        f'<meta property="og:image" content="{e(image_url)}">',
        f'<meta property="og:locale" content="{e("es_ES" if lang == "es" else "en_US")}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{e(title)}">',
        f'<meta name="twitter:description" content="{e(desc)}">',
        f'<meta name="twitter:image" content="{e(image_url)}">',
        '<script type="application/ld+json">'
        + json.dumps(jsonld, ensure_ascii=False, separators=(",", ":"))
        + "</script>",
    ]
    return "".join(parts)


def inject_seo(html, meta, canonical, image_url, alternates=None):
    """Rewrites the head and H1 of a CURATED conversation. `meta` is its gallery entry
    ({label, desc, lang, section, meta}). `alternates` = [(lang, url), ...] para hreflang."""
    lang = meta.get("lang", "es")
    label = meta.get("label", "")
    desc = meta.get("desc", "")
    title = seo_title(label, lang)

    html = _TITLE_RE.sub("<title>" + _html.escape(title, quote=False) + "</title>", html, count=1)
    html = _strip_old_social(html)

    jsonld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": desc,
        "inLanguage": lang,
        "url": canonical,
        "isAccessibleForFree": True,
        "author": {"@type": "Organization", "name": BRAND},
        "publisher": {"@type": "Organization", "name": BRAND},
    }
    iso = _iso_date(meta.get("meta", ""))
    if iso:
        jsonld["datePublished"] = iso

    tags = build_head_tags(title=title, desc=desc, canonical=canonical, lang=lang,
                           image_url=image_url, jsonld=jsonld)
    # hreflang between Spanish and English: only when there is a real pair.
    if alternates:
        e = lambda s: _html.escape(s or "", quote=True)
        for alt_lang, alt_url in alternates:
            tags += f'<link rel="alternate" hreflang="{e(alt_lang)}" href="{e(alt_url)}">'

    if "</head>" in html:
        html = html.replace("</head>", tags + "</head>", 1)
    html = _H1_RE.sub("<h1>" + _html.escape(label, quote=False) + "</h1>", html, count=1)
    return html


def inject_home_seo(html, *, lang, title, desc, canonical, image_url, alternates=None):
    """SEO for the HOME page. Like inject_seo but for a site page rather than a
    conversation: og:type=website, robots index,follow, JSON-LD WebSite, and it does NOT touch
    the hero's <h1>. Rewrites the <title> per language. Idempotent: it strips previous social tags."""
    e = lambda s: _html.escape(s or "", quote=True)
    html = _TITLE_RE.sub("<title>" + _html.escape(title, quote=False) + "</title>", html, count=1)
    html = _strip_old_social(html)
    jsonld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": BRAND,
        "url": canonical,
        "inLanguage": lang,
        "description": desc,
    }
    parts = [
        '<meta name="robots" content="index,follow">',
        f'<meta name="description" content="{e(desc)}">',
        f'<link rel="canonical" href="{e(canonical)}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:url" content="{e(canonical)}">',
        f'<meta property="og:image" content="{e(image_url)}">',
        f'<meta property="og:locale" content="{"es_ES" if lang == "es" else "en_US"}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{e(title)}">',
        f'<meta name="twitter:description" content="{e(desc)}">',
        f'<meta name="twitter:image" content="{e(image_url)}">',
        '<script type="application/ld+json">'
        + json.dumps(jsonld, ensure_ascii=False, separators=(",", ":")) + "</script>",
    ]
    for alt_lang, alt_url in (alternates or []):
        parts.append(f'<link rel="alternate" hreflang="{e(alt_lang)}" href="{e(alt_url)}">')
    tags = "".join(parts)
    if "</head>" in html:
        html = html.replace("</head>", tags + "</head>", 1)
    return html


def inject_noindex(html):
    """NON-curated conversations: kept out of search indexes, but their links are still followed."""
    tag = '<meta name="robots" content="noindex,follow">'
    if tag in html:
        return html
    if "</head>" in html:
        return html.replace("</head>", tag + "</head>", 1)
    return html
