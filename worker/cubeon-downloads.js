/**
 * Cubeon download proxy - Cloudflare Worker (free tier).
 *
 * The repository is PRIVATE, so GitHub answers every anonymous release-asset
 * request with an auth wall (and signed asset URLs minted from a logged-in
 * session expire within the hour). This Worker is the middle piece: it holds
 * one GitHub token as a secret and streams the latest release's installer
 * files straight to anyone, with no GitHub page and no expiry.
 *
 *   GET /windowsdownload  -> streams Cubeon-Windows-x64-Setup.exe
 *   GET /linuxdownload    -> streams Cubeon-x86_64.AppImage
 *   GET /linuxdeb         -> streams the .deb for the current APP_VERSION
 *   GET /linuxsetup       -> streams Cubeon-Linux-x86_64-Setup.sh
 *   GET /health           -> plain-text OK, for debugging by hand
 *
 * Bindings required: a secret GITHUB_TOKEN with read access to the repo
 * (read-only is enough):
 *
 *   npx wrangler deploy -c wrangler-downloads.toml
 *   echo "<token>" | npx wrangler secret put GITHUB_TOKEN -c wrangler-downloads.toml
 *
 * Quota: every request WOULD cost one GitHub API call to resolve the latest
 * release (5000/hour on a token) - the asset bytes themselves come off
 * GitHub's CDN and never pass through the API. The vercel.json routes point
 * at this Worker, so the token never reaches a browser.
 *
 * ABUSE PROTECTION (2026-10-17). This Worker is public by design - the website
 * and the launcher both hand its URL out, and the URL is in this repo - so
 * "who can call it" is everyone, fork or not. The scarce resource an attacker
 * could burn was the TOKEN'S hourly API budget: about 1.4 requests/second for
 * an hour used to take the download buttons down for every user. Two
 * independent gates now stand in front of it:
 *
 *   1. The release lookup is served from the edge cache for
 *      RELEASE_CACHE_SECONDS, so a flood costs ZERO GitHub API calls. This is
 *      the one that matters - it makes the token's quota unbunable.
 *   2. A per-IP throttle: an in-isolate limiter that always runs, plus the
 *      RATE_LIMITER binding (Cloudflare's Rate Limiting) when bound, which
 *      makes it per-POP. See wrangler-downloads.toml.
 *
 * The cache protects the TOKEN, not this Worker's request budget: a flood still
 * costs one request each from the account-wide 100k/day that all five Workers
 * share, so gate 2 is what keeps a flood from taking friend requests, skins and
 * signups down with it for the rest of the UTC day.
 *
 * A missing or broken edge cache degrades to the old behaviour (one API call
 * per request), never to an error: a cache is an optimisation, and a download
 * must not fail because the cache had a bad day.
 */

const REPOSITORY = "Shadow-457/Cubeon";

// Routes -> release asset names. Keep in sync with the ROUTES list in
// web/assets/site.js (which counts presses) and web/vercel.json.
//
// The .deb is the one asset whose name carries the app version
// (packaging/build_deb.py names it cubeon_<APP_VERSION>_amd64.deb), so it is
// declared as a PREFIX_MATCH rather than a literal. Pinning the literal here
// meant the two sides drifted: packaging stopped hardcoding "1.0.0" and began
// emitting the real version, while this map kept asking GitHub for
// cubeon_1.0.0_amd64.deb, so /linuxdeb 404'd on every request.
const FILES = {
  "/windowsdownload": "Cubeon-Windows-x64-Setup.exe",
  "/linuxdownload": "Cubeon-x86_64.AppImage",
  "/linuxdeb": { prefix: "cubeon_", suffix: "_amd64.deb" },
  "/linuxsetup": "Cubeon-Linux-x86_64-Setup.sh",
};

const jsonHeaders = {
  "User-Agent": "cubeon-downloads",
  "Accept": "application/vnd.github+json",
};

