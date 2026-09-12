# 2026-09-08/09 — 4 FPS fix, keyboard-as-gamepad gate, ink ripples, snappy pass

Follow-up to `2026-09-08_agent_dialog-fixes.md`. Same box (KDE/X11, Mesa 26.1).
Five user complaints across two days, all fixed and regression-tested.

## 1. Minecraft ran at 4 FPS — the launcher poisoned the game's GL

**Diagnosis path** (worth remembering): user said "in-game 4 FPS", launcher
itself was smooth, so my first instinct (controller event flood stealing CPU)
was wrong. The real cause: the GPU-crash fallback from the mid-session
recovery work armed `use_software_gl`, `_session_loop` set
`LIBGL_ALWAYS_SOFTWARE=1` + `GALLIUM_DRIVER=llvmpipe` in the launcher's own
environment, and `cubeon/launch.py` spawned java **inheriting that env**.
Verified with hard evidence:

```
$ tr '\0' '\n' < /proc/27124/environ | grep -i "LIBGL\|GALLIUM"
LIBGL_ALWAYS_SOFTWARE=1
GALLIUM_DRIVER=llvmpipe
```

Minecraft on llvmpipe = ~4 FPS. Exactly matched the symptom.

**Fixes** (both, belt and braces):
- `cubeon/launch.py`: Popen now gets `env=` with `LIBGL_ALWAYS_SOFTWARE`,
  `GALLIUM_DRIVER`, `LIBGL_DRM_DEVICE` stripped. The game's GL stack is its
  own; the launcher's driver bug is not the game's.
- `main.py` `_reveal_window`: the `use_software_gl` marker is deleted the
  moment the UI paints. Before, it only cleared on a *clean close*, so any
  kill/crash left it armed and every subsequent session (and game) ran
  software GL forever.

Note: the marker was still armed on disk when I started; it's gone now, and
the running game (pid 27124 at the time) was the poisoned one — user needs a
game restart to get hardware GL back.

## 2. "🎮 Baseus K03 Keyboard connected" — keyboard detected as gamepad

`/dev/input/js0` on this box is the **keyboard** (Baseus K03, exposes a js
HID interface for media keys: 3 buttons, 1 axis). The watcher accepted any
js device, so it toasted a connection and then translated key presses into
menu navigation.

**Fix** in `cubeon/controller.py`:
- `_probe_shape(f)` — non-blocking read of the JS_EVENT_INIT dump that the
  kernel replays on open; collects button/axis numbers.
- `_looks_like_gamepad(name, buttons, axes)` — keyboard/mouse/touchpad-named
  devices refused outright; pad-named devices (xbox/dualsense/8bitdo/...)
  need ≥4 buttons; unnamed need ≥8 buttons + ≥4 axes.
- `_scan` probes before accepting; rejected paths land in `_rejected` so the
  2s scan doesn't re-open them forever.

**Verified live**: ran ControllerWatcher against the real js0 — zero events,
`is_connected()` False, `{'/dev/input/js0'}` in `_rejected`. Synthetic pad
names (Xbox/DualSense/8BitDo/generic joystick) all pass; keyboard/mouse
names all refuse.

## 3. Ink ripples removed

