/**
 * Tests for worker/cubeon-invites.js - run with:
 *
 *     node worker/test-invites.mjs
 *
 * Needs nothing installed. Imports the Worker directly against a stub KV
 * namespace, which works because the Worker only uses get/put/delete.
 *
 * The checks that matter most are the ownership ones: this endpoint is the only
 * thing standing between a host's friends and someone redirecting them
 * elsewhere, and it has to hold with no accounts and no login anywhere in the
 * system.
 */
import { createHash } from "node:crypto";

import worker from "./cubeon-invites.js";

// --- Stub KV: get/put/delete, plus enough TTL bookkeeping to test expiry ----
const store = new Map();
const env = {
  INVITES: {
    async get(key, type) {
      const record = store.get(key);
      if (!record) return null;
      if (record.expires !== null && record.expires <= Date.now() / 1000) {
        store.delete(key); // matches KV's behaviour: expired reads as absent
        return null;
      }
      return type === "json" ? JSON.parse(record.value) : record.value;
    },
    async put(key, value, options = {}) {
      store.set(key, {
        value,
        expires: options.expirationTtl
          ? Date.now() / 1000 + options.expirationTtl
          : null,
      });
    },
    async delete(key) {
      store.delete(key);
    },
  },
};

let failures = 0;
function check(label, ok, extra = "") {
  console.log(`${ok ? "  ok  " : " FAIL "} ${label}${extra ? "  " + extra : ""}`);
  if (!ok) failures++;
}

const CODE = "CUBE-7F4K-9QMN";
const SECRET = "s".repeat(43); // shaped like secrets.token_urlsafe(32)
const OTHER_SECRET = "x".repeat(43);

const call = (path, init) =>
  worker.fetch(new Request("https://test.invalid" + path, init), env);

const put = (code, body, secret = SECRET) =>
  call(`/i/${code}`, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${secret}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

const del = (code, secret = SECRET) =>
  call(`/i/${code}`, { method: "DELETE", headers: { Authorization: `Bearer ${secret}` } });

/** Reaches into the stub to check storage decisions the API doesn't expose. */
const stored = (code) => {
  const record = store.get(`invite:${code}`);
  return record ? JSON.parse(record.value) : null;
};

console.log("\n1. claim and resolve");

let res = await put(CODE, { address: "bluefox-1234.gl.joinmc.link:52341", version: "1.21.11", loader: "fabric" });
let body = await res.json();
check("claiming a free code succeeds", res.status === 200 && body.claimed === true,
  `${res.status} ${JSON.stringify(body)}`);

res = await call(`/i/${CODE}`);
body = await res.json();
check("resolves to the published address",
  body.address === "bluefox-1234.gl.joinmc.link:52341", JSON.stringify(body));
check("carries version and loader for the join UI",
  body.version === "1.21.11" && body.loader === "fabric");
check("reports an age, not an absolute timestamp",
  typeof body.age === "number" && body.age < 5 && !("updated" in body));
check("reports time left so a stale code can be flagged",
  body.expires_in > 23 * 3600);

check("never leaks the secret hash",
  !JSON.stringify(body).includes("secret") &&
  !JSON.stringify(body).includes(createHash("sha256").update(SECRET).digest("hex")));

check("stores only a hash of the secret, never the secret",
  stored(CODE).secret_hash === createHash("sha256").update(SECRET).digest("hex") &&
  !JSON.stringify(stored(CODE)).includes(SECRET));

check("lower-case code resolves (kids retype codes by hand)",
  (await call(`/i/${CODE.toLowerCase()}`)).status === 200);

check("unknown code -> 404", (await call("/i/CUBE-3333-4444")).status === 404);

console.log("\n2. ownership - the whole security model");

res = await put(CODE, { address: "attacker.example.com:25565" }, OTHER_SECRET);
check("a different secret cannot redirect the code", res.status === 409,
  `got ${res.status}`);
check("...and the address is untouched",
  stored(CODE).address === "bluefox-1234.gl.joinmc.link:52341");

res = await call(`/i/${CODE}`, {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ address: "nowhere.example.com:25565" }),
});
check("no Authorization header -> 401", res.status === 401);

res = await del(CODE, OTHER_SECRET);
check("a different secret cannot unpublish", res.status === 403);

// First-come ownership, spelled out: an unclaimed code is claimable by whoever
// asks, which is the model - a fresh code has no rightful owner to impersonate.
// An *already claimed* one is not, which is the check above.
res = await put("CUBE-CCCC-DDDD", { address: "a.example.com:25565" }, OTHER_SECRET);
check("an unclaimed code is claimable by any secret", res.status === 200);
check("...and is then locked to that secret",
  (await put("CUBE-CCCC-DDDD", { address: "b.example.com:25565" }, SECRET)).status === 409);

console.log("\n3. the write budget (KV free tier: ~1000 writes/day)");

const before = stored(CODE).updated;
res = await put(CODE, { address: "bluefox-1234.gl.joinmc.link:52341", version: "1.21.11", loader: "fabric" });
body = await res.json();
check("re-publishing an unchanged address spends no write", body.written === false,
  JSON.stringify(body));
check("...and leaves the entry byte-identical", stored(CODE).updated === before);