/**
 * Newest asset matching prefix + suffix, or undefined.
 *
 * Used for the .deb, whose name embeds the app version
 * (cubeon_1.1.2_amd64.deb) and therefore cannot be pinned here without
 * drifting out of sync with packaging/build_deb.py. A release may carry more
 * than one build of it, so the version in the middle is compared
 * NUMERICALLY per segment - "1.0.10" must beat "1.0.9", which a plain string
 * sort gets wrong. Anything that doesn't parse as a version sorts last, so a
 * well-formed asset always wins over a malformed one.
 */
function pickLatestPrefixed(assets, { prefix, suffix }) {
  const matches = [];
  for (const asset of assets) {
    const name = asset && asset.name;
    if (typeof name !== "string") continue;
    if (!name.startsWith(prefix) || !name.endsWith(suffix)) continue;
    const version = name.slice(prefix.length, name.length - suffix.length);
    if (!version) continue;
    matches.push({ asset, version, parts: version.split(".").map(Number) });
  }
  if (!matches.length) return undefined;
  matches.sort((a, b) => {
    const len = Math.max(a.parts.length, b.parts.length);
    for (let i = 0; i < len; i++) {
      const av = a.parts[i];
      const bv = b.parts[i];
      // A missing segment counts as 0, so "1.0" == "1.0.0".
      const cmp = (Number.isFinite(av) ? av : 0) - (Number.isFinite(bv) ? bv : 0);
      if (cmp !== 0) return cmp;
    }
    // Equal versions: fall back to the raw string so the choice is stable.
    return a.version < b.version ? -1 : a.version > b.version ? 1 : 0;
  });
  return matches[matches.length - 1].asset;
}

// ------------------------------------------------------------- abuse gates ---

// How long a resolved release is served from the edge cache. Five minutes is a
// deliberate compromise: long enough that a flood cannot reach GitHub at all,
// short enough that a release published during a download surge shows up
// promptly. It also bounds the token's spend to at most 12 API calls an hour,
// whatever the traffic.
//
// The streamed installer carries the same max-age deliberately: metadata and
// bytes going stale on the same clock means a browser can never pair a fresh
// asset URL with a stale body.
const RELEASE_CACHE_SECONDS = 300;

// A synthetic cache key. This is an internal object, not a client URL, so it
// must not be able to collide with a real request.
const RELEASE_CACHE_KEY = "https://cubeon-downloads.internal/latest-release.json";

/** The Workers edge cache, or null where there isn't one (Node, tests). */
function edgeCache() {
  try {
    return typeof caches !== "undefined" && caches.default ? caches.default : null;
  } catch {
    return null;
  }
}

/**
 * The latest release's assets - edge cache first, GitHub second.
 *
 * Only the three fields a route needs are kept (`name`, `url`, `size`), so the
 * cached object is a few kB and carries nothing about the private repo beyond
 * the asset names this file already lists by hand.
 *
 * Returns null when GitHub can't be reached or answers without assets. A
 * FAILURE is deliberately not cached, so the next request retries instead of
 * pinning an outage for five minutes.
 */
export async function latestRelease(env) {
  const cache = edgeCache();
  const key = new Request(RELEASE_CACHE_KEY);

  if (cache) {
    try {
      const hit = await cache.match(key);
      if (hit) {
        const cached = await hit.json();
        if (cached && Array.isArray(cached.assets)) return cached;
      }
    } catch {
      // A misbehaving cache costs one API call, never a failed download.
    }
  }

  const release = await fetch(
    `https://api.github.com/repos/${REPOSITORY}/releases/latest`,
    { headers: { ...jsonHeaders, Authorization: `Bearer ${env.GITHUB_TOKEN}` } }
  );
  if (!release.ok) return null;

  const data = await release.json();
  const assets = (Array.isArray(data.assets) ? data.assets : [])
    .filter((a) => a && typeof a.name === "string")
    .map((a) => ({ name: a.name, url: a.url, size: a.size }));

  const payload = { assets };
  if (cache && assets.length) {
    try {
      await cache.put(key, new Response(JSON.stringify(payload), {
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": `max-age=${RELEASE_CACHE_SECONDS}`,
        },
      }));
    } catch {
      // Not cached: still a correct answer, just a costlier one.
    }
  }
  return payload;
}

