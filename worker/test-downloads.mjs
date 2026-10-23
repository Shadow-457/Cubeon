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

// --- Stub KV: the same get/put surface the counter uses ---------------------
function makeKV() {
  const store = new Map();
  return {
    store,
    async get(key) {
      return store.has(key) ? store.get(key) : null;
    },
    async put(key, value) {
      store.set(key, String(value));
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

// Every request carries its OWN CF-Connecting-IP by default, so one case cannot
// spend another's rate-limit budget; the throttle's own checks pin an IP in
// 203.0.113.0/24 so they can share a bucket on purpose. Same idiom as
// worker/test-worker.mjs.
let ipCounter = 0;
const freshIp = () => `10.0.0.${++ipCounter}`;
const get = (path, init = {}, ip = freshIp()) =>
  worker.fetch(new Request("https://cubeon-downloads.test" + path, {
    ...init,
    headers: {
      "CF-Connecting-IP": ip,
      ...(init.headers || {}),
    },
  }), env);

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

// -------------------------------------------------------------- the counter ---
// One count per IP, not per press (2026-10-24). This is the whole property the
// site advertises: a repeat visitor and a re-download must not move the number,
// a new visitor must. KV is stubbed here exactly as the Worker uses it.
env.DOWNLOADS = makeKV();
world = fresh();
res = await get("/count");
let countBody = await res.json();
check("a fresh namespace reads 0", countBody.value === 0,
  `value=${countBody.value}`);
check("the count is readable from the site's origin",
  res.headers.get("Access-Control-Allow-Origin") === "*");
check("the count is never cached", /no-store/.test(res.headers.get("Cache-Control") || ""));

res = await get("/count/hit", {}, "198.51.100.1");
check("the first hit from an IP counts", (await res.json()).value === 1);
res = await get("/count/hit", {}, "198.51.100.1");
check("a repeat hit from the same IP does NOT count", (await res.json()).value === 1);
res = await get("/count/hit", {}, "198.51.100.2");
check("a different IP counts", (await res.json()).value === 2);

res = await get("/count");
check("GET /count returns the running total", (await res.json()).value === 2);

world = fresh();
res = await get("/windowsdownload", {}, "198.51.100.3");
check("a direct download (JavaScript off) still counts", res.status === 200,
  `status ${res.status}`);
res = await get("/count");
check("...and the total went up", (await res.json()).value === 3);

res = await get("/windowsdownload", {}, "198.51.100.3");
res = await get("/count");
check("re-downloading from the same IP does not count again",
  (await res.json()).value === 3);

const keys = [...env.DOWNLOADS.store.keys()];
check("KV holds a count plus one HASHED marker per visitor",
  keys.includes("count") &&
  keys.filter((k) => k !== "count").every((k) => /^ip:[0-9a-f]{64}$/.test(k)),
  JSON.stringify(keys));
check("the raw IP address never reaches KV",
  !JSON.stringify(keys).includes("198.51.100.1"));

res = await get("/count/hit", { method: "POST" });
check("a non-GET hit is refused", res.status === 405, `status ${res.status}`);
res = await get("/count", { method: "OPTIONS" });
check("the CORS preflight is answered", res.status === 204 &&
  res.headers.get("Access-Control-Allow-Methods") === "GET, OPTIONS",
  `status ${res.status}`);

// The counter is decoration: no KV binding (local dev) must answer 0, and a
// download must still work.
delete env.DOWNLOADS;
world = fresh();
res = await get("/count");
check("without the KV binding the count reads 0, not an error",
  res.status === 200 && (await res.json()).value === 0, `status ${res.status}`);
res = await get("/windowsdownload");
check("...and downloads still stream", res.status === 200, `status ${res.status}`);

// ----------------------------------------------------- the cost property ---

// THIS is the security test. The endpoint is public and holds a token with a
// 5000/hour budget, so a hundred presses must not cost a hundred API calls.
// Each press here comes from its own IP, so the per-IP throttle cannot confound
// the measurement - the cache alone has to carry it.
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

// A PASSING binding must not switch the local gate off (the production
// regression: with the binding live and the local gate skipped, a rapid burst
// drew zero 429s), so the flood test below keeps the binding in place.
const EDGE_PASS_IP = "203.0.113.9";
let passBlocked = 0;
for (let i = 1; i <= 35; i++) {
  const r = await get("/windowsdownload", {}, EDGE_PASS_IP);
  if (r.status === 429) { passBlocked = i; break; }
}
check("a PASSING binding does not switch the local gate off",
  passBlocked === 31, `first 429 on request ${passBlocked || "(none in 35)"}`);
delete env.RATE_LIMITER;

// With NO binding bound at all the Worker must still be damped, not wide open:
// a flood here costs the account-wide 100k/day request budget that every other
// Worker shares, so the in-isolate fallback is what keeps one host from taking
// friend requests, skins and signups down with it for the rest of the day.
world = fresh();
const FLOOD_IP = "203.0.113.7";
let firstBlocked = 0;
for (let i = 1; i <= 35; i++) {
  const r = await get("/windowsdownload", {}, FLOOD_IP);
  if (r.status === 429) { firstBlocked = i; break; }
}
check("with NO binding, one IP is still throttled (the in-isolate fallback)",
  firstBlocked === 31, `first 429 on request ${firstBlocked || "(none in 35)"}`);
check("...and the flood still cost ONE cached lookup, not 30 API calls",
  world.apiCalls === 1, `apiCalls=${world.apiCalls}`);
res = await get("/windowsdownload", {}, "203.0.113.8");
check("...while a different IP is untouched", res.status === 200,
  `status ${res.status}`);

// ------------------------------------------------------------------- done ---

console.log(failures ? `\n${failures} failed` : "\nall downloads-worker checks passed");
process.exit(failures ? 1 : 0);
