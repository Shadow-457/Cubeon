/**
 * Tests for worker/cubeon-downloads.js - run with:
 *
 *     node worker/test-downloads.mjs
 *
 * Needs nothing installed: no wrangler, no npm, no Cloudflare account, and no
 * network. The Worker is imported directly and handed a stub `caches` and a
 * stub `fetch`, which works because the module reaches for the edge cache
 * through `caches.default` and for GitHub through the global `fetch`.
 *
 * The checks that matter most are the COST ones. This Worker holds a secret
 * GitHub token whose API budget is 5000 calls/hour shared by every user of
 * every download button, and the endpoint is public, so "how many API calls
 * does a hostile client cost me" is the security property under test here -
 * not the routing, which is the easy part.
 */
import worker from "./cubeon-downloads.js";

// --- Stub edge cache: honours max-age the way the real Cache API does --------
function makeCache({ enabled = true } = {}) {
  const entries = new Map();
  return {
    enabled,
    entries,
    async match(key) {
      if (!enabled) throw new Error("cache is having a bad day");
      const record = entries.get(key.url);
      if (!record) return null;
      if (record.expires <= Date.now()) {
        entries.delete(key.url); // expired reads as absent, like the real thing
        return null;
      }
      return new Response(record.body, {
        headers: { "Content-Type": "application/json" },
      });
    },
    async put(key, response) {
      const maxAge = /max-age=(\d+)/.exec(response.headers.get("Cache-Control") || "");
      const text = await response.text();
      entries.set(key.url, {
        body: text,
        expires: Date.now() + (maxAge ? Number(maxAge[1]) : 0) * 1000,
      });
    },
  };
}

// --- Stub GitHub: counts API calls, serves fake asset bytes ------------------
function installWorld({ cache = makeCache(), releaseFails = false } = {}) {
  const world = { apiCalls: 0, assetFetches: 0, lastAuth: null, cache };
  globalThis.caches = { default: cache };
  globalThis.fetch = async (url, init = {}) => {
    const href = typeof url === "string" ? url : url.url;
    if (href.includes("api.github.com/repos/")) {
      world.apiCalls++;
      world.lastAuth = init.headers && init.headers.Authorization;
      if (releaseFails) return new Response("nope", { status: 500 });
      return Response.json({
        tag_name: "v1.0.0",
        // Extra fields on purpose: they must NOT end up in the cache.
        body: "private release notes",
        assets: [
          { name: "Cubeon-Windows-x64-Setup.exe", url: "https://cdn.test/win", size: 11, id: 1 },
          { name: "Cubeon-x86_64.AppImage", url: "https://cdn.test/linux", size: 12, id: 2 },
          { name: "Cubeon-Linux-x86_64-Setup.sh", url: "https://cdn.test/sh", size: 13, id: 3 },
          { name: "cubeon_1.0.9_amd64.deb", url: "https://cdn.test/deb9", size: 14, id: 4 },
          { name: "cubeon_1.0.10_amd64.deb", url: "https://cdn.test/deb10", size: 15, id: 5 },
          { name: "cubeon_bad.deb", url: "https://cdn.test/debbad", size: 16, id: 6 },
        ],
      });
    }
    world.assetFetches++;
    return new Response("installer-bytes", { status: 200 });
  };
  return world;
}

const env = { GITHUB_TOKEN: "ghp_test_token" };

let failures = 0;
function check(label, ok, extra = "") {
  console.log(`${ok ? "  ok  " : " FAIL "} ${label}${extra ? "  " + extra : ""}`);
  if (!ok) failures++;
}

const get = (path, init) =>
  worker.fetch(new Request("https://cubeon-downloads.test" + path, init), env);

const fresh = (opts) => {
  const world = installWorld(opts);
  // Each case starts with an empty cache and a fresh call counter.
  return world;
};

// ---------------------------------------------------------------- routing ---

let world = fresh();
let res = await get("/health");
check("health answers without touching GitHub",
  res.status === 200 && world.apiCalls === 0, `status ${res.status}`);

world = fresh();
res = await get("/windowsdownload");
check("the Windows route streams the installer",
  res.status === 200 && (await res.text()) === "installer-bytes", `status ${res.status}`);
check("it names the file for the browser",
  res.headers.get("Content-Disposition") ===
    'attachment; filename="Cubeon-Windows-x64-Setup.exe"',
  res.headers.get("Content-Disposition") || "");
check("it forwards the real size",
  res.headers.get("Content-Length") === "11", res.headers.get("Content-Length") || "");

world = fresh();
res = await get("/linuxdownload");
check("the Linux route works too", res.status === 200, `status ${res.status}`);

world = fresh();
res = await get("/linuxsetup");
check("the setup-script route works", res.status === 200, `status ${res.status}`);

