# 2026-09-11 - Launcher Chat tab + automatic Cubeon name

## Ask
Add a Chat tab to the launcher (the mod's Friends/social UI shouldn't be the
only way to use it), and stop asking the user to type or claim a Cubeon name -
derive it automatically from the existing secret so it "just works".

## Design decisions (user-confirmed)
- **New top-nav Chat tab**, not a rewrite of the in-game mod screen. It drives
  the process-scoped `FriendsService` directly instead of the localhost bridge
  the mod uses, so friends/chat work without launching Minecraft.
- **Full social layer**, not chat-only: roster + presence, add, accept/decline,
  remove, plus DMs.
- **Automatic name = pure secret-derived handle**: `Player_<first 8 hex of
  sha256(stable_secret())>`. Deterministic per `auth_key.json`, 15 chars, inside
  `[A-Za-z0-9_]{3,16}`, never reserved. No prompt, never the MC username.

## What changed
- **`cubeon/friends.py`** - `import hashlib`, `AUTO_NAME_PREFIX = "Player_"`,
  `auto_name()`, `ensure_identity()`. `ensure_identity()` returns an existing
  named identity untouched (so a user rename or a friend-known handle is never
  rotated) and only mints + persists `save_identity(auto_name())` when none
  exists. Identity remains the same durable account (stable secret/uuid), so the
  server can bind the handle claim-on-connect at the WS hello
  (`worker/cubeon-friends.js` `onHello`) with no claim round-trip.
- **`ui/chat_tab.py`** (NEW) - `build_chat_tab(page, cfg, state, service, *,
  section_label, **THEME) -> (root, refresh)`. Left column: connection pill,
  "You are <handle>", add-friend, Requests, Friends. Right column: conversation
  header + remove, transcript, composer. Theming uses the Mods-tab language
  (`CARD_FILL`/`CARD_BORDER`, `ROW_HOVER`, `ACCENT_TINT`) via `attach_hover`,
  no nested solid panels. Polls on a daemon thread through
  `cubeon/thread_safe_ui.py`. `service is None` returns a static notice.
- **`main.py`** - imports `friends_enabled` / `build_chat_tab`; nav inserts
  `("chat", CHAT_BUBBLE_ROUNDED, "Chat")` at index 3 only when enabled; lazy
  `_build_chat_tab`, `_TAB_BUILDERS["chat"]`, `tabs["chat"]`, `switch_tab`
  branch. Startup mints the identity but connects only if an identity *already*
  existed; a brand-new one connects when the Chat tab first opens. This keeps
  headless UI test harnesses from opening real websockets with throwaway
  identities. The public-build `if friends_service is not None:
  friends_service.set_version(...)` guard is untouched.

## Verification
- `test_friends_service` 200/200 (+13): new `test_automatic_identity` pins
  determinism, name-rule validity, reserved safety, mint-and-persist, no
  rotation on a second call, and that a renamed identity is untouched. The
  headless section now also asserts `ui/chat_tab.py` exists, exports
  `build_chat_tab`, and is wired into `main.py`.
- `test_ui_smoke` 96/96 (+3): Chat tab exists + nav/lazy-builder wiring, the
  `service is None` degradation, and the daemon-thread/thread_safe_ui poll.
- Full sweep green: `test_friends.py` 37, `test_mod_bridge` 119,
  `test_mod_matrix` 68, `test_mod_compile` clean, `test_modpacks` 51,
  `test_milestones` 50 (one known flake, passed on rerun), `test_gallery` 38,
  `test_capes` 14, `test_net` 19, `test_mod_store` 21,
  `test_versions_profile_key` 11, `test_launch_indicator` 11.
- Docs: `agents/docs/module-map.md` (last-updated line, one-paragraph intro,
  `ui/` row, `friends.py` row, new Chat-tab/auto-identity facts bullet, test
  counts) and `agents/docs/guide-ui-modules.md` (architecture tree, startup
  snippet, new `ui/chat_tab.py` section).

## Note for next agent
- If you add another tab, remember the public-build rule: `friends_service` is
  `None` when `features.friends_enabled()` is false - every reference outside
  the enabled block must tolerate it.
- The auto handle is stable *only* as long as `auth_key.json` survives. Losing
  it mints a new handle (a new account to the server). That is by design; do not
  "fix" it.
