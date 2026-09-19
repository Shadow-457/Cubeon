# 2026-09-12 - Refined the Cubeon-to-Cubeon join, no architecture change

## Ask
"work like this just refine it no thing change needed" - keep the invite-
flow (explained: no Minekube domain is involved; Cubeon does the networking
itself via punch/relay), don't add the proxy, just polish what the joiner
sees when their mods differ.

## What changed (all presentational / tested)
- cubeon/friends_service.py
  - `_mod_stem(filename)` -> the mod NAME (tokens before the first digit-led
    one). Purely presentational; a digit-led filename yields "" and can
    never claim a match.
  - `_sync_on_reply` computes `rep["version_licts"]`: missing mods whose stem
    the JOINER already has (a same-name, different-sha file).
  - `_sync_render` prints a "You have a DIFFERENT version of:" block for
    those, so a version clash isn't left as an unexplained duplicate, and
    rewrote the relaunch line to say the host's mods are installed + linked
    and to press Fix and relaunch.
- mod .../CubeonClientScreen.java: the sync action button is now "Fix"
  (was "Download mods"); its behavior (install into the global store,
  link into the profile, then relaunch by hand) is unchanged.
- report dicts init get `version_licts: []`.

## Deliberately NOT changed
No proxy, no Minekube domain, no Friends-tab removal, no auto-restart (the
relaunch stays a player action). Auto-restart and the domain need the proxy
component the user passed on for now.


## Verification
- test_friends_service 259/259 (+7: stem semantics + DIFFERENT-version
  call-out incl. absence when no clash).
- mod_bridge 119, mod_compile clean, mod_matrix 68, friends 48, ui_smoke 112,
  production 13. BOTH jars rebuilt + redeployed.