User hates the Material ink splash. All `ink=True` → `ink=False` across
main.py, ui/*.py, cubeon/theme.py, cubeon/inspector.py (50 static sites +
3 dynamic `ink=not is_installed` sites). Left alone: `archive/` (dead dist
copies) and `ui_new/preview.py` (the --new-ui design mock, not live UI).

## 4. Account panel "reloaded the whole app"

`_open_account_panel`/`_close_account_panel` ended in `page.update()`, which
diffs EVERY control in the tree — the visible effect is the entire app
flickering/reloading on each panel toggle. Fixed to per-control diffs:
`thread_safe_ui.refresh(account_scrim)` + `refresh(account_panel)` (the
pattern `_retire_scrim` already used). Verified via FakePage harness:
0 `page.update` calls for a full open+close cycle, state transitions correct
(panel.right 0↔-390, scrim opacity/visible toggled). ui_smoke §10 gained a
check that no raw `page.update()` line sits in either handler (regex on
`^\s*page\.update\(\)` — plain substring matching false-positives on the
explanatory comments, don't downgrade it).

## 5. "Rendering feels sloppy" — tab-switch hitch killed (2026-09-09)

Two stacked causes. (a) The launcher had been running on llvmpipe (the armed
software-GL marker — healed by fix #1; user just needed a launcher restart).
(b) `switch_tab` ended in `page.update()` — a full-tree diff of every mounted
tab over the websocket, right at the moment of the switch — plus a 220ms
AnimatedSwitcher fade on top. Changes:

- `switch_tab` tail → `thread_safe_ui.refresh(tab_switcher / subnav_bar /
  nav buttons)`.
- AnimatedSwitcher fade → `duration=0, reverse_duration=0` (kept as a
  switcher so `.content` assignment code is unchanged).
- `refresh_installed_packs` (ran on every Modpacks visit) → scoped diff of
  `installed_view` + `installed_count`.

Measured in the FakePage harness: steady-state switch 0 page.update calls /
~3ms wall; first visit to a lazy tab ~87ms once (the build). Remaining
`page.update()` sites are one-shot action handlers (install buttons, filter
toggles) — acceptable, they run on explicit user actions, not per frame.

Also checked: no launcher process was running with LIBGL at audit time; GPU
is an RX 580 with working radeonsi direct rendering, so hardware GL is fine
when the marker isn't armed.

## 6. Efficiency pass (2026-09-09, "make it more efficient")

Audited every always-on loop and hot callback path. Three changes:

- **`net.stream_to_file` progress throttle** (the big one): progress_cb fired
  per 64 KiB chunk → hundreds of UI repaints/sec on fast links (every
  download: versions, mods, modpacks). Now emits at most every 33ms OR every
  1% of the file; one guaranteed final callback carries the exact byte count
  (resume/hash callers depend on it — verified: 100 MB instant download went
  1600 callbacks → 101, final cb exact).
- **P2P `_tcp_outbound_loop` de-polled**: was `time.sleep(0.01)` forever
  (~100 wakeups/sec per session). Now a Condition (`_outbound_wake` on
  `_state_lock`) with 0.2s wait timeout; nudged by ACK-freed window space
  (`_handle_frame`) and `close()`. Full `test_p2p_*` suite green
  (session/transport/batch6/hybrid/relay).
- Confirmed already-good paths (left alone): console append is coalesced
  (80ms flush, 800-line cap, TREE_LOCK), `set_status` diffs two controls,
  backup scheduler sleeps 1800s, name-contest check is one-shot.

Full battery after: ui_smoke 68, fuzz 12, production 13, mod_store 21,
modpacks 51, capes 14, friends_service 187, friends 37, mod_bridge 119,
mod_matrix 68, net 19, invites 127 — all green.



- `python3 tools/test_ui_smoke.py`: **68 passed, 0 failed** — added §10 with
  8 new checks (no-ink scan, 3 gamepad-gate unit checks, probe wiring,
  env-strip in launch.py, marker-clear in _reveal_window, account-panel
  scoped diffs).
- Full battery: fuzz 12, production 13, mod_store 21, modpacks 51, capes 14,
  friends_service 187, friends 37, mod_bridge 119, mod_matrix 68, net 19,
  invites 127 — all green.
- `py_compile` clean on every touched file.

## 7. Browse/Installed toggle views (2026-09-09, user request)

Mods (with resourcepacks + shaders), modpacks, and server plugins no longer
stack the installed list below a full catalog scroll. Each surface now has
`view_segment_row` underline tabs (Browse | Installed (N)) above two
always-mounted panes — `on_view_change` flips `.visible` only, nothing is
rebuilt or re-fetched. The Installed label carries a live count, refreshed
by the existing refresh_*_list() calls (which also switched to scoped
diffs — `refresh_plugins_list` dropped its `page.update()`).

Gotcha hit: server_tab's panes reference market controls (plugin_search_field
etc.) defined ~200 lines later than `installed_plugins_list` — the pane
construction must sit after ALL its children exist (mine now lives right
after `plugin_search_button`), while `refresh_plugins_list` (defined earlier)
can still call `_build_plugins_view_segment()` because Python resolves names
at call time.

Verified in the FakePage harness: all three surfaces mount, the Installed
tab is found and clickable both ways, no exceptions. ui_smoke 72/72 (§11 has
4 new checks). Full battery green.

## 8. Browse-row unification: modpacks + plugins match the mods row (2026-09-09)

User: "mods/shaders/resourcepacks one looks good — plugins and modpacks need
to look like the mods one." So `build_pack_row` (modpacks) and
`_plugin_result_row` (plugins) were restyled to the mods browse-row pattern:
transparent at rest with `attach_hover(..., "transparent", ROW_HOVER)` lift,
15px bold title + 12px description + 11px TEXT_FAINT mono metadata, and the
action button a restrained ACCENT_TINT wash (not solid ACCENT): "Install /
Installed" with ACCENT/TEXT_FAINT text. Placeholder icons use ROW_HOVER fill
with TEXT_FAINT glyphs. Both needed extra direct imports from cubeon.theme
(ROW_HOVER, ACCENT_TINT, TEXT_FAINT; plugins also attach_hover) since tab
builders only take the fixed THEME kwarg set.

The earlier plan in this turn (big cover-art store cards from the ASCII
sketch) was superseded by this request — mods rows were explicitly kept
as-is.

Verified in FakePage harness: modpacks auto-load shows 5 rows with
`bgcolor=None` at rest, ACCENT_TINT button fill, no border; plugins after a
Search click shows 4 rows same pattern, install button still clickable.
Full battery green (ui_smoke 72, modpacks 51, production 13, mod_store 21,
fuzz 12, mod_bridge 119, mod_matrix 68).

## 9. Full pane unification (2026-09-09, follow-up)

"Not quite look good" meant the SURROUNDINGS, not the rows: plugins/modpacks
still had SURFACE-slab panes, a big ACCENT icon + Minecraftia "Plugin Market"
header, bright SURFACE_HI search fields and solid-green Search buttons, and
boxed installed rows. All aligned to the mods tab's pane anatomy:

- browse/installed panes are bare Columns (no bgcolor/border slab; the only
  remaining slab in modpacks is the hidden install progress card)
- search fields: CARD_BORDER / ACCENT_DIM focus / CARD_FILL / 46px /
  TEXT_FAINT hints (mods search styling); plugins' solid-green Search button
  deleted (Enter + the field itself carry it, like mods)
- plugins' "Plugin Market" hero header replaced by a 12px TEXT_DIM mono
  caption ("Plugin picks") on the same line as the status text — same role
  as mods' "Recommended" line
- installed rows (packs + plugins) now transparent-until-hover with
  13.5px/W_600 names + TEXT_FAINT mono subtitles, matching mods' installed
  rows

## 10. Stats tab (2026-09-09, user request)

New top-nav tab ("stats", QUERY_STATS_ROUNDED icon) built in ui/stats_tab.py:
one clean screen of big Minecraftia numbers + small mono captions in three
sections — Playtime (time in game, sessions hosted, friends high-water,
hats unlocked), Library (instances, mods, modpacks, packs+shaders, server
plugins), Cosmetics (custom skins, custom capes, "using Cubeon since").
No slabs, no boxes — numbers are the UI, quiet rules between sections.

Data sources are all pre-existing: milestones.json (playtime/hosted/friends/
unlocks), versions scan, folder globs, skins/capes metadata. Wired like the
other lazy tabs: `stats_tab_host` Container, `_build_stats_tab`, entry in
`_TAB_BUILDERS` + `tabs`, and a `stats` branch in `switch_tab` that
`_ensure_tab`s then calls its refresh.

Gotcha honored: the counts glob folders DIRECTLY (PROFILES_DIR/*/
*.jar, SERVERS_DIR/*/plugins/*.jar, RESOURCEPACKS_DIR/SHADERPACKS_DIR
*.zip) because get_profile_dir()/get_plugins_dir()/content_dir() CREATE
directories on read — a stats pass must not litter empty folders. The
smoke test enforces this with a comment/docstring-stripping matcher
(`_code_lines`), since the docstrings legitimately mention those names.

Flet 0.86 note: `ft.margin.only/.symmetric` don't exist — use
`ft.Margin(l, t, r, b)`.

Verified: harness navs stats → all 12 values render (incl. "Sep 2026"
member-since), stats→play→stats→mods→stats round-trips clean. ui_smoke
74/74, full battery green.

## Verification

- `python3 tools/test_ui_smoke.py`: **68 passed, 0 failed** — added §10 with
  8 new checks (no-ink scan, 3 gamepad-gate unit checks, probe wiring,
  env-strip in launch.py, marker-clear in _reveal_window, account-panel
  scoped diffs).
- Full battery: fuzz 12, production 13, mod_store 21, modpacks 51, capes 14,
  friends_service 187, friends 37, mod_bridge 119, mod_matrix 68, net 19,
  invites 127, p2p (session/transport/batch6/hybrid/relay) — all green.
- `py_compile` clean on every touched file.

## For the next agent

- If a user reports slow Minecraft again, check
  `tr '\0' '\n' < /proc/<java pid>/environ | grep LIBGL` FIRST. One command,
  instant answer. Env inheritance is a recurring trap: anything main.py sets
  in `os.environ` post-fork reaches the game unless launch.py filters it.
- The keyboard STILL owns /dev/input/js0; that's a hardware/udev fact, not a
  bug. Our gate handles it, but if you touch controller.py keep the gate —
  ui_smoke will fail you if you break it.
- `_probe_shape` waits up to 200ms for the INIT dump; don't raise that much
  — it runs inside the 2s scan loop while holding `self._lock`.
- Lazy tabs build on FIRST visit (~87ms once for mods); steady-state tab
  switches are ~3ms with zero full-page updates. If you add a new tab,
  follow the switch_tab scoped-refresh pattern — ui_smoke §8/§10 exercise it.
