## Sandbox launcher tool (2026-09-13) — testing friends with yourself
- `tools/launch_sandbox.py <name>` boots a SECOND real launcher window with a
  fully isolated account: HOME+USERPROFILE point at
  `~/.cubeon_test_sandboxes/<name>/`, so CUBEON_HOME (and the whole friends
  identity/auth_key/config/geometry) is fresh → new stable secret → new
  auto name → new server-assigned 12-digit ID. `--list` shows every sandbox
  account + ID; `--wipe <name>` stops (SIGTERM off the pid file) and deletes.
- Two launchers coexist fine: the bridge binds a random 127.0.0.1 port +
  per-instance token (`("127.0.0.1", 0)` in local_api.py); no single-instance
  lock exists.
- **Critical gotcha (bitten live):** overriding HOME also moves the python
  USER-SITE dir (~/.local/...), so the child dies with
  `ModuleNotFoundError: No module named 'flet'` at startup. The tool must set
  `PYTHONUSERBASE=<real home>/.local`. Same family as the _sandbox_home leak
  noted in the AI-driver section.
- By default the sandbox SHARES the real game dir via CUBEON_GAME_DIR (no MC
  re-download); `--isolated-game` gives it its own. Only two simultaneous
  GAME launches into the shared dir would clobber the mods/ sync.
- Verified live: sandbox "bot1" minted Player_d4652512, connected, and got
  ID 000000000002 (main account is 000000000001) — ready to friend+chat.

## Chat identity card: username + profile picture (2026-09-13, same day)
- The card is now: profile avatar + display NAME (cfg["username"] from the
  Play tab, falling back to the relay name until one is picked) + the ID as a
  small dim secondary line + copy button. The ID is intentionally demoted —
  the user's read: the name is what you present, the ID is a personal,
  un-takeable account handle.
- `_set_you_avatar()` renders the Profile tab's picture (profile.py
  `get_profile_picture_path`, PFP_DIR/avatar.png) as a 34px rounded image;
  color-initial fallback when none. The pfp path is part of `_apply_identity`'s
  change-signature, so swapping the picture repaints the card on the next
  1.5s tick without any friends-state change.
- HONEST LIMIT: friends' profile pictures are NOT shown — a friend's PFP lives
  on THEIR machine and nothing in the friends protocol transmits it. Friend
  rows keep the color-initial avatars keyed on their relay name. Sending
  display names/avatars would be a protocol change (worker + client).
- Mega smoke 16/16, UI smoke 116/116.
