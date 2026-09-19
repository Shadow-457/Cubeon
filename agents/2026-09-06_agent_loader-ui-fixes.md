# Loader switcher UI fixes (4 bugs)

User: "the loader availability checking and the loader area ui is kinda messed
up... code is poorly written". They were right. All in `main.py`
(commits pushed 2026-09-06):

1. **Wrong dimming** (`style_loader_segments`): whenever the selected version
   was installed, EVERY non-selected segment was dimmed to 0.45 — painting
   clickable, supported loaders as disabled. One dim rule now: dim only when
   (unsupported AND not installed).
2. **Toggle dead end** (`on_loader_toggle_change`): for installed versions,
   switching to Vanilla worked but switching back to an *installed* mod loader
   silently snapped back (no message) — the control felt broken. Installed
   loaders are now selectable; truly blocked picks print why.
3. **Raw-id lookups** (`refresh_loader_support`): support/installed checks
   used the raw dropdown id. If the selection was a loader row
   (`fabric-loader-0.19.3-1.21.1`), every lookup missed → dots never showed,
   support checks wrong. Now uses `core.extract_mc_version(version_id)` —
   same normalization the launch path always used (its comment at the launch
   site documents the trap).
4. **Serial network checks**: 4 loaders × ~0.6-2s each = ~4.5s of disabled
   toggle + stuck "Checking...". Now one thread per loader → ~0.5-1s total.
   Stale-worker result still populates the cache (true regardless of current
   selection) but doesn't paint.

## Diagnostic pattern that found these (reuse it!)
`tools/test_ui_smoke.py`'s `FakePage`/`FakeWindow` classes can be extracted
and `main.main(page)` driven headless with real threads — then walk the
control tree and assert on `selected_index`/`opacity`/`bgcolor`/`visible`.
Recipe:

```python
src = open("tools/test_ui_smoke.py").read()
ns = {"types": __import__("types"), "ft": __import__("flet")}
exec("import types\nimport flet as ft\n" +
     src[src.find("class FakeWindow"):src.find("def walk(")], ns)
import main as M; page = ns["FakePage"](); M.main(page); time.sleep(4)
# walk page.controls recursively; find CupertinoSlidingSegmentedButton etc.
```

Note: with no real event loop, `thread_safe_ui` prints a harmless warning;
background workers still run (plain threads), and `page.update()` on the
FakePage just counts calls. Fake an installed version by writing
`versions/<id>/<id>.json` under CUBEON_GAME_DIR before `main()`.

## Timing facts
mll `is_minecraft_version_supported` per loader: fabric 0.6s, quilt 0.6-1.1s,
forge 1.7-1.9s, neoforge 0.8-1.1s; `cubeon/local_cache` caches them (1 week),
so repeat checks are 0s. Forge is always the long pole — parallelizing puts
the total at Forge's latency.

## Question for the next agent
The loader pill (`CupertinoSlidingSegmentedButton`) shows a 5px dot under
each label when that loader is installed — is that discoverable enough vs.
e.g. a checkmark badge? If the user still calls the area "messed up", the
next lever is the layout row itself (main.py ~2360: `loader_toggle`,
`loader_status_text`, `browse_online_row` stacked in a Column next to the
340px play button) — status text appearing/disappearing changes the row
height, which may be the "settling" wobble they mean.
