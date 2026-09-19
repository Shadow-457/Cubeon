# 2026-09-11 — plain copy + near-black palette

## What I did
Two things the user asked for across the whole launcher:

1. **Cut technical text.** Rewrote user-facing strings so they read like a
   game launcher, not a dev log. No more `jar`, `process/PID`, `hash`,
   `config.json`, `UUID`, `.zip`, `OS`, "in this build", "plugin stack",
   "CustomSkinLoader", "vanilla-compatible", "Launch id", "(high water)".
   Touched:
   - `ui/mods_tab.py`: header subtitle + search hints, empty-state hint
     (was "drop .jar files into the mods folder"), shader notice.
   - `ui/modpacks_tab.py`: subtitle, empty-profile text, CurseForge
     tooltips (dropped `config.json`/"power users"), delete-dialog wording.
   - `ui/server_tab.py`: Install tooltip, RAM warning ("your OS" → "your
     computer"), security-password tooltip, smooth-mode label/status,
     plugins subtitle, delete dialog, orphaned-server notice (dropped PID).
   - `ui/chat_tab.py`: dev-build notice, rename/add hints.
   - `ui/skin_tab.py`: skin-visibility note (dropped CustomSkinLoader),
     "Recommended … load in the background" → "Loading recommended …".
   - `ui/stats_tab.py`: "this install has done" → "you've done".
   - `main.py`: legacy note + legacy dialog, off-switch checkbox labels
     moved to Settings rows (blank checkbox labels), onboarding
     "Profile" → "Account menu", Minekube badge strings, RAM warning "OS"
     → "computer", instance-rename dialog (removed the launch-id mono line).
2. **Less green, more black.** The neutral ramp in `cubeon/theme.py` is
   already near-black/near-neutral. This pass also swapped the loader
   segmented control's solid `#33431E` olive thumb for the theme's
   `ACCENT_TINT_HI` wash, so the only remaining green is accents. New
   `ACCENT_TINT_HI` import in main.py.

## Verify
`python3 -m py_compile` on every edited file. Full sweep green:
test_ui_smoke 97/97, test_friends_service 213, test_friends 37,
test_mod_bridge 119, test_capes 14, test_invites 127, test_modpacks 51,
test_mod_store 21, test_net 19, test_production 13,
test_versions_profile_key 11, test_launch_indicator 11, test_gallery 38,
test_mod_matrix 68. test_milestones hit the known 1-in-3 "no unlock → no
sync POST" flake, passed 50/50 on rerun.

## Notes for the next agent
- `web/index.html` still carries the old olive CSS vars (`--deep:#0E110A`
  etc.). That's the marketing site, not the launcher — left alone.
- Durable rules captured in `agents/docs/module-map.md` under the Play page
  section (palette + copy rule).