res = await put(CODE, { address: "bluefox-1234.gl.joinmc.link:60000", version: "1.21.11", loader: "fabric" });
body = await res.json();
check("a changed port does write", body.written === true);
check("...and resolve reflects it immediately",
  (await (await call(`/i/${CODE}`)).json()).address === "bluefox-1234.gl.joinmc.link:60000");

check("re-publish keeps the original created time (code identity is stable)",
  stored(CODE).created <= stored(CODE).updated);

check("entries expire so abandoned codes cost no delete",
  store.get(`invite:${CODE}`).expires !== null);

// Simulate a long session: the entry is old, so even an unchanged publish must
// write to refresh the TTL before the 24h expiry drops a live server.
const record = store.get(`invite:${CODE}`);
const aged = JSON.parse(record.value);
aged.updated = Math.floor(Date.now() / 1000) - 7 * 3600;
store.set(`invite:${CODE}`, { ...record, value: JSON.stringify(aged) });
body = await (await put(CODE, { address: "bluefox-1234.gl.joinmc.link:60000", version: "1.21.11", loader: "fabric" })).json();
check("a long-running session refreshes its TTL", body.written === true);

console.log("\n4. bad input never reaches KV");

for (const bad of ["CUBE-0000-0000", "CUBE-7F4K", "CUBE7F4K9QMN", "NOPE-7F4K-9QMN",
                   "CUBE-7F4K-9QM", "CUBE-IIII-LLLL", "../invite:CUBE-7F4K-9QMN"]) {
  check(`rejects malformed code ${JSON.stringify(bad)}`,
    (await call(`/i/${bad}`)).status === 404);
}

for (const bad of [undefined, "", "noport.example.com", "host:notaport", "localhost:25565",
                   "just-a-word:25565", ":25565", "a.example.com:99999",
                   "a.example.com:0", "a.example.com:25565extra"]) {
  const r = await put("CUBE-3333-4444", { address: bad });
  check(`rejects address ${JSON.stringify(bad)}`, r.status === 400, `got ${r.status}`);
}

check("accepts a bare IPv4 host (LAN and VPS both need it)",
  (await put("CUBE-3333-4444", { address: "203.0.113.7:25565" })).status === 200);

let r = await put("CUBE-4444-6666", { address: "a.example.com:25565", version: "../../etc/passwd" });
check("rejects a junk version field instead of storing it", r.status === 400);
r = await put("CUBE-4444-6666", { address: "a.example.com:25565", loader: "FABRIC!" });
check("rejects a junk loader field", r.status === 400);
r = await put("CUBE-4444-6666", { address: "a.example.com:25565" });
check("version and loader are genuinely optional", r.status === 200);
check("...and read back as null, not undefined",
  (await (await call("/i/CUBE-4444-6666")).json()).version === null);

r = await call("/i/CUBE-4444-7777", {
  method: "PUT",
  headers: { Authorization: `Bearer ${SECRET}` },
  body: "not json",
});
check("rejects a non-JSON body", r.status === 400);

r = await call("/i/CUBE-4444-7777", {
  method: "PUT",
  headers: { Authorization: `Bearer ${SECRET}` },
  body: JSON.stringify({ address: "a.example.com:25565", pad: "z".repeat(2000) }),
});
check("rejects an oversized body", r.status === 400);

r = await call("/i/CUBE-4444-7777", {
  method: "PUT",
  headers: { Authorization: "Bearer short" },
  body: JSON.stringify({ address: "a.example.com:25565" }),
});
check("rejects an implausibly short secret", r.status === 401);

console.log("\n5. unpublish and moderation");

res = await del(CODE);
check("owner can unpublish", res.status === 204);
check("...and the code stops resolving", (await call(`/i/${CODE}`)).status === 404);
check("unpublishing twice is not an error (retry-safe)",
  (await del(CODE)).status === 204);

await put(CODE, { address: "bluefox-1234.gl.joinmc.link:52341" });
store.set("blocked:" + CODE, { value: "1", expires: null });
check("blocked code -> 404, like a reported skin",
  (await call(`/i/${CODE}`)).status === 404);
check("...and cannot be re-published while blocked",
  (await put(CODE, { address: "a.example.com:25565" })).status === 403);
store.delete("blocked:" + CODE);

console.log("\n6. protocol surface");

check("/health -> 200", (await call("/health")).status === 200);
check("POST to /health -> 405", (await call("/health", { method: "POST" })).status === 405);
check("unknown path -> 404", (await call("/nope")).status === 404);
res = await call(`/i/${CODE}`, { method: "POST" });
check("POST to a code -> 405 with Allow", res.status === 405 && !!res.headers.get("Allow"));
check("resolve is cached only briefly (hosts change ports)",
  /max-age=\d+/.test((await call(`/i/${CODE}`)).headers.get("Cache-Control")) &&
  Number(/max-age=(\d+)/.exec((await call(`/i/${CODE}`)).headers.get("Cache-Control"))[1]) <= 60);
check("writes are never cached",
  (await put(CODE, { address: "bluefox-1234.gl.joinmc.link:52341" }))
    .headers.get("Cache-Control") === "no-store");

console.log(failures ? `\n${failures} CHECK(S) FAILED` : "\nALL INVITE WORKER CHECKS PASSED");
process.exit(failures ? 1 : 0);