// Requests per window, per IP, for the download routes. Far above honest use:
// a person grabs one or two installers, and a re-download or a browser retry is
// rare. There is no write and no token cost per request here, so the only thing
// this protects is the account's shared 100k/day Worker request budget - which
// the other four Workers draw on too (see wrangler-downloads.toml).
const DOWNLOAD_RATE = { max: 30, windowMs: 60_000 };

// Fallback limiter state. Module scope, so it lives as long as the isolate.
const fallbackRL = new Map();

/**
 * Sliding-window limiter over {max} requests per {windowMs} for one key.
 * Mirrors cubeon-skins.js fallbackAllow (same window semantics), kept local
 * because each Worker is deployed on its own.
 */
function fallbackAllow(map, key, max, windowMs, now) {
  const hits = (map.get(key) || []).filter((t) => now - t < windowMs);
  hits.push(now);
  map.set(key, hits);
  return hits.length <= max;
}

/**
 * The per-IP throttle. Two gates, and EITHER may refuse: the RATE_LIMITER
 * binding, which is the one that reliably caps sustained abuse (it converges
 * late - roughly a hundred requests before the first refusal, measured on the
 * waitlist Worker 2026-10-17), and the in-isolate fallback, which is
 * best-effort and may be inert live because requests for a cold Worker need not
 * share an isolate. A binding that throws degrades to the fallback, never to an
 * error.
 */
async function throttle(request, env) {
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  if (env.RATE_LIMITER) {
    const rl = await env.RATE_LIMITER.limit({ key: ip }).catch(() => null);
    if (rl && rl.success === false) return throttled();
  }
  if (!fallbackAllow(fallbackRL, ip, DOWNLOAD_RATE.max, DOWNLOAD_RATE.windowMs, Date.now())) {
    return throttled();
  }
  return null;
}

function throttled() {
  return new Response("too many requests", {
    status: 429,
    headers: { "Retry-After": "60" },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return new Response("cubeon-downloads ok");
    }

    const spec = FILES[url.pathname];
    if (!spec || request.method !== "GET") {
      return new Response("not found", { status: 404 });
    }

    // Throttle before the token is even looked at, so a flood costs the
    // cheapest possible rejection.
    const limited = await throttle(request, env);
    if (limited) return limited;

    if (!env.GITHUB_TOKEN) {
      return new Response("server misconfigured: no GITHUB_TOKEN", { status: 500 });
    }

    // One edge-cached lookup, however many people are pressing Download.
    const release = await latestRelease(env);
    if (!release) {
      return new Response("release unavailable", { status: 502 });
    }
    const assets = release.assets;
    const asset = typeof spec === "string"
      ? assets.find((a) => a.name === spec)
      : pickLatestPrefixed(assets, spec);
    if (!asset) {
      return new Response(`no matching asset for ${url.pathname} in the latest release`, { status: 404 });
    }

    // Accept: application/octet-stream makes GitHub answer the asset with a
    // redirect to the real bytes; follow it and stream them on.
    const file = await fetch(asset.url, {
      headers: {
        "User-Agent": "cubeon-downloads",
        "Accept": "application/octet-stream",
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      },
      redirect: "follow",
    });
    if (!file.ok || !file.body) {
      return new Response("asset unavailable", { status: 502 });
    }

    return new Response(file.body, {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": `attachment; filename="${asset.name}"`,
        "Content-Length": String(asset.size),
        "Cache-Control": `public, max-age=${RELEASE_CACHE_SECONDS}`,
      },
    });
  },
};
