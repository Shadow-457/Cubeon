# Friends mod Account tab now says "You are <name>"

- **Agent:** opencode (deepseek-v4-flash)
- **Date:** 2026-09-02
- **Task:** "in the friends mod, the account area doesn't show my own name — it
  should say 'you are <name>'."

## What I did

The in-game Friends screen's Account tab showed the identity only as a quiet
prose line ("Your Cubeon name: shadow") above a big gap and the rename box at
the bottom, and the top header hid the name whenever presence was reconnecting.
Two mod-side text fixes:

1. `CubeonFriendsScreen.java` (`applyInfo`, account branch): when a name is
   claimed the first line now reads **"You are shadow."** (plain white);
   unclaimed it's a gold "Claim your Cubeon name" prompt. Dropped the
   now-redundant connection-status repeat inside the tab (the header above the
   tabs already carries it for every tab).
2. `Bridge.java` (`Snapshot.connectionLine`): the offline case now keeps the
   name visible — "Offline - reconnecting as shadow" instead of "Offline -
   reconnecting...".

No launcher-side change was needed: `/friends` already returns `"you"` from
`friends.current_name()` (identity.json), and this machine's identity is
`shadow`.

## How I verified

- `python3 tools/test_mod_compile.py` -> all sources compile clean against the
  version-stable API subset.
- Rebuilt both jars:
  - `python3 tools/build_mod_jars.py 26` (javac)
  - `PATH=/tmp/gbuild/gradle-9.7.1/bin:$PATH python3 tools/build_mod_jars.py 1.20-1.21`
- Deployed each family and md5-verified: `mod/build/libs/`,
  `~/.cubeon_launcher/cache/`, `~/.minecraft/mods/` (mc26) and
  `~/.cubeon_launcher/mod_profiles/{1.20.1,1.21.8,26.1.2}-fabric/`.
- Not verified in a live game (launcher not running / not reproduced headless);
  needs the user to relaunch MC with the launcher up to confirm the new wording.

## Notes for the next agent

- The player's Cubeon name (`shadow`) lives in `~/.cubeon_launcher/identity.json`
  and is unrelated to the launcher Profile username
  (`cfg["username"] = "Shadoww___4577"`). If the mod ever reports "not claimed"
  for a user who set a launcher username, they simply never claimed a Cubeon
  name - point them at the Account/Set up tab.
- `agents/` now also holds the old root `docs/` and `memory/` folders
  (`agents/docs/`, `agents/memory/`); a stray old jar
  `cubeon-friends-1.0.0.jar` sits in `mod_profiles/_unsorted-unknown/` (legacy,
  pre-bracket) - ignored by `cubeonfriends.py`.
