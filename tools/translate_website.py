"""Build the localised Cubeon website (Arabic, Ukrainian, Russian) from the
English pages and the translation catalogues in ``web/i18n``.

The English HTML stays the single source of truth. Every translatable block
(text between inline markup) becomes one catalogue entry with a stable key:
the block's text, with inline elements replaced by ``{0}``, ``{1}`` ... so a
translator may reorder them. Inline elements are catalogued separately, which
keeps sentences whole instead of translating fragments around a link.

Commands
--------
    python tools/translate_website.py extract
    python tools/translate_website.py build [--lang ar uk ru]
    python tools/translate_website.py check
    python tools/translate_website.py stats

``build`` also patches the English pages with the language menu, hreflang
links, canonical URLs and the early-detection script. It is idempotent.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
I18N = WEB / "i18n"
ORIGIN = "https://www.ylet.online"
LAUNCHER_IMAGE_ALT = "Cubeon Launcher: free, open-source Minecraft Java launcher for Windows and Linux, with the launcher window, mods, modpacks and skins."

LANGUAGES = {
    "en": {"native": "English", "dir": "ltr", "label": "Language"},
    "ar": {"native": "العربية", "dir": "rtl", "label": "اللغة"},
    "uk": {"native": "Українська", "dir": "ltr", "label": "Мова"},
    "ru": {"native": "Русский", "dir": "ltr", "label": "Язык"},
}
TRANSLATED = ("ar", "uk", "ru")

PAGES = [
    "index", "about", "benchmarks", "cookies", "cosmetics", "docs", "doctor",
    "download", "files", "getting-started", "help", "licenses", "minecraft-launcher", "modpacks",
    "mods", "multiplayer", "privacy", "refunds", "terms", "troubleshooting",
    "403", "404", "429", "500", "502", "503",
]
ROOT_PAGES = {"index"}

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
# Elements whose whole subtree is copied verbatim (code stays code).
OPAQUE = {"code", "kbd", "samp", "var", "pre", "script", "style", "svg", "math"}
BLOCK_TAGS = {
    "title", "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd",
    "th", "td", "summary", "figcaption", "caption", "button", "a", "span",
    "b", "strong", "em", "small", "label", "option", "blockquote",
}
ATTR_NAMES = {"title", "alt", "aria-label", "placeholder"}
META_NAMES = {
    "description", "og:title", "og:description", "og:image:alt",
    "twitter:title", "twitter:description", "twitter:image:alt",
}
JSONLD_TEXT_KEYS = {"name", "headline", "description", "text", "alternateName", "caption"}

PLACEHOLDER = re.compile(r"\{(\d+)\}")
TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w:-]*)([^>]*?)(/?)>", re.S)
SKIP_KEY = re.compile(r"^(?:https?://|mailto:|/|#|[0-9\s.,:;+\-–—·/|×→←]+)$")

LANG_BLOCK = "<!-- cubeon:language -->"
LANG_END = "<!-- /cubeon:language -->"
SEO_BLOCK = "<!-- cubeon:seo -->"
SEO_END = "<!-- /cubeon:seo -->"
EARLY_BLOCK = "<!-- cubeon:auto-language -->"
EARLY_END = "<!-- /cubeon:auto-language -->"


def unescape(text: str) -> str:
    return html.unescape(text)


def escape(text: str) -> str:
    return html.escape(text, quote=False)


def escape_attr(text: str) -> str:
    return html.escape(text, quote=True)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def has_letters(text: str) -> bool:
    return bool(re.search(r"[^\W\d_]", text, re.UNICODE))


@dataclass
class Part:
    tag: str
    open_raw: str
    inner_raw: str
    close_raw: str


@dataclass
class Unit:
    tag: str
    start: int
    end: int
    template: str
    raw: str
    parts: list[Part] = field(default_factory=list)


@dataclass
class Attr:
    start: int
    end: int
    name: str
    value: str
    context: str


def opening_tag(source: str, start: int) -> str:
    match = TAG_RE.match(source, start)
    return match.group(0) if match else ""


class Scanner(HTMLParser):
    """Locate tags and attribute values while preserving exact offsets."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_starts = [0]
        for line in source.splitlines(True):
            self.line_starts.append(self.line_starts[-1] + len(line))
        self.stack: list[list] = []
        self.candidates: list[tuple[int, int, str]] = []
        self.opaque: list[tuple[int, int]] = []
        self.attrs: list[Attr] = []
        self.feed(source)
        self.close()

    def pos(self) -> int:
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def _attr_spans(self, tag: str, attrs, start: int, tag_text: str):
        cursor = 0
        for name, value in attrs:
            if not value:
                continue
            label = name.lower()
            wanted = label in ATTR_NAMES
            if tag == "meta" and label == "content":
                meta_name = dict(attrs).get("name") or dict(attrs).get("property") or ""
                wanted = meta_name in META_NAMES
            if not wanted:
                continue
            pattern = re.compile(r"\b" + re.escape(name) + r"\s*=\s*([\"'])(.*?)\1", re.S)
            match = pattern.search(tag_text, cursor)
            if not match:
                continue
            cursor = match.end()
            vstart = start + match.start(2)
            self.attrs.append(Attr(vstart, vstart + len(match.group(2)), label, value, tag))

    def handle_starttag(self, tag, attrs):
        start = self.pos()
        tag_text = self.get_starttag_text() or ""
        tag = tag.lower()
        self._attr_spans(tag, attrs, start, tag_text)
        if tag in VOID:
            return
        self.stack.append([tag, start])
        if tag in OPAQUE:
            self.opaque.append((start, -1))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in VOID:
            return
        pos = self.pos()
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                break
        else:
            return
        while len(self.stack) - 1 >= i:
            t, start = self.stack.pop()
            if t in OPAQUE:
                for j in range(len(self.opaque) - 1, -1, -1):
                    if self.opaque[j][0] == start and self.opaque[j][1] < 0:
                        self.opaque[j] = (start, pos + len(tag) + 3)
                        break
            elif t in BLOCK_TAGS:
                self.candidates.append((start + len(opening_tag(self.source, start)),
                                        pos, t))


