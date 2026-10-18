# The update nag sent people to a door only we can open (2026-10-17)

## What the user said
"why the get it in cubeon the update notification takes user to git release? it
should take to cubeon.ylet.online new url"

## What was wrong
`updater.check_for_updates()` returned `data["html_url"]` from the releases API,
so the startup snackbar's **Get it** opened

    https://github.com/Shadow-457/Cubeon/releases/tag/vX.Y.Z

That repo is **private**. For anyone who isn't us that page is an auth wall or a
404, so the one button whose entire job is "go get the new version" was a dead
end for every real user. The site's own buttons were the only thing that worked
(they go through the downloads worker, where the token stays server-side).

## The fix
- `cubeon/updater.py`: new `DOWNLOAD_URL = "https://cubeon.ylet.online/download"`
  (with a comment saying why NOT the release page). `check_for_updates()` always
  returns it, whatever the feed advertises. Overridable for staging with the
  `download_url` argument or `CUBEON_DOWNLOAD_URL`, mirroring `CUBEON_UPDATE_FEED`.
  `check_in_background()` forwards it. The API endpoint itself is unchanged.
- `main.py`: the snackbar handler is `_open_download` now, not `_open_release`,
  with a one-line comment about the auth wall.

## Verified
- `tools/test_net.py` (46/0): the reported url equals `updater.DOWNLOAD_URL`, it
  is NOT the feed's `html_url`, and both overrides work.
- `python3 tools/test_mega_smoke.py --static` 16/0 and `--suites` **50 passed, 0
  failed** (main.py's startup path is one of the things the suites build).
- Checked the destination before pointing at it, rather than trusting the name:
  `https://cubeon.ylet.online/download` answers **200** and says **"Version
  1.2.3"**, and `/windowsdownload` + `/linuxdownload` both end up streaming a
  real asset from the worker (curl only stopped because I capped it, exit 28
  mid-download - i.e. data was flowing).
- Pushed `2dd658f`, so this ships in **v1.2.4**.

## Durable bits (in the module-map, not just here)
- The updater section now names `DOWNLOAD_URL` and why it exists; the "Follow-up
  14: private repo + packaging scripts" section carries the full trap ("never
  send users to the release page of a private repo").
- `docs/SIMPLE_OWNER_GUIDE.md` step 4 now says the click goes to the site.

## Loose thread for whoever is next
The site updates its stamped version when `main` moves, and the release job's
bump commit says `[skip ci]`. Vercel is documented to skip builds for commits
with that token in the message, yet the live page read "Version 1.2.4" minutes
after exactly such a commit landed - so it is deploying them for now (checked
twice, on the 1.2.3 and 1.2.4 bumps). If the site is ever seen advertising a
stale version, that is the first thing to check, and the fix is Vercel's
"ignored build step" setting rather than the commit message.
