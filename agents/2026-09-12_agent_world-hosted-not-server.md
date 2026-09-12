# 2026-09-12 - Address in Minecraft chat; world hosted, not the server

## Ask
"i want adress to show in minecraft chat and i want like world to be hosted
not server adress ... just fix things up ... we just push it fully."

## Finding (verified in the shipped connect-spigot.jar)
Minekube Connect is a tunnel for the host's PAPER SERVER - no target/local
host:port config key exists - so the old fallback that pointed the joiner at
<endpoint>.play.minekube.net landed them in the SERVER's world, never the
LAN world. The only transports that carry the client LAN world are the direct
punch and Cubeon's relay (which bridges the host's LAN TCP port).

## What changed
- `_switch_to_minekube` no longer redirects the joiner. The punch-failed
  session stays on the relay (world, higher ping); the Minekube address is
  announced into the HOST's Minecraft chat, labelled as the Cubeon server.
  The joiner's `p2p_use_minekube` handler is kept for old-launcher hosts.
- `FriendsService.notify_active()` + `_active` registry (set in start,
  cleared in stop): any module can push a line into the mod's chat.
- The Server tab's public-address watcher pushes "Your Cubeon server is
  public at <address>" into Minecraft chat once per resolved address.
- Host now gets "Your world is live - <peer> has been invited" in chat at
  worldgate_set; the password itself is never echoed (streamer safety).
- Joiner already got the address in chat via the (kept) handoff notice.

## Commits
The whole backlog was committed (user asked to "push it fully"):
- 4f7af46 mod: friends->client rename (prior agents' work)
- ca7cd05 launcher: accumulated prior sessions
- fe7f8f9 this fix. Working tree CLEAN - HEAD == the tested disk state, so a
  fresh clone finally builds the mod.

## Verification
- test_friends_service 252/252 (+12: relay-stay/no-redirect/transport-untouched,
  address-in-chat, old-host handoff compat, notify_active seam)
- mod_bridge 119, mod_compile clean, friends 48, ui_smoke 112, production 13.

## Note for next agent
If a TRUE "world behind a public address" is ever wanted, the spigot plugin
cannot do it - it needs a proxy in front of the LAN port (e.g. a managed
Velocity/Connect-standalone). That is the playit-dance the repo escaped;
scope it deliberately, don't bolt it on.
