"""Per-language string tables for cubeon/i18n.py.

One module per language, named for its code with ``-`` replaced by ``_``
(``pt-br`` -> ``pt_br.py``), each exporting ``TABLE``: a dict whose KEYS are
the English source strings and whose VALUES are the translation.

English has no module - it is the key space, so ``t("Play")`` in English is
just "Play".

Adding a language:
  1. add it to ``i18n.LANGUAGES`` (code, native name, English name, rtl);
  2. add ``<code>.py`` here with a ``TABLE``;
  3. run ``python tools/test_i18n.py`` - it reports strings your table has
     that the UI no longer uses, so the table cannot rot silently.

Partial tables are fine and expected: an untranslated string renders in
English. Do not fill a table with the English text just to look complete -
that hides the gap from translators and from the orphan report.
"""
from __future__ import annotations

import importlib
import logging

log = logging.getLogger(__name__)

__all__ = ["table_for"]

_cache: dict[str, dict] = {}


def table_for(code: str) -> dict:
    """The TABLE for a language code, or {} when there is none.

    Never raises: a language with a broken or missing module simply renders in
    English, and must not disturb the languages that did load.
    """
    key = str(code or "").strip().lower()
    if key in _cache:
        return _cache[key]
    if not key or key == "en":
        return {}
    table: dict = {}
    try:
        module = importlib.import_module(f"cubeon.lang.{key.replace('-', '_')}")
        raw = getattr(module, "TABLE", None)
        if isinstance(raw, dict):
            table = {str(k): str(v) for k, v in raw.items()
                     if isinstance(v, str) and v}
        else:
            log.warning("cubeon.lang.%s has no TABLE dict", key)
    except ModuleNotFoundError:
        log.debug("no table for language %r", key)
    except Exception:
        log.warning("could not import the %r table", key, exc_info=True)
    _cache[key] = table
    return table
