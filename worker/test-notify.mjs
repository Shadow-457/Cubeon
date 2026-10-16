/**
 * Tests for the /notify route of cubeon-downloads.js (Phase 6).
 *
 *   node worker/test-notify.mjs
 *
 * No deps, no network, no Cloudflare account: the Worker's `fetch` is called
 * directly with plain Request objects and a tiny in-memory KV stand-in.
 *
 * The Worker is loaded through a data: URL rather than a plain `import`, so
 * this test does not depend on a package.json declaring "type": "module"
 * (the sibling .js workers have none).
 */
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("./cubeon-downloads.js", import.meta.url), "utf8");
const worker = (await import(
  "data:text/javascript;base64," + Buffer.from(SRC).toString("base64")
)).default;

const ENDPOINT = "https://cubeon-downloads.example/notify";

let passed = 0;
let failed = 0;

function check(label, cond, detail = "") {
  if (cond) {
    passed++;
    console.log(`  ok   ${label}`);
  } else {
    failed++;
    console.log(`  FAIL ${label}${detail ? `\n       ${detail}` : ""}`);
  }
}

/** Minimal KV stand-in: get/put only, which is all handleNotify uses. */
function fakeKV(initial = {}) {
  const store = { ...initial };
  return {
    store,
    async get(key) {
      return key in store ? store[key] : null;
    },
    async put(key, value) {
      store[key] = value;
    },
  };
}

function post(body, { token = "s3cret", headers = {} } = {}) {
  const h = { "Content-Type": "application/json", ...headers };
  if (token !== null) h.Authorization = `Bearer ${token}`;
  return new Request(ENDPOINT, { method: "POST", headers: h, body: JSON.stringify(body) });
}

const get = new Request(ENDPOINT, { method: "GET" });

console.log("1. an unauthenticated POST is rejected before anything is stored");

{
  const kv = fakeKV();
  const res = await worker.fetch(post({ headline: "Hi", content: "There" }, { token: null }), { CUBEON_NOTIFY: kv, NOTIFY_TOKEN: "s3cret" });
  check("no Authorization header -> 401", res.status === 401, `got ${res.status}`);
  check("nothing was written to KV", Object.keys(kv.store).length === 0);
}
{
  const res = await worker.fetch(post({ headline: "Hi", content: "x" }, { token: "wrong" }), { CUBEON_NOTIFY: fakeKV(), NOTIFY_TOKEN: "s3cret" });
  check("a wrong token -> 401", res.status === 401, `got ${res.status}`);
}
{
  const res = await worker.fetch(post({ headline: "Hi", content: "x" }), { CUBEON_NOTIFY: fakeKV() });
  check("no NOTIFY_TOKEN secret configured -> 401 (never open)", res.status === 401, `got ${res.status}`);
}

console.log("\n2. an authorised POST stores the entry and GET reads it back");

{
  const kv = fakeKV();
  const env = { CUBEON_NOTIFY: kv, NOTIFY_TOKEN: "s3cret" };
  const res = await worker.fetch(post({ headline: "  Hello  ", content: "  World  " }), env);
  check("authorised POST -> 200", res.status === 200, `got ${res.status}`);
  const body = await res.json();
  check("the response carries ok + a ts", body.ok === true && typeof body.ts === "number", JSON.stringify(body));

  const stored = JSON.parse(kv.store.latest);
  check("whitespace is trimmed", stored.headline === "Hello" && stored.content === "World", kv.store.latest);
  check("url defaults to null", stored.url === null, kv.store.latest);

  const read = await worker.fetch(get, env);
  check("GET -> 200", read.status === 200, `got ${read.status}`);
  const entry = await read.json();
  check("GET returns the same entry",
    entry.headline === "Hello" && entry.content === "World" && entry.ts === stored.ts,
    JSON.stringify(entry));
}

console.log("\n3. bad input never reaches storage");

{
  const kv = fakeKV();
  const env = { CUBEON_NOTIFY: kv, NOTIFY_TOKEN: "s3cret" };
  check("missing content -> 400", (await worker.fetch(post({ headline: "x" }), env)).status === 400);
  check("blank headline -> 400", (await worker.fetch(post({ headline: "   ", content: "y" }), env)).status === 400);
  check("malformed json -> 400",
    (await worker.fetch(new Request(ENDPOINT, {
      method: "POST",
      headers: { Authorization: "Bearer s3cret", "Content-Type": "application/json" },
      body: "not json",
    }), env)).status === 400);
  const long = "z".repeat(4001);
  check("oversized content -> 413",
    (await worker.fetch(post({ headline: "x", content: long }), env)).status === 413);
  check("nothing was stored by any of those", Object.keys(kv.store).length === 0);
}

console.log("\n4. the url field is sanitised");

{
  const kv = fakeKV();
  const env = { CUBEON_NOTIFY: kv, NOTIFY_TOKEN: "s3cret" };
  await worker.fetch(post({ headline: "x", content: "y", url: "javascript:alert(1)" }), env);
  check("a javascript: url is dropped",
    JSON.parse(kv.store.latest).url === null, kv.store.latest);
  await worker.fetch(post({ headline: "x", content: "y", url: "https://cubeon.run.place/" }), env);
  check("an https url is kept",
    JSON.parse(kv.store.latest).url === "https://cubeon.run.place/", kv.store.latest);
}

console.log("\n5. degraded environments answer usefully, not fatally");

{
  check("GET with no KV binding -> 204 (nothing to show)",
    (await worker.fetch(get, {})).status === 204);
  check("POST with no KV binding -> 501 (misconfigured)",
    (await worker.fetch(post({ headline: "x", content: "y" }), { NOTIFY_TOKEN: "s3cret" })).status === 501);
  check("GET with an empty store -> 204",
    (await worker.fetch(get, { CUBEON_NOTIFY: fakeKV() })).status === 204);
  const put = new Request(ENDPOINT, { method: "PUT", headers: { Authorization: "Bearer s3cret" } });
  const res = await worker.fetch(put, { CUBEON_NOTIFY: fakeKV(), NOTIFY_TOKEN: "s3cret" });
  check("PUT -> 405 with an Allow header",
    res.status === 405 && res.headers.get("Allow") === "GET, POST", `got ${res.status}`);
}

console.log("\n6. the download routes and /health are untouched");

{
  const res = await worker.fetch(new Request("https://x/health"), {});
  check("/health still answers OK", res.status === 200 && (await res.text()) === "cubeon-downloads ok");
  const res2 = await worker.fetch(new Request("https://x/nope"), {});
  check("an unknown route is still 404", res2.status === 404);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  console.log("notify worker test: FAIL");
  process.exit(1);
}
console.log("notify worker test: PASS");
