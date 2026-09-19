# Installed-mods icons never appeared — missing re-export

## What was wrong
The Mods tab "installed" list renders a placeholder glyph, then a background
worker (`_fetch_missing_icons` in `ui/mods_tab.py`) is supposed to patch real
Modrinth art in via `core.get_mod_icons(slugs)`. But `launcher_core.py` re-exports
a fixed list from `cubeon.mods` and `get_mod_icons` was **not in it** (line ~61-67).
So inside the app `core.get_mod_icons` raised `AttributeError`, which the worker's
`except Exception: return` swallowed silently — rows kept the placeholder forever.

Evidence: `~/.cubeon_launcher/cache/mod_icons_*.json` had zero entries after real
usage (the 7-day disk tier had never been written), and `hasattr(launcher_core,
"get_mod_icons")` was False. Browse/recommended rows were unaffected because
search responses carry `icon_url` inline.

## Fix
Added `get_mod_icons` to the `from cubeon.mods import (...)` list in
`launcher_core.py`. Verified: re-import exposes it, `py_compile` OK, headless
run of the same lookup resolved all 11 installed slugs to URLs, and a manual
invocation of `cubeon.mods.get_mod_icons` wrote the missing disk cache.

## Note for next agent
A headless reproduction (`cubeon.mods.list_mods` + `get_mod_icons` +
`icons.local_path`) primed the disk cache, so on restart most icons load
instantly. The app must be restarted to pick up the code fix.
