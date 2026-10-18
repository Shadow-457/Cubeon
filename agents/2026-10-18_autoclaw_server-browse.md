# Server Browse - a live public-server browser in the Servers tab

**Date:** 2026-10-18 · **Repo:** products/cubeon · **Status:** code + tests
done, all suites green (browse 59, mega 23 incl. the new builder-mounted
check, fuzz 13 x3 runs, ui_smoke 260, startup 25).

## What the user asked for
"An option in a browse area in Servers where we can use a free endpoint to
get all the servers, a search bar, sorted most playing to none playing,
showing tags (cracked, premium...), what it does, clean and good-looking UI."

## What they got, and the one honest limitation
- New module `cubeon/server_browse.py` (data layer) + `ui/server_browse_tab.py`
  (the view) + a fourth chip in the Servers group ("Browse", telescope icon).
- 18 curated famous servers, each with live player counts/MOTD/version from
  free keyless status APIs (minetools -> mcstatus.io -> mcsrvstat.us fallback),
  sorted most-playing-first, tag chips (cracked/premium/genres), a blurb per
  server, icon via the shared disk cache, click-the-address-to-copy, a manual
  Refresh (parallel, TTL-respecting), and an address-lookup (type a host,
  press Enter) that pins a live status row on top.
- **The limitation, measured not assumed: no free keyless API LISTS servers.**
  List sites are Cloudflare-walled; the old open dataset repo is 404. So the
  catalogue is curated data + live status, which still satisfies "most playing
  to none playing" honestly (a dead famous server sinks live). Editors add a
  server by appending to CATALOGUE - tags become chips automatically.
- JOIN launches the selected profile straight into the server via
  `core.launch_game(server_address=, server_port=)` - the same path friends
  uses. No version selected = snackbar, never a dead click.

## Debugging story (the reason this note is long)
1. First runtime crash (user-pasted traceback): `ft.padding.symmetric` does
   not exist in Flet 0.86 - it is `ft.padding.Padding.symmetric(...)` (same
   for `ft.margin.only` -> `ft.Margin.only`). The mega suite's static scan
   caught the margin one; the padding one slipped because `Text.content_padding`
   only explodes when the TextField is BUILT, and `_ensure_tab` swallows lazy
   builder exceptions into a printed traceback (by design). Same family
   afterwards: `ft.alignment.center` -> `ft.Alignment.CENTER`, and
   `ft.Text(ellipsis=True)` does not exist -> plain `max_lines=1`.
2. Closed the harness hole for good: test_mega_smoke now builds a FRESH
   driver, opens each server screen and asserts its title Text is mounted
   ("lazy tab builders really built their views"). app_driver.NAV_KEYS gained
   `server_browse`, and _fuzz_common.install_safe_stubs cans
   `server_browse._fetch_status`/`get_status` (canned 123-player answer) so
   the fuzz corpus can click Browse offline and deterministically.
3. Real logic bugs my own tests caught before they shipped:
   `server_browse.get_status` stored TWO different memory-cache shapes
   (tuple vs packed dict) -> KeyError on the second call; `_mcstatus` crashed
   on mcstatus.io's list-shaped `motd.clean`; `sort_by_status` trusted a
   phantom `offline` key (the shared shape says `online: False`); the
   Enter-submit handler originally passed a fake event dict (now
   `_on_search(e=None, *, submit=False)` + a real `_on_submit` wrapper).
4. JOIN safety: my first draft imported `cubeon.launch.launch_game` directly -
   which BYPASSES the `core` facade the harness stubs, meaning a fuzzer-fired
   JOIN could spawn a real Minecraft. Now `core.launch_game` only. Worth
   remembering: any new side-effecting path must go through the facade.

## Baton
- The UI is verified headless (rows build, handlers fire, statuses paint);
  nobody has eyeballed it in the real window yet - if the spacing of the
  tag chips or the pinned lookup row feels off, that's pure CSS-level polish
  in `_build_row`/render.
- CATALOGUE deliberately excludes ping-hostile servers (TheArchon, DatBlock,
  VeltPvP): they answer 403/timeout to datacenter IPs and would lie "offline".
  If someone asks "where is X", check whether X pings before adding it.
- The earlier FastClient JVM-comparison baton item is still open and untouched.
