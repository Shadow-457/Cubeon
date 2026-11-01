// Exercise real routing/cache behavior with counted KV operations and no network.
import assert from "node:assert/strict";
import worker from "./cubeon-skins.js";

let now = 1_000_000, reads = 0, writes = 0, address = 0;
const realNow = Date.now;
Date.now = () => now;
const stored = new Map(), edge = new Map();
const env = { SKINS: {
  async get(key, type) {
    reads++;
    await Promise.resolve();
    const value = stored.get(key);
    return value === undefined ? null : type === "json" ? JSON.parse(value) : value;
  },
  async put(key, value) { writes++; stored.set(key, value); },
} };
globalThis.caches = { default: {
  async match(key) {
    const entry = edge.get(key.url);
    return entry && entry.until > now ? entry.response.clone() : undefined;
  },
  async put(key, response) {
    const ttl = Number(response.headers.get("Cache-Control").match(/max-age=(\d+)/)[1]);
    edge.set(key.url, { until: now + ttl * 1000, response });
  },
} };
async function request(path, headers = {}, method = "GET") {
  return worker.fetch(new Request("https://skins.example" + path, {
    method, headers: { "CF-Connecting-IP": `10.0.0.${++address}`, ...headers },
  }), env);
}
const uuid = "00000000-0000-0000-0000-000000000001", texture = "a".repeat(64), face = "b".repeat(64);
stored.set("pointer:alice", uuid);
stored.set(`skin:${uuid}`, JSON.stringify({ id: texture, face, model: "slim" }));
stored.set(`texture:${texture}`, "c2tpbg==");
stored.set(`texture:${face}`, "ZmFjZQ==");
try {
  const simultaneous = await Promise.all(Array.from({ length: 40 }, () => request("/skins/alice.json")));
  assert.equal(reads, 3, "40 simultaneous cold profile reads share three KV operations");
  for (const response of simultaneous) assert.equal((await response.json()).textures.slim, texture);
  for (let index = 0; index < 40; index++) {
    const response = await request(`/skins/Alice.json?nonce=${index}`);
    assert.equal((await response.json()).username, "Alice", "Canonical cache preserves caller spelling");
  }
  assert.equal(reads, 3, "Case/query variants of warm profiles spend zero KV reads");
  const tagged = await request("/skins/alice.json");
  const conditional = await request("/skins/alice.json", { "If-None-Match": tagged.headers.get("ETag") });
  assert.equal(conditional.status, 304);
  assert.equal(await conditional.text(), "");
  const head = await request("/skins/alice.json", {}, "HEAD");
  assert.equal(head.status, 200); assert.equal(await head.text(), "");
  assert.equal(reads, 3, "Conditional GET/HEAD reuse the same profile cache");
  let before = reads;
  await request(`/textures/${texture}`);
  await request(`/skins/textures/${texture}?nonce=1`);
  assert.equal(reads - before, 1, "Texture aliases share one immutable cache entry");
  const faceResponse = await request("/faces/Alice.png");
  assert.equal(faceResponse.headers.get("Cache-Control"), "public, max-age=60",
    "Username avatars must refresh after changes, unlike immutable hash URLs");
  assert.equal(await faceResponse.text(), "face");
  before = reads;
  await request("/skins/Unknown.json");
  await request("/skins/UNKNOWN.json?another=1");
  assert.equal(reads - before, 1, "Missing players are negatively cached");
  assert.equal(writes, 0, "Read caching never spends KV writes");
  stored.set(`blocked:${uuid}`, "1");
  now += 61_000;
  assert.equal((await request("/skins/alice.json")).status, 404, "Moderation takes effect after bounded profile TTL");
  assert.equal((await request("/faces/alice.png")).status, 404);
  before = reads;
  assert.equal((await request("/skins/alice.json")).status, 404);
  assert.equal(reads, before, "Blocked profile misses are cached too");
  assert.equal((await request("/api/skin", {}, "POST")).status, 401,
    "A cached profile never authorizes an upload");
  before = reads;
  await request("/skins/../bad.json");
  await request("/skins/x.json");
  assert.equal(reads, before, "Invalid paths/names do not reach KV or create public entries");
  const ownEnv = { SKINS: { async get() { return null; } } };
  assert.equal((await worker.fetch(new Request("https://other.example/skins/alice.json"), ownEnv)).status, 404,
    "Cache keys remain scoped to the service origin");
  globalThis.caches.default = {
    async match() { throw Error("cache unavailable"); },
    async put() { throw Error("cache unavailable"); },
  };
  stored.delete(`blocked:${uuid}`);
  assert.equal((await request("/skins/alice.json")).status, 200, "Broken Cache API degrades to KV");
  console.log("PASS 80 profile requests use 3 KV reads; alias, negative, ETag, HEAD, moderation, auth and cache-failure checks");
} finally {
  Date.now = realNow;
  delete globalThis.caches;
}
