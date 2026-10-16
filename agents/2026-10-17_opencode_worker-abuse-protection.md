# Protecting the Workers: "can a fork use my Cloudflare Worker?"

The user asked whether anyone who forks the repo can use their Cloudflare
Worker, and asked me to protect it if so. Short answer: **a fork can't touch the
account, but it never needed to** — the Worker URLs are hardcoded in the shipped
launcher, so they are public to everyone. The protection therefore had to go
*into the Workers*, and the audit found one with a real, cheap-to-trigger DoS.

## The audit

Five Workers, audited in order of what an attacker could cost. First, the
threat model, because it decides where the fix belongs:

- Forking a repo does **not** grant access to the owner's Cloudflare account,
  secrets, or deploy rights. A forker deploying the Worker deploys to **their
  own** account.
- But `cubeon/csl.py`, `cubeon/friends.py`, `cubeon/invites.py` and
  `web/vercel.json` all hardcode `*.hamza-457-shahbaz.workers.dev`, and they
  have to: a client-side launcher has nowhere to hide a URL. So the exposure is
  "anyone with the URL", fork or not.
- I confirmed all five are live (`/health` returns each Worker's own text, not
  a workers.dev 404): skins, invites, friends, downloads, waitlist.

Already sound, so left alone: `cubeon-skins.js`, `cubeon-invites.js`,
`cubeon-friends.js`. All three prove ownership with a **per-machine secret**
(SHA-256 at rest, constant-time compare) and carry write budgets; the friends
Worker adds a sliding-window limiter (per IP pre-auth, and per action) and sends
the secret in the first WebSocket frame rather than the URL, so it never lands
in a request log. Note the IP limiter lives in `cubeon-friends.js` - the skins
Worker only *mirrors* its constant-time compare, so do not assume the skins
Worker is throttled.

### The bug: `cubeon-downloads.js` could be knocked over for everyone

It is the only Worker holding a credential (a read-only GitHub token), and it
spent **one API call per request** against a 5000/hour budget, with
`Cache-Control: no-store` and no throttle:

- ~1.4 requests/second sustained for an hour exhausts the token's quota;
- after that **every** user's download button 502s until the hour rolls over;
- `no-store` meant even a *legitimate* second press cost another call.

That is a whole-service outage for the cost of a `while` loop, triggerable by
anyone who has ever loaded the site. This is what the user was worried about,
even if the mechanism is not the one they guessed.

### The fix (`cubeon-downloads.js`)

1. **Edge-cache the release lookup** in `caches.default` for
   `RELEASE_CACHE_SECONDS = 300`. This is the fix that matters: a flood now
   costs **zero** GitHub API calls, so the quota cannot be burned at all. It
   also caps the token's spend at ~12 calls/hour regardless of traffic.
2. **Optional per-IP `RATE_LIMITER`** binding, matching `cubeon-invites.js`'s
   contract (absent = unthrottled, broken = unthrottled, never an error). The
   opt-in is a commented `[[unsafe.bindings]]` block in `wrangler-downloads.toml`.
3. Dropped `no-store` for `public, max-age=300` — the same clock as the
   metadata, so a browser can never pair a fresh asset URL with a stale body,
   and repeat presses cost nothing.

Deliberate design constraints, so the next agent doesn't "simplify" them away:

- **Only `name`/`url`/`size` are cached.** The rest of the release JSON (notes,
  asset ids) is dropped at the `.map()`, so the cache holds nothing about the
  private repo beyond asset names the file already lists by hand.
- **A failure is never cached** (`if (cache && assets.length)`), or one bad
  minute at GitHub would pin a 5-minute outage.
- **Both gates degrade, never error.** `edgeCache()` returns `null` off-Workers
  and the limiter is wrapped in `.catch(() => null)`. A protection that turns
  into an outage when it misbehaves is worse than no protection.

### Also hardened: `cubeon-waitlist.js`

The only Worker whose writes carry **no identity** (it is a public signup form),
and its tally shares the KV namespace. A script posting made-up addresses could
spend the free tier's account-wide ~1k writes/day and take every *real* signup
down with it. Added the same optional `RATE_LIMITER`, gated **inside the POST
branch above the dispatch**.

### Two things I found that were not asked for

Reported, not silently swallowed:

1. **`tools/test_csl.py` was not hermetic.** It sets its own temp `HOME`, but
   `CUBEON_GAME_DIR` *wins over HOME* in `cubeon/paths.py` — and CI sets that
   variable for the whole job. So the test wrote and **consumed** ExtraList files
   in the shared real game dir instead of its sandbox. Fixed by popping
   `CUBEON_GAME_DIR` before importing; verified both with and without it set.
2. **`worker/test-friends-metadata.mjs` was stale.** Commit `c28b8f0` ("shorten
   Cubeon IDs") changed `UID_WIDTH` to 8, but the test still asserted
   `"000000000001"`. It fails at `HEAD`, and **nothing in CI runs the `.mjs`
   tests**, so it rotted invisibly. Fixed the four assertions.

## Verification

- `node worker/test-downloads.mjs` — **new, 26 checks, all pass.** Stubs
  `globalThis.caches` and `globalThis.fetch` (possible precisely because
  `edgeCache()` returns null off-Workers). The load-bearing one: **100 rapid
  downloads → exactly 1 GitHub API call**.
- `worker/test-waitlist.mjs` — 6 new checks (throttled → 429 with zero KV
  writes and the address never stored; broken limiter → still accepts; no
  binding → unchanged).
- All other `.mjs` Worker tests: skins, invites, friends-rooms, friends-sql
  pass. `test-friends-metadata.mjs` now passes too (was failing before my change).
- `tools/test_web_download_count.py` — **89 checks** (was 76), including the new
  §4b source pins.** All Python Worker tests pass.** `tools/test_csl.py` passes
  hermetically both ways.
- **Negative controls, because a source pin that cannot fail is theatre.** I
  mutated the code and re-ran: a 5s cache TTL, deleting the cache read/write,
  moving the throttle below the token check, and moving the waitlist gate below
  the dispatch each produced exactly the intended FAIL. **The first version of
  the waitlist pin passed with the gate moved below the dispatch** — a plain
  `x in source` check — which is why the committed version uses
  `_before()`/`_post_branch()` and slices the POST branch.
- Full gate: `tools/test_mega_smoke.py --suites` → **44 passed, 1 failed**, the
  same known non-hermetic `test_mod_store.py` (24/3) as the baseline.

## Honest caveats

- **No live deploy was tested.** The edge cache and the rate limiter only do
  anything in the Workers runtime; I proved them with stubs, and the pins prove
  the source, but nothing has hit the real cache.
- The rate limiter must be **uncommented and re-deployed** to take effect. Until
  then the cache alone is doing the work — which is the intended order of
  importance, since the cache is what makes the quota unbunable.
- A fork's launcher still points at the upstream URLs unless it sets
  `CUBEON_SKIN_API` / `CUBEON_FRIENDS_API` / `CUBEON_INVITE_API`. I added the
  missing `CUBEON_SKIN_API` for parity, and documented the rest in
  `worker/README.md`, but I cannot force a fork to use it.
- `worker/README.md`'s status table claimed "Three Workers" and called the
  friends Worker "not deployed yet"; both were stale (it is live), so I corrected
  the table to all five.