TRANSLATABLE_ATTRS = {"title", "alt", "aria-label", "placeholder"}


def attr_pairs(raw_attrs: str):
    pairs = []
    for match in re.finditer(
        r"([^\s=/>]+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+)))?", raw_attrs
    ):
        name = match.group(1)
        value = match.group(2) if match.group(2) is not None else (
            match.group(3) if match.group(3) is not None else (match.group(4) or ""))
        pairs.append((name.lower(), value))
    return pairs


def tag_signature(fragment: str):
    sig = []
    for match in TAG_RE.finditer(fragment):
        closing, tag, raw_attrs, _ = match.groups()
        if closing:
            continue
        attrs = tuple(sorted(
            (name, value) for name, value in attr_pairs(raw_attrs)
            if name not in TRANSLATABLE_ATTRS
        ))
        sig.append((tag.lower(), attrs))
    return sig


def normalize_fragment(raw: str) -> str:
    out = []
    pos = 0
    for match in TAG_RE.finditer(raw):
        out.append(re.sub(r"\s+", " ", raw[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(re.sub(r"\s+", " ", raw[pos:]))
    return "".join(out).strip()


def visible_text(fragment: str) -> str:
    text = re.sub(r"\{[0-9]+\}", " ", fragment)
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(clean_text(text))


def split_top(raw: str) -> tuple[str, list[Part]]:
    """Keep inline markup in the unit; lift opaque/decorative pieces out."""
    template: list[str] = []
    parts: list[Part] = []
    i, n = 0, len(raw)
    while i < n:
        if raw.startswith("<!--", i):
            j = raw.find("-->", i)
            i = n if j < 0 else j + 3
            continue
        match = TAG_RE.match(raw, i)
        if not match:
            template.append(raw[i])
            i += 1
            continue
        closing, tag, raw_attrs, selfclose = match.groups()
        tag = tag.lower()
        if closing:
            template.append(match.group(0))
            i = match.end()
            continue
        attrs = dict(attr_pairs(raw_attrs))
        decorative = attrs.get("aria-hidden", "").lower() == "true" or attrs.get("translate") == "no"
        if tag in VOID or selfclose:
            template.append("{%d}" % len(parts))
            parts.append(Part(tag, match.group(0), "", ""))
            i = match.end()
            continue
        if decorative or tag in OPAQUE:
            depth = 1
            j = match.end()
            close_start = close_end = None
            while j < n:
                m = TAG_RE.match(raw, j)
                if not m:
                    j += 1
                    continue
                c, t, _, sc = m.groups()
                t = t.lower()
                if not c and t == tag and not sc and t not in VOID:
                    depth += 1
                elif c and t == tag:
                    depth -= 1
                    if depth == 0:
                        close_start, close_end = j, m.end()
                        break
                j = m.end()
            if close_start is None:
                template.append("{%d}" % len(parts))
                parts.append(Part(tag, match.group(0), raw[match.end():n], ""))
                break
            template.append("{%d}" % len(parts))
            parts.append(Part(tag, raw[i:match.end()],
                              raw[match.end():close_start], raw[close_start:close_end]))
            i = close_end
            continue
        # Ordinary inline markup stays in the sentence so translators see it.
        template.append(match.group(0))
        i = match.end()
    return "".join(template), parts


def build_unit(source: str, start: int, end: int, tag: str) -> Unit:
    raw = source[start:end]
    template, parts = split_top(raw)
    return Unit(tag, start, end, normalize_fragment(template), raw, parts)


def outermost(source: str, candidates: list[tuple[int, int, str]]):
    kept = []
    seen = set()
    for start, end, tag in candidates:
        if (start, end, tag) in seen:
            continue
        seen.add((start, end, tag))
        if any(s < start and end <= e for s, e, _ in candidates if (s, e) != (start, end)):
            continue
        if not re.sub(r"<[^>]+>", "", source[start:end]).strip():
            continue
        kept.append((start, end, tag))
    return kept


def collect_units(source: str) -> list[Unit]:
    scanner = Scanner(source)
    units = []
    for start, end, tag in outermost(source, scanner.candidates):
        if any(s <= start and end <= e for s, e in scanner.opaque):
            continue
        unit = build_unit(source, start, end, tag)
        if unit.template.strip():
            units.append(unit)
    return units


def all_attrs(source: str) -> list[Attr]:
    return Scanner(source).attrs


def collect_attrs(source: str) -> list[Attr]:
    """Attributes outside the translated blocks; the rest move with the unit."""
    scanner = Scanner(source)
    spans = [(u.start, u.end) for u in collect_units(source)]
    return [a for a in scanner.attrs
            if not any(start < a.start and a.end <= end for start, end in spans)]


# --------------------------------------------------------------------------
# Catalogues
# --------------------------------------------------------------------------

def jsonld_pairs(obj, parent=None):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from jsonld_pairs(value, key)
    elif isinstance(obj, list):
        for value in obj:
            yield from jsonld_pairs(value, parent)
    elif isinstance(obj, str) and parent in JSONLD_TEXT_KEYS:
        yield obj


def read_jsonld(source: str):
    for match in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        source, re.S,
    ):
        try:
            yield json.loads(match.group(1))
        except ValueError:
            continue


def extract():
    I18N.mkdir(parents=True, exist_ok=True)
    strings: dict[str, dict] = {}

    def add(key: str, kind: str, page: str, parts=None):
        entry = strings.setdefault(
            key, {"key": key, "kind": kind, "pages": [], "parts": []}
        )
        if page not in entry["pages"]:
            entry["pages"].append(page)
        if parts and not entry["parts"]:
            entry["parts"] = parts[:8]

    for page in PAGES:
        source = strip_generated(read_page(page))
        for unit in collect_units(source):
            key = unit.template
            if not key or SKIP_KEY.match(key) or not has_letters(visible_text(key)):
                continue
            hints = [visible_text(p.open_raw) for p in unit.parts]
            add(key, "text", page, [h for h in hints if h])
        for attr in all_attrs(source):
            key = clean_text(unescape(attr.value))
            if not key or len(key) < 2 or not has_letters(key) or SKIP_KEY.match(key):
                continue
            add(key, "attr", page)
        for obj in read_jsonld(source):
            for value in jsonld_pairs(obj):
                key = clean_text(value)
                if not key or len(key) < 3 or not has_letters(key) or SKIP_KEY.match(key):
                    continue
                add(key, "jsonld", page)

    data = {
        "version": 1,
        "note": "Generated by tools/translate_website.py extract. Only edit "
                "web/i18n/<lang>.json; rebuild with build.",
        "strings": list(strings.values()),
    }
    (I18N / "source.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for lang in TRANSLATED:
        path = I18N / f"{lang}.json"
        existing = load_catalog(lang)
        merged = {entry["key"]: existing.get(entry["key"], "") for entry in data["strings"]}
        path.write_text(
            json.dumps({"version": 1, "language": lang, "strings": merged},
                       ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    print(f"{len(data['strings'])} strings -> web/i18n/source.json")
    for lang in TRANSLATED:
        filled = sum(1 for v in load_catalog(lang).values() if v)
        print(f"  {lang}: {filled}/{len(data['strings'])} translated")


def load_catalog(lang: str) -> dict[str, str]:
    path = I18N / f"{lang}.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    strings = raw.get("strings", raw)
    return {k: v for k, v in strings.items() if isinstance(v, str) and v}


def read_page(page: str) -> str:
    return (WEB / f"{page}.html").read_text(encoding="utf-8")


def translated_languages():
    """Advertise real translations; empty catalogues retain fallback routes."""
    return ["en"] + [lang for lang in TRANSLATED if load_catalog(lang)]


def strip_generated(source: str) -> str:
    # Remove the generated block's own trailing newline as well, so each
    # rebuild does not add another blank line at all three insertion points.
    for start, end in ((LANG_BLOCK, LANG_END), (SEO_BLOCK, SEO_END), (EARLY_BLOCK, EARLY_END)):
        source = re.sub(r'\n(?:[ \t]*\n)*[ \t]*' + re.escape(start) + r".*?" + re.escape(end) + r"\n?", "\n", source, flags=re.S)
    source = source.replace('<link rel="stylesheet" href="/assets/rtl.css" />\n', "")
    source = source.replace('<link rel="stylesheet" href="/assets/rtl.css" />', "")
    return source


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------

class Renderer:
    def __init__(self, catalog: dict[str, str]):
        self.catalog = catalog
        self.missing: set[str] = set()
        self.used: set[str] = set()

    def t(self, key: str) -> str:
        key = clean_text(key)
        value = self.catalog.get(key)
        if value:
            self.used.add(key)
            return value
        self.missing.add(key)
        return key

    def render_unit(self, unit: Unit) -> str:
        translated = self.catalog.get(unit.template)
        if not translated or not valid_translation(unit, translated):
            if unit.template not in self.missing:
                self.missing.add(unit.template)
            return unit.raw
        self.used.add(unit.template)
        translated = translate_tag_values(translated, self.t)
        out = []
        cursor = 0
        for match in PLACEHOLDER.finditer(translated):
            out.append(translated[cursor:match.start()])
            index = int(match.group(1))
            if index < len(unit.parts):
                out.append(self.render_part(unit.parts[index]))
            cursor = match.end()
        out.append(translated[cursor:])
        return "".join(out)

    def render_part(self, part: Part) -> str:
        return (translate_tag_values(part.open_raw, self.t)
                + part.inner_raw + part.close_raw)


def valid_translation(unit: Unit, translated: str) -> bool:
    expected = {int(n) for n in PLACEHOLDER.findall(unit.template)}
    actual = {int(n) for n in PLACEHOLDER.findall(translated)}
    if expected != actual or actual != set(range(len(unit.parts))):
        return False
    if not has_letters(visible_text(translated)):
        return False
    return tag_signature(unit.template) == tag_signature(translated)


def translate_tag_values(fragment: str, translator) -> str:
    def repl(match):
        before, quote, value = match.group(1), match.group(2), match.group(3)
        key = clean_text(unescape(value))
        if not key or SKIP_KEY.match(key):
            return match.group(0)
        return before + quote + escape_attr(translator(key)) + quote

    return re.sub(
        r"(\s(?:title|alt|aria-label|placeholder)\s*=\s*)([\"'])(.*?)\2",
        repl, fragment, flags=re.S,
    )


def url_path(page: str, lang: str) -> str:
    stem = "" if page in ROOT_PAGES else f"/{page}"
    prefix = "" if lang == "en" else f"/{lang}"
    return prefix + stem or "/"


def page_url(page: str, lang: str) -> str:
    return ORIGIN + url_path(page, lang)


def language_menu(page: str, lang: str) -> str:
    available = translated_languages()
    if lang not in available:
        lang = "en"
    current = LANGUAGES[lang]
    options = []
    for code in available:
        meta = LANGUAGES[code]
        attrs = f' hreflang="{code}" lang="{code}"'
        if code == lang:
            attrs += ' aria-current="true"'
        options.append(f'<a href="{url_path(page, code)}"{attrs}>{meta["native"]}</a>')
    items = "\n          ".join(options)
    return (
        f'{LANG_BLOCK}\n'
        f'<div class="lang-menu">\n'
        f'  <details>\n'
        f'    <summary aria-label="{escape_attr(current["label"])}: {current["native"]}">'
        f'<span aria-hidden="true">🌐</span> {lang.upper()}</summary>\n'
        f'    <nav class="lang-list" aria-label="{escape_attr(current["label"])}">\n'
        f'          {items}\n'
        f'    </nav>\n'
        f'  </details>\n'
        f'</div>\n'
        f'{LANG_END}'
    )


def head_block(page: str, lang: str) -> str:
    available = translated_languages()
    alternates = "\n".join(
        f'<link rel="alternate" hreflang="{code}" href="{page_url(page, code)}" />'
        for code in available
    )
    alternates += f'\n<link rel="alternate" hreflang="x-default" href="{page_url(page, "en")}" />'
    canonical = page_url(page, lang if lang in available else "en")
    return (
        f"{SEO_BLOCK}\n{alternates}\n"
        f'<link rel="canonical" href="{canonical}" />\n'
        f'<meta property="og:url" content="{canonical}" />\n'
        f"{SEO_END}"
    )


EARLY_SCRIPT = r"""<!-- cubeon:auto-language -->
<script>
(function () {
  var names = { en: 1, ar: 1, uk: 1, ru: 1 }, cur = document.documentElement.lang || 'en';
  if (location.protocol === 'file:') return;
  if (/bot|crawl|spider|googlebot|bingbot|yandex|baidu/i.test(navigator.userAgent)) return;
  var path = location.pathname, m = path.match(/^\/(ar|uk|ru)(?=\/|$)/), pref = null;
  if (m) cur = m[1];
  function search() {
    var out = '', q;
    try { q = new URLSearchParams(location.search); q.delete('lang'); out = q.toString(); } catch (e) {}
    return (out ? '?' + out : '') + location.hash;
  }
  function urlFor(code) {
    var rest = path.replace(/^\/(ar|uk|ru)(?=\/|$)/, '') || '/';
    if (rest === '/index.html') rest = '/';
    else if (rest.slice(-5) === '.html') rest = rest.slice(0, -5);
    return (code === 'en' ? '' : '/' + code) + rest + search();
  }
  try { pref = localStorage.getItem('cubeon-lang'); } catch (e) {}
  var q = null;
  try { q = new URLSearchParams(location.search); } catch (e) {}
  if (q && q.get('lang') && names[q.get('lang')]) {
    pref = q.get('lang');
    try { localStorage.setItem('cubeon-lang', pref); } catch (e) {}
    location.replace(urlFor(pref));
    return;
  }
  if (!pref) {
    var list = navigator.languages || [navigator.language || ''];
    for (var i = 0; i < list.length; i++) {
      var code = String(list[i]).toLowerCase().split('-')[0];
      if (names[code]) { pref = code; break; }
    }
  }
  if (pref && names[pref] && pref !== cur) location.replace(urlFor(pref));
})();
</script>
<!-- /cubeon:auto-language -->"""


def patch_social_metadata(source: str, lang: str) -> str:
    metadata = {name: unescape(value) for name, value in re.findall(
        r'<meta\s+(?:property|name)="([^"]+)"\s+content="([^"]*)"[^>]*>', source
    )}
    if metadata.get("og:image") != ORIGIN + "/assets/og.png":
        return source
    available = translated_languages()
    content_lang = lang if lang in available else "en"
    alt = LAUNCHER_IMAGE_ALT if content_lang == "en" else load_catalog(content_lang).get(
        LAUNCHER_IMAGE_ALT, LAUNCHER_IMAGE_ALT
    )
    locales = {"en": "en_US", "ar": "ar_AR", "uk": "uk_UA", "ru": "ru_RU"}
    properties = [
        ("og:image:width", "1200"),
        ("og:image:height", "630"),
        ("og:image:alt", alt),
        ("og:image:secure_url", metadata["og:image"]),
        ("og:image:type", "image/png"),
        ("og:locale", locales[content_lang]),
    ]
    properties.extend(("og:locale:alternate", locales[code])
                      for code in available if code != content_lang)
    names = [
        ("twitter:card", "summary_large_image"),
        ("twitter:title", metadata["og:title"]),
        ("twitter:description", metadata["og:description"]),
        ("twitter:image", metadata["og:image"]),
        ("twitter:image:alt", alt),
    ]
    replaced = {name for name, value in properties + names} | {"og:locale:alternate"}
    pattern = "|".join(re.escape(name) for name in replaced)
    source = re.sub(r'[ \t]*<meta\s+(?:property|name)="(?:' + pattern + r')"[^>]*>\n?', "", source)
    block = "\n".join(f'<meta {attribute}="{name}" content="{escape_attr(value)}" />'
                      for attribute, entries in (("property", properties), ("name", names))
                      for name, value in entries)
    return source.replace("</head>", block + "\n</head>", 1)


def patch_common(source: str, page: str, lang: str) -> str:
    source = patch_social_metadata(source, lang)
    available = translated_languages()
    content_lang = lang if lang in available else "en"
    source = re.sub(
        r"<html\b[^>]*>",
        f'<html lang="{content_lang}"' + (' dir="rtl"' if LANGUAGES[content_lang]["dir"] == "rtl" else "") + ">",
        source, count=1,
    )
    if lang not in available and not page.isdigit():
        source = re.sub(r'(<meta name="robots" content=")[^"]*(")',
                        r'\1noindex, follow\2', source, count=1)
    source = re.sub(r"[ \t]*<link rel=\"canonical\"[^>]*>\n?", "", source)
    source = re.sub(r"[ \t]*<meta property=\"og:url\"[^>]*>\n?", "", source)
    block = head_block(page, lang)
    if SEO_BLOCK in source:
        source = re.sub(re.escape(SEO_BLOCK) + r".*?" + re.escape(SEO_END), block, source, flags=re.S)
    else:
        source = source.replace("</head>", block + "\n</head>", 1)
    names = ", ".join(code + ": 1" for code in available)
    early = re.sub(r"var names = \{[^}]+\}", "var names = { " + names + " }", EARLY_SCRIPT)
    if EARLY_BLOCK in source:
        source = re.sub(re.escape(EARLY_BLOCK) + r".*?" + re.escape(EARLY_END), early, source, flags=re.S)
    elif '<link rel="stylesheet"' in source:
        source = source.replace('<link rel="stylesheet"', early + '\n<link rel="stylesheet"', 1)
    else:
        source = source.replace("</head>", early + "\n</head>", 1)
    if LANGUAGES[lang]["dir"] == "rtl" and '/assets/rtl.css' not in source:
        source = source.replace("</head>", '<link rel="stylesheet" href="/assets/rtl.css" />\n</head>', 1)
    menu = language_menu(page, lang)
    if LANG_BLOCK in source:
        source = re.sub(re.escape(LANG_BLOCK) + r".*?" + re.escape(LANG_END), menu, source, flags=re.S)
    else:
        match = re.search(r'(<nav class="nav-links"[^>]*>)', source)
        if match:
            source = source[:match.end()] + "\n      " + menu + source[match.end():]
    return source


def rewrite_links(source: str, lang: str) -> str:
    if lang == "en":
        return source

    def repl(match):
        prefix, quote, value = match.group(1), match.group(2), match.group(3)
        if not value or value.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            return match.group(0)
        if re.match(r"^[a-zA-Z][\w+.-]*:", value) or value.startswith("//"):
            return match.group(0)
        path, hash_sep, fragment = value.partition("#")
        path, query_sep, query = path.partition("?")
        candidate = path[1:] if path.startswith("/") else path
        stem = re.sub(r"\.html$", "", candidate)
        if stem in PAGES or stem in ("", "index"):
            new = url_path(stem or "index", lang)
        elif path.startswith("/") or not path:
            return match.group(0)
        else:
            new = "/" + path
        if query_sep:
            new += "?" + query
        if hash_sep:
            new += "#" + fragment
        return f"{prefix}{quote}{new}{quote}"

    source = re.sub(r'((?:href|src)=)(["\'])(.*?)\2', repl, source, flags=re.S)

    def srcset(match):
        quote, value = match.group(1), match.group(2)
        if value.startswith('data:'):
            return match.group(0)
        candidates = []
        for candidate in value.split(','):
            parts = candidate.strip().split()
            if parts and not parts[0].startswith(('/', 'https:', 'http:', 'data:')):
                parts[0] = '/' + parts[0]
            candidates.append(' '.join(parts))
        return 'srcset=' + quote + ', '.join(candidates) + quote

    return re.sub(r'srcset=(["\'])(.*?)\1', srcset, source, flags=re.S)


def translate_jsonld(source: str, translator, page=None, lang="en") -> str:
    def repl(match):
        opening, body, closing = match.group(1), match.group(2), match.group(3)
        try:
            data = json.loads(body)
        except ValueError:
            return match.group(0)

        def visit(value, parent=None, local_page=False):
            if isinstance(value, str):
                if local_page and page and page not in ROOT_PAGES and lang != "en":
                    canonical = page_url(page, "en")
                    if value == canonical or value.startswith(canonical + "#"):
                        return page_url(page, lang) + value[len(canonical):]
                    if parent == "item":
                        for target in PAGES:
                            if value == page_url(target, "en"):
                                return page_url(target, lang)
                if parent in JSONLD_TEXT_KEYS:
                    key = clean_text(value)
                    if key and len(key) >= 3 and not SKIP_KEY.match(key):
                        return translator(key)
                return value
            if isinstance(value, dict):
                # Product/site IDs stay shared; each translated article and
                # breadcrumb belongs to its own canonical page.
                local_page = local_page or value.get("@type") in {
                    "WebPage", "AboutPage", "Article", "BreadcrumbList"
                }
                return {k: visit(v, k, local_page) for k, v in value.items()}
            if isinstance(value, list):
                return [visit(v, parent, local_page) for v in value]
            return value

        data = visit(data)
        return opening + "\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n" + closing

    return re.sub(
        r'(<script[^>]*type=["\']application/ld\+json["\'][^>]*>)(.*?)(</script>)',
        repl, source, flags=re.S,
    )


def apply_attrs(source: str, renderer: Renderer, attrs: list[Attr]) -> str:
    for attr in sorted(attrs, key=lambda a: a.start, reverse=True):
        key = clean_text(unescape(attr.value))
        if not key or SKIP_KEY.match(key):
            continue
        value = renderer.t(key)
        if value != key:
            source = source[:attr.start] + escape_attr(value) + source[attr.end:]
    return source


def translate_page(page: str, lang: str) -> tuple[str, set[str]]:
    source = strip_generated(read_page(page))
    attrs = collect_attrs(source)
    units = collect_units(source)
    renderer = Renderer(load_catalog(lang))
    # Both sets of offsets refer to the original HTML. Applying all body/title
    # units first shifts later attributes and can delete closing quotes/tags.
    replacements = [(unit.start, unit.end, renderer.render_unit(unit)) for unit in units]
    for attr in attrs:
        key = clean_text(unescape(attr.value))
        if key and not SKIP_KEY.match(key):
            value = renderer.t(key)
            if value != key:
                replacements.append((attr.start, attr.end, escape_attr(value)))
    for start, end, rendered in sorted(replacements, reverse=True):
        source = source[:start] + rendered + source[end:]
    source = translate_jsonld(source, renderer.t, page, lang if lang in translated_languages() else "en")
    source = rewrite_links(source, lang)
    source = patch_common(source, page, lang)
    return source, renderer.missing


def write_sitemap():
    import xml.etree.ElementTree as ET

    path = WEB / "sitemap.xml"
    if not path.exists():
        return
    ET.register_namespace("", "http://www.sitemaps.org/schemas/sitemap/0.9")
    ET.register_namespace("image", "http://www.google.com/schemas/sitemap-image/1.1")
    ET.register_namespace("xhtml", "http://www.w3.org/1999/xhtml")
    tree = ET.parse(path)
    root = tree.getroot()
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    xhtml = "{http://www.w3.org/1999/xhtml}"
    original = list(root)
    languages = translated_languages()
    # New public source pages must enter the sitemap without a manual XML edit.
    known = {url.findtext(ns + "loc") for url in original}
    for page in PAGES:
        if page.isdigit() or page_url(page, "en") in known:
            continue
        entry = ET.Element(ns + "url")
        ET.SubElement(entry, ns + "loc").text = page_url(page, "en")
        original.append(entry)
    root.clear()
    seen = set()
    for url in original:
        loc = url.find(ns + "loc")
        if loc is None or not loc.text:
            continue
        loc_text = loc.text.rstrip("/")
        # Regenerate alternates from English entries only; otherwise every
        # build multiplies already generated language URLs and image records.
        relative = loc_text.removeprefix(ORIGIN).strip('/')
        if relative.split('/', 1)[0] in TRANSLATED or loc_text in seen:
            continue
        seen.add(loc_text)
        page = "index" if loc_text == ORIGIN else loc_text.rsplit("/", 1)[-1]
        if page not in PAGES:
            root.append(url)
            continue
        for lang in languages:
            entry = ET.SubElement(root, ns + "url")
            ET.SubElement(entry, ns + "loc").text = page_url(page, lang)
            for code in languages + ["x-default"]:
                ET.SubElement(entry, xhtml + "link", {
                    "rel": "alternate",
                    "hreflang": code,
                    "href": page_url(page, "en" if code == "x-default" else code),
                })
            if lang != "en":
                continue
            for child in url:
                if child.tag not in (ns + "loc", xhtml + "link"):
                    entry.append(child)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    print("updated web/sitemap.xml with language alternates")


def build(langs: list[str], quiet: bool = False):
    I18N.mkdir(parents=True, exist_ok=True)
    for lang in langs:
        if lang == "en":
            for page in PAGES:
                source = strip_generated(read_page(page))
                source = patch_common(source, page, lang)
                (WEB / f"{page}.html").write_text(source, encoding="utf-8")
            print("patched English pages")
            continue
        if not (I18N / f"{lang}.json").exists():
            print(f"missing catalogue web/i18n/{lang}.json; run extract", file=sys.stderr)
            continue
        outdir = WEB / lang
        outdir.mkdir(parents=True, exist_ok=True)
        missing_total = set()
        for page in PAGES:
            translated, missing = translate_page(page, lang)
            (outdir / f"{page}.html").write_text(translated, encoding="utf-8")
            missing_total |= missing
        filled = len(load_catalog(lang))
        print(f"{lang}: {len(PAGES)} pages, {filled} catalogue entries, "
              f"{len(missing_total)} untranslated blocks")
        write_sitemap()
        if missing_total and not quiet:
            for item in sorted(missing_total)[:8]:
                print(f"    ? {item[:100]}")


def check(langs=None):
    source = json.loads((I18N / "source.json").read_text(encoding="utf-8"))
    keys = {entry["key"] for entry in source["strings"]}
    status = 0
    for lang in (langs or TRANSLATED):
        if lang == 'en':
            continue
        catalog = load_catalog(lang)
        unknown = set(catalog) - keys
        missing = keys - set(catalog)
        bad = [key for key in keys & set(catalog)
               if set(PLACEHOLDER.findall(key)) != set(PLACEHOLDER.findall(catalog[key]))]
        print(f"{lang}: {len(set(catalog) & keys)}/{len(keys)} translated, "
              f"{len(missing)} missing, {len(unknown)} stale, {len(bad)} placeholder errors")
        for key in bad[:10]:
            print(f"    placeholder: {key[:90]}")
        if missing or unknown or bad:
            status = 1
    return status


# --------------------------------------------------------------------------
# Translation work packages (used by agents; output lands in web/i18n)
# --------------------------------------------------------------------------

WORK = Path("/tmp/opencode/i18n-work")


def make_work(lang: str, chunks: int):
    source = json.loads((I18N / "source.json").read_text(encoding="utf-8"))["strings"]
    WORK.mkdir(parents=True, exist_ok=True)
    per = (len(source) + chunks - 1) // chunks
    for index in range(chunks):
        part = source[index * per:(index + 1) * per]
        if not part:
            continue
        rows = [
            {
                "key": entry["key"],
                "pages": entry["pages"],
                "hint": entry["parts"],
                "translation": "",
            }
            for entry in part
        ]
        path = WORK / f"{lang}-{index + 1:02d}.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{path}  {len(rows)} strings, {sum(len(r['key']) for r in rows)} chars")


def merge_work(lang: str):
    import glob

    source = json.loads((I18N / "source.json").read_text(encoding="utf-8"))["strings"]
    keys = {entry["key"] for entry in source}
    catalog = load_catalog(lang)
    errors = 0
    for path in sorted(glob.glob(str(WORK / f"{lang}-*.out.json"))):
        try:
            rows = json.loads(Path(path).read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"{path}: invalid JSON: {exc}")
            errors += 1
            continue
        for row in rows:
            key = row.get("key")
            value = (row.get("translation") or "").strip()
            if key not in keys or not value:
                continue
            if set(PLACEHOLDER.findall(key)) != set(PLACEHOLDER.findall(value)):
                print(f"{path}: placeholder mismatch: {key[:80]}")
                errors += 1
                continue
            if tag_signature(key) != tag_signature(value):
                print(f"{path}: tag mismatch: {key[:80]}")
                errors += 1
                continue
            catalog[key] = value
    ordered = {entry["key"]: catalog.get(entry["key"], "") for entry in source}
    (I18N / f"{lang}.json").write_text(
        json.dumps({"version": 1, "language": lang, "strings": ordered},
                   ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    filled = sum(1 for value in ordered.values() if value)
    print(f"{lang}: {filled}/{len(ordered)} translated, {errors} rejected")



def stats():
    source = json.loads((I18N / "source.json").read_text(encoding="utf-8"))
    total = sum(len(e["key"]) for e in source["strings"])
    print(f"{len(source['strings'])} unique strings, {total} characters")
    for lang in TRANSLATED:
        filled = load_catalog(lang)
        print(f"  {lang}: {len(filled)} entries, {sum(len(v) for v in filled.values())} characters")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["extract", "build", "check", "stats", "work", "merge"])
    parser.add_argument("--lang", nargs="*", default=list(TRANSLATED), choices=list(LANGUAGES))
    parser.add_argument("--work-lang", default="ar", choices=list(TRANSLATED))
    parser.add_argument("--chunks", type=int, default=5)
    args = parser.parse_args()
    if args.command == "extract":
        extract()
    elif args.command == "build":
        build(args.lang)
    elif args.command == "check":
        sys.exit(check(args.lang))
    elif args.command == "work":
        make_work(args.work_lang, args.chunks)
    elif args.command == "merge":
        merge_work(args.work_lang)
    else:
        stats()