world = fresh();
res = await get("/linuxdeb");
check("the .deb route picks the numerically newest build (1.0.10 > 1.0.9)",
  res.headers.get("Content-Disposition") ===
    'attachment; filename="cubeon_1.0.10_amd64.deb"',
  res.headers.get("Content-Disposition") || "");

world = fresh();
res = await get("/nope");
check("an unknown route is a 404 and costs nothing",
  res.status === 404 && world.apiCalls === 0, `status ${res.status}`);

world = fresh();
res = await get("/windowsdownload", { method: "POST" });
check("a non-GET is a 404 and costs nothing",
  res.status === 404 && world.apiCalls === 0, `status ${res.status}`);

world = fresh();
res = await worker.fetch(
  new Request("https://cubeon-downloads.test/windowsdownload"), {});
check("no GITHUB_TOKEN is a 500, not a crash",
  res.status === 500, `status ${res.status}`);

world = fresh();
res = await get("/windowsdownload");
check("the token is presented to GitHub as a Bearer header",
  world.lastAuth === "Bearer ghp_test_token", String(world.lastAuth));

// ----------------------------------------------------- the cost property ---

// THIS is the security test. The endpoint is public and holds a token with a
// 5000/hour budget, so a hundred presses must not cost a hundred API calls.
world = fresh();
const before = world.apiCalls;
for (let i = 0; i < 100; i++) {
  const r = await get("/windowsdownload");
  if (r.status !== 200) { check("100 rapid downloads all succeed", false, `status ${r.status}`); break; }
}
check("100 rapid downloads all succeed", true);
check("...and cost exactly ONE GitHub API call",
  world.apiCalls === 1, `apiCalls=${world.apiCalls} (was ${before})`);

world = fresh();
res = await get("/windowsdownload");
const cacheControl = res.headers.get("Cache-Control") || "";
check("the streamed installer is cacheable, not no-store",
  /public/.test(cacheControl) && /max-age=\d+/.test(cacheControl),
  `Cache-Control: ${cacheControl || "(none)"}`);

world = fresh();
await get("/windowsdownload");
const entry = [...world.cache.entries.values()][0];
const ttlMs = entry ? entry.expires - Date.now() : 0;
check("the cached release carries roughly a 5-minute TTL",
  ttlMs > 4 * 60_000 && ttlMs <= 5 * 60_000, `ttl=${Math.round(ttlMs / 1000)}s`);

world = fresh();
await get("/windowsdownload");
const stored = JSON.parse([...world.cache.entries.values()][0].body);
check("only name/url/size are cached - no release notes, no asset ids",
  stored.assets.every((a) =>
    Object.keys(a).sort().join(",") === "name,size,url"),
  JSON.stringify(stored.assets[0]));

world = fresh();
await get("/windowsdownload");
world.cache.entries.clear(); // simulate the TTL lapsing
await get("/windowsdownload");
check("after the TTL lapses the lookup is made again",
  world.apiCalls === 2, `apiCalls=${world.apiCalls}`);

// A failure must not be cached, or one bad minute pins an outage for five.
world = fresh({ releaseFails: true });
res = await get("/windowsdownload");
const firstStatus = res.status;
res = await get("/windowsdownload");
check("a GitHub failure is a 502",
  firstStatus === 502, `status ${firstStatus}`);
check("...and is NOT cached, so the next request retries",
  world.apiCalls === 2 && world.cache.entries.size === 0,
  `apiCalls=${world.apiCalls} cached=${world.cache.entries.size}`);

// A broken cache must degrade to the old behaviour, never to an error.
world = fresh({ cache: makeCache({ enabled: false }) });
res = await get("/windowsdownload");
check("a broken edge cache still serves the download",
  res.status === 200, `status ${res.status}`);
check("...and simply costs an API call per request, as it always did",
  world.apiCalls === 1, `apiCalls=${world.apiCalls}`);

// ----------------------------------------------------------- the throttle ---

world = fresh();
env.RATE_LIMITER = { limit: async () => ({ success: false }) };
res = await get("/windowsdownload");
check("the rate limiter can reject with a 429",
  res.status === 429, `status ${res.status}`);
check("...before any GitHub call is made",
  world.apiCalls === 0, `apiCalls=${world.apiCalls}`);
check("...and retry-after is set", res.headers.get("Retry-After") === "60");

env.RATE_LIMITER = { limit: async () => { throw new Error("binding died"); } };
world = fresh();
res = await get("/windowsdownload");
check("a broken rate limiter degrades to serving, not to 500",
  res.status === 200, `status ${res.status}`);

env.RATE_LIMITER = { limit: async () => ({ success: true }) };
world = fresh();
res = await get("/windowsdownload");
check("a passing rate limiter lets the request through",
  res.status === 200, `status ${res.status}`);
delete env.RATE_LIMITER;

// ------------------------------------------------------------------- done ---

console.log(failures ? `\n${failures} failed` : "\nall downloads-worker checks passed");
process.exit(failures ? 1 : 0);
