"""Launcher language selection (2026-10-28).

WHY THIS EXISTS
---------------
The launcher shipped English-only. Every string was a literal at its call
site, so "add a language" meant touching all of them. This module is the seam:
UI code calls ``i18n.t("Play")`` and gets the player's language back, or the
English it was handed if there is no translation.

HOW TRANSLATION IS KEYED
------------------------
The ENGLISH TEXT IS THE KEY. There is no parallel key registry to keep in
step, a string that nobody translated simply renders in English instead of as
``nav.play`` or a blank, and a translator reading a table sees the sentence in
context. The cost is that rewording an English string orphans its
translations - `tools/test_i18n.py` reports those as orphans so the drift is
visible instead of silent.

RTL
---
Arabic (and any future RTL language) needs more than translated words: the
whole layout has to mirror. ``is_rtl()`` is the single answer, and main.py
feeds it to ``page.rtl``. Nothing else in the app should be guessing from the
language code.

CONTRACTS
- ``t()`` NEVER raises and never returns a falsy value for a non-empty input.
  A missing table, a bad locale or a non-string argument all fall back to the
  text it was given. The launcher must not fail to start over a translation.
- The active language is process-global and read from UI threads and worker
  threads, so it is guarded by a lock and only ever swapped wholesale.
- Setting the language does NOT repaint anything. Callers that can rebuild
  their controls do; the rest pick the new language up on the next start, and
  the Settings row says so.
"""
from __future__ import annotations

import locale
import logging
import os
import threading

log = logging.getLogger(__name__)

__all__ = [
    "CONFIG_KEY",
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "SUPPORTED",
    "current",
    "is_rtl",
    "language_name",
    "resolve_language",
    "set_language",
    "t",
]

# The config.json key. An empty/absent value means "detect from the OS once,
# then remember" - see resolve_language().
CONFIG_KEY = "ui_language"
DEFAULT_LANGUAGE = "en"

# (code, native name, English name, rtl). The native name is what the picker
# shows - a player choosing a language should read it in THAT language, which
# also makes the list usable before any translation is loaded.
#
# ORDER IS THE USER'S: Arabic, English, Russian, Spanish first, then the rest
# of the widely-spoken languages by rough speaker population.
LANGUAGES = (
    ("ar",    "العربية",              "Arabic",              True),
    ("en",    "English",              "English",             False),
    ("ru",    "Русский",              "Russian",             False),
    ("es",    "Español",              "Spanish",             False),
    ("zh-cn", "简体中文",              "Chinese (Simplified)", False),
    ("hi",    "हिन्दी",                 "Hindi",               False),
    ("pt-br", "Português (Brasil)",   "Portuguese (Brazil)", False),
    ("fr",    "Français",             "French",              False),
    ("de",    "Deutsch",              "German",              False),
    ("ja",    "日本語",                "Japanese",            False),
    ("tr",    "Türkçe",               "Turkish",             False),
    ("ko",    "한국어",                "Korean",              False),
    ("it",    "Italiano",             "Italian",             False),
    ("pl",    "Polski",               "Polish",              False),
    ("id",    "Bahasa Indonesia",     "Indonesian",          False),
    ("uk",    "Українська",           "Ukrainian",           False),
    ("ur",    "اردو",                 "Urdu",                True),
    ("bn",    "বাংলা",                "Bengali",             False),
    ("fa",    "فارسی",                "Persian",             True),
    ("ms",    "Bahasa Melayu",        "Malay",               False),
    ("ps",    "پښتو",                 "Pashto",              True),
    ("ur-latn", "Roman Urdu",         "Urdu (Latin)",        False),
)

SUPPORTED = tuple(code for code, *_ in LANGUAGES)
_RTL = {code for code, _n, _e, rtl in LANGUAGES if rtl}
_NAMES = {code: (native, english) for code, native, english, _r in LANGUAGES}

_lock = threading.RLock()
_active = DEFAULT_LANGUAGE
_tables: dict[str, dict] = {}
_orphans: set[str] = set()


def _load_table(code: str) -> dict:
    """The translation table for `code`, loaded once. English has none.

    Import failures are logged, not raised: one broken language file must not
    take the launcher down, and it must not break the OTHER languages either.
    """
    if code == DEFAULT_LANGUAGE:
        return {}
    with _lock:
        cached = _tables.get(code)
    if cached is not None:
        return cached
    table: dict = {}
    try:
        from cubeon import lang
        table = dict(getattr(lang, "table_for", lambda _c: {})(code) or {})
    except Exception:
        log.warning("could not load the %r language table", code, exc_info=True)
    with _lock:
        _tables[code] = table
    return table


