/**
 * Tests for worker/cubeon-waitlist.js - run with:
 *
 *     node worker/test-waitlist.mjs
 *
 * Same shape as test-worker.mjs: no wrangler, no npm, no Cloudflare account.
 * The Worker module is imported directly and handed a stub KV namespace.
 *
 * Why this file exists: the site no longer collects emails, but the KV
 * namespace still holds the addresses the old waitlist form captured. So the
 * unsubscribe / "delete my data" route has to actually delete, has to tell the
 * truth when there is nothing to delete, and has to stay cheap - KV writes are
 * the scarce resource on the free tier.
 *
 * Separate from test-worker.mjs (which covers the skins Worker) on purpose: one
 * harness per Worker, each runnable on its own.
 */
import { createHash } from "node:crypto";

import worker from "./cubeon-waitlist.js";

// --- Stub KV: just the subset of the API this Worker calls ----------------
const store = new Map();
let writes = 0;
const env = {
  WAITLIST: {
    async get(key, type) {
      if (!store.has(key)) return null;
      const value = store.get(key);
      return type === "json" ? JSON.parse(value) : value;
    },
    async put(key, value) {
      writes++;
      store.set(key, String(value));  // real KV coerces to string
    },
    async delete(key) {
      writes++;
      store.delete(key);
    },
  },
};

const keyFor = (email) => "email:" + createHash("sha256").update(email).digest("hex");
const get = (path) => worker.fetch(new Request("https://test.invalid" + path), env);
const post = (path, obj) => worker.fetch(new Request("https://test.invalid" + path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(obj),
}), env);

let failures = 0;
function check(label, ok) {
  if (ok) console.log("  ok   " + label);
  else { failures++; console.log("  FAIL " + label); }
}

// --- health + routing -----------------------------------------------------
let res = await get("/health");
check("GET /health -> 200 plain text", res.status === 200 &&
  (await res.text()).startsWith("cubeon-waitlist ok"));

res = await get("/");
let data = await res.json();
check("GET / on an empty KV -> count 0", res.status === 200 && data.count === 0);
check("CORS is open on the public tally",
  res.headers.get("Access-Control-Allow-Origin") === "*");

res = await worker.fetch(new Request("https://test.invalid/", { method: "OPTIONS" }), env);
check("OPTIONS -> 204", res.status === 204);

res = await worker.fetch(new Request("https://test.invalid/", { method: "DELETE" }), env);
check("unknown method -> 405", res.status === 405);

// --- signup ---------------------------------------------------------------
res = await post("/", { email: "Friend@Example.COM " });
data = await res.json();
check("POST / -> joined, count 1", res.status === 200 && data.joined === true && data.count === 1);
check("address is normalised before hashing", store.has(keyFor("friend@example.com")));
check("the raw address is kept in the value, not the key",
  JSON.parse(store.get(keyFor("friend@example.com"))).email === "friend@example.com");

let before = writes;
res = await post("/", { email: "friend@example.com" });
data = await res.json();
check("duplicate signup -> joined false, count unchanged, zero writes",
  data.joined === false && data.count === 1 && writes === before);

before = writes;
res = await post("/", { email: "not-an-email" });
check("invalid address -> 422 and no write", res.status === 422 && writes === before);

before = writes;
res = await post("/", { email: "x".repeat(2000) + "@example.com" });
check("oversized body -> 400 and no write", res.status === 400 && writes === before);

// --- unsubscribe over JSON (the data-deletion path) -----------------------
res = await post("/unsubscribe", { email: "friend@example.com" });
data = await res.json();
check("POST /unsubscribe -> removed, count back to 0",
  res.status === 200 && data.removed === true && data.count === 0);
check("the record is really gone from KV", !store.has(keyFor("friend@example.com")));

before = writes;
res = await post("/unsubscribe", { email: "friend@example.com" });
data = await res.json();
check("second unsubscribe -> removed false (the truth), zero writes",
  data.removed === false && data.count === 0 && writes === before);

before = writes;
res = await post("/unsubscribe", { email: "nobody@example.com" });
data = await res.json();
check("unsubscribing an unknown address -> removed false, zero writes",
  data.removed === false && writes === before);

res = await post("/unsubscribe", { email: "" });
check("unsubscribe with no address -> 422", res.status === 422);

// --- unsubscribe link from an email (GET) ---------------------------------
await post("/", { email: "link@example.com" });
res = await get("/unsubscribe?email=link%40example.com");
let html = await res.text();
check("GET /unsubscribe?email=... -> 200 HTML",
  res.status === 200 && res.headers.get("Content-Type").startsWith("text/html"));
check("the link route says it deleted", html.includes("You're off the list"));
check("the link route mentions no suppression list", html.includes("suppression list"));
check("the link route really deleted", !store.has(keyFor("link@example.com")));

res = await get("/unsubscribe?email=link%40example.com");
html = await res.text();
check("a stale link tells the truth instead of claiming a deletion",
  html.includes("wasn&#39;t on the list") || html.includes("wasn't on the list"));

res = await get("/unsubscribe?email=bogus");
check("a link with no valid address -> HTML with a fallback instruction",
  res.status === 200 && (await res.text()).includes("missing a valid address"));

// --- the tally stays honest ----------------------------------------------
await post("/", { email: "a@example.com" });
await post("/", { email: "b@example.com" });
await post("/unsubscribe", { email: "a@example.com" });
res = await get("/");
data = await res.json();
check("count reflects live records only", data.count === 1);

before = writes;
await post("/unsubscribe", { email: "b@example.com" });
res = await get("/");
data = await res.json();
check("deleting the last record -> count 0, never negative", data.count === 0);
check("a deletion costs two writes (record + tally), like a signup",
  writes === before + 2);

console.log(failures ? `\n${failures} CHECK(S) FAILED` : "\nALL WAITLIST CHECKS PASSED");
process.exit(failures ? 1 : 0);
