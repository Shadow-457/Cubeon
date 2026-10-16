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
 * Quota: every request costs ONE GitHub API call to resolve the latest
 * release (5000/hour on a token) - the asset bytes themselves come off
 * GitHub's CDN and never pass through the API. The vercel.json routes point
 * at this Worker, so the token never reaches a browser.
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

// --- Owner notifications (2026-10-16) --------------------------------------
// A short one-off broadcast from the owner to every running launcher. The
// launcher polls GET /notify at startup and shows the entry ONCE (it keeps the
// `ts` it last displayed in config), styled like the seasonal greeting.
//
//   POST /notify   Authorization: Bearer <NOTIFY_TOKEN>
//                  {"headline": "...", "content": "...", "url": "https://..."}
//   GET  /notify   -> {"headline","content","url","ts"}  |  204 when unset
//
// Storage is the KV namespace bound as CUBEON_NOTIFY - the same pattern the
// cubeon-skins Worker uses for its SKINS namespace. NOTIFY_TOKEN is a Worker
// SECRET: it lives only inside Cloudflare, is never in this repo, and cannot
// be read back out of the Worker:
//
//   echo "<long-random-token>" | npx wrangler secret put NOTIFY_TOKEN -c wrangler-downloads.toml
//
// An unauthenticated POST is rejected with 401 BEFORE anything is read or
// written, and the published bytes are capped, because GET /notify is public.
const NOTIFY_KEY = "latest";
const NOTIFY_MAX = 4000;

async function handleNotify(request, env) {
  const kv = env.CUBEON_NOTIFY;

  if (request.method === "GET") {
    // 204 (not 404) when nothing was ever published: the launcher treats any
    // non-200 as "nothing to show" and moves on.
    if (!kv) return new Response(null, { status: 204 });
    const raw = await kv.get(NOTIFY_KEY);
    if (!raw) return new Response(null, { status: 204 });
    return new Response(raw, {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }

  if (request.method !== "POST") {
    return new Response("method not allowed", {
      status: 405,
      headers: { Allow: "GET, POST" },
    });
  }

  // Owner only. The expected token is a Worker secret; `got` comes from the
  // Authorization header so the token never lands in a URL, a log or a referer.
  const expected = env.NOTIFY_TOKEN;
  const got = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!expected || !got || got !== expected) {
    return new Response("unauthorized", { status: 401 });
  }
  if (!kv) {
    return new Response("server misconfigured: no CUBEON_NOTIFY binding", {
      status: 501,
    });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return new Response("bad json", { status: 400 });
  }
  const headline = String(body?.headline ?? "").trim();
  const content = String(body?.content ?? "").trim();
  if (!headline || !content) {
    return new Response("headline and content are required", { status: 400 });
  }
  if (headline.length > NOTIFY_MAX || content.length > NOTIFY_MAX) {
    return new Response("too long", { status: 413 });
  }
  const entry = {
    headline,
    content,
    // Only an absolute http(s) url survives, so a stored entry can never feed
    // the launcher a file:// or javascript: link.
    url:
      typeof body?.url === "string" && /^https?:\/\//i.test(body.url)
        ? body.url
        : null,
    ts: Date.now(),
  };
  await kv.put(NOTIFY_KEY, JSON.stringify(entry));
  return new Response(JSON.stringify({ ok: true, ts: entry.ts }), {
    headers: { "Content-Type": "application/json" },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return new Response("cubeon-downloads ok");
    }

    if (url.pathname === "/notify") {
      return handleNotify(request, env);
    }

    const spec = FILES[url.pathname];
    if (!spec || request.method !== "GET") {
      return new Response("not found", { status: 404 });
    }
    if (!env.GITHUB_TOKEN) {
      return new Response("server misconfigured: no GITHUB_TOKEN", { status: 500 });
    }

    // The asset lookup is the only metered call (5000/hour); bytes stream
    // from the CDN afterwards.
    const release = await fetch(
      `https://api.github.com/repos/${REPOSITORY}/releases/latest`,
      { headers: { ...jsonHeaders, Authorization: `Bearer ${env.GITHUB_TOKEN}` } }
    );
    if (!release.ok) {
      return new Response("release unavailable", { status: 502 });
    }
    const data = await release.json();
    const assets = Array.isArray(data.assets) ? data.assets : [];
    const asset = typeof spec === "string"
      ? assets.find((a) => a && a.name === spec)
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
        "Cache-Control": "no-store",
      },
    });
  },
};