def set_language(code: str | None) -> str:
    """Make `code` the active language. Returns what is now active.

    An unknown or empty code falls back to English rather than raising: a
    hand-edited config.json is not a reason for the launcher to fail to start.
    """
    global _active
    want = str(code or "").strip().lower()
    if want not in SUPPORTED:
        want = DEFAULT_LANGUAGE
    with _lock:
        _active = want
    _load_table(want)
    return want


def current() -> str:
    """The active language code."""
    with _lock:
        return _active


def is_rtl(code: str | None = None) -> bool:
    """Does this language (default: the active one) read right-to-left?

    main.py feeds this to ``page.rtl``. One answer for the whole app, so a
    half-mirrored layout is not a thing that can happen.
    """
    return (code if code is not None else current()) in _RTL


def language_name(code: str, *, english: bool = False) -> str:
    """The picker label for a code: its native name, or its English one."""
    native, eng = _NAMES.get(str(code or "").strip().lower(), (None, None))
    if native is None:
        return str(code or "")
    return eng if english else native


def resolve_language(cfg: dict | None = None, *, env=None) -> str:
    """The language to use at startup: explicit config, else the OS locale.

    Deliberately does NOT write anything. main.py persists the answer only
    when the config had no value, so a player's choice is never overwritten by
    a later boot on a differently-configured machine.
    """
    env = os.environ if env is None else env
    try:
        chosen = (cfg or {}).get(CONFIG_KEY)
    except Exception:
        chosen = None
    if chosen:
        want = str(chosen).strip().lower()
        return want if want in SUPPORTED else DEFAULT_LANGUAGE
    for var in ("CUBEON_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        try:
            raw = str(env.get(var) or "").strip().lower()
        except Exception:
            raw = ""
        if not raw:
            continue
        for token in raw.split(":"):
            got = _match_locale(token)
            if got:
                return got
    try:
        got = _match_locale(locale.getlocale()[0] or "")
        if got:
            return got
    except Exception:
        pass
    return DEFAULT_LANGUAGE


def _match_locale(raw: str) -> str | None:
    """Map a locale string onto a supported code, or None.

    Handles the spellings real systems use: ``pt_BR.UTF-8``, ``zh_CN``,
    ``ar_SA:ar``, ``ru``. Region matters only where we ship a regional table
    (pt-br, zh-cn); ``pt`` alone still gets Brazilian Portuguese rather than
    nothing, because that is the table we have.
    """
    token = str(raw or "").split(":")[0].split(".")[0].replace("_", "-").lower()
    if not token or token in ("c", "posix"):
        return None
    if token in SUPPORTED:
        return token
    base = token.split("-")[0]
    if base in SUPPORTED:
        return base
    # Windows may report language names (Arabic_Saudi Arabia) rather than
    # ISO codes. Match the names in the catalog before the regional fallback.
    for code, _native, english, _rtl in LANGUAGES:
        if english.split(" (")[0].lower() == base:
            return code
    # A language we only ship regionally: pt -> pt-br, zh -> zh-cn.
    for fallback in (f"{base}-br", f"{base}-cn"):
        if fallback in SUPPORTED:
            return fallback
    return None


def t(text, **kwargs) -> str:
    """Translate `text` into the active language.

    Returns the English it was given when there is no translation, which is
    what makes a partially-translated language safe to ship. ``kwargs`` are
    ``str.format`` substitutions applied AFTER translation, so a language can
    reorder them ("{name} is online" -> "在线：{name}").

    Never raises. A format error leaves the unformatted translation in place
    rather than losing the string entirely.
    """
    if text is None:
        return ""
    source = text if isinstance(text, str) else str(text)
    if not source:
        return source
    code = current()
    out = source
    if code != DEFAULT_LANGUAGE:
        table = _load_table(code)
        hit = table.get(source)
        if isinstance(hit, str) and hit:
            out = hit
        else:
            with _lock:
                # Bounded: this is a diagnostic for translators, not a leak.
                if len(_orphans) < 5000:
                    _orphans.add(source)
    if kwargs:
        try:
            return out.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            log.debug("could not format %r with %r", out, kwargs, exc_info=True)
    return out


def untranslated() -> frozenset:
    """English strings shown in the active language because no table has them.

    Exposed for tests and for translators; nothing in the launcher reads it.
    """
    with _lock:
        return frozenset(_orphans)


def reset_orphans() -> None:
    with _lock:
        _orphans.clear()
