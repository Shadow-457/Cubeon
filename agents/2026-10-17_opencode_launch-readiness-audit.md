# Launch-readiness audit before making the repo public (2026-10-17)

The user asked, roughly: "I can make it public and tell my Discord members now -
there's no bug, right?" They wanted a go/no-go, not reassurance.

## What I actually checked (and what came back)

**Credentials - clean, and I looked properly:**
- Current tree: no tokens/keys/passwords. Every hit for "password"/"token" is
  code that *handles* them (worldgate, gate.py, the CurseForge key dialog) or a
  test fixture (`ruby-secret-1234...`).
- **Whole history**: `git log -p --all` = 495,336 patch lines, grepped for
  `ghp_`, `github_pat_`, `gho_`, `sk-`, AWS `AKIA`, `$2a$10$` (CurseForge keys),
  private-key headers, Discord webhooks, and any `secret|token|api_key = "<16+>"`
  assignment → nothing but test fixtures.
- Workers keep their tokens as Cloudflare secrets (`env.GITHUB_TOKEN`), never in
  the file. `wrangler` tomls carry only names.
- Tree hygiene: 499 tracked files, no venv/dist/node_modules/`__pycache__`.
- Apache-2.0 LICENSE + NOTICE ("Copyright 2026 Hamza Shahbaz") are present, so a
  public repo is not accidental-looking.
- The commit email is a non-issue: `gh api` over the user's 14 existing PUBLIC
  repos shows `hamza1tan123456@gmail.com` ×232 and `Hamza.457.Shahbaz@gmail.com`
  ×6 already published. Nothing new leaks.

**The one real finding - in history, not the tree:** the deleted Wrangler cache
files `worker/.wrangler/cache/cf.json` and `wrangler-account.json` (removed in
`fe76bc5`) are still reachable. They contain the Cloudflare account ID, the
account name (an email), and `cf.json` carries the user's city-level location
(Lahore, lat/long, postal code) plus TLS handshake material. **No API token.**
Told the user; they chose to publish as-is rather than rewrite history (which
would have orphaned tags v1.2.0-v1.2.4 and needed the releases recreated).

## The bug question, answered honestly

- No known user-facing bug. Everything verified tonight works: site 200, the
  Windows/Linux buttons stream real assets, v1.2.4 published with six assets,
  the update nag points at the site.
- **Windows is the least-verified path and most members are on Windows.** The
  `Startup tests (Windows)` CI job is red, but I read the log instead of
  assuming: it dies in the *test harness* - `AttributeError: 'ProactorEventLoop'
  object has no attribute '_ssock'` (a Unix selector-loop attribute) and the
  socket ban killing flet's own local client connect. 22/25 startup and 27/28
  window checks pass there. So it is a harness gap, not evidence of an app bug -
  but it also means a green run there would not prove the app works.
- The custom frame is default-OFF and unverified on real Windows (its own
  docstring says so), so it cannot bite a mass launch.

## What I left behind for them

- **`docs/WINDOWS_SMOKE_TEST.md`** (new, tracked): the numbered pass to run on a
  real Windows box before announcing. Includes the unsigned-build SmartScreen
  prompt (already covered by the site's download step 1 - point members there),
  the hidden-start window reveal, the version check via exe Properties (the UI
  does not display the version anywhere), the update-nag re-check, and the
  opt-in frame. Referenced from `docs/SIMPLE_OWNER_GUIDE.md` and the module map.
- The module map now records *why* the Windows CI job is red, so a future agent
  does not "fix" it by trusting a green run.
- Pushing the doc minted **v1.2.5**, which hands them a live update nag to test
  against with the build they install.

## Still open (their side)

- Make the repo public themselves (I did not flip that switch).
- Run the checklist on Windows.
- If they want the location/account-id gone from history later, it is a rewrite
  plus tag/release recreation - possible, just not free.
