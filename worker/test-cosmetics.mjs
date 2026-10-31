import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import worker from "./cubeon-skins.js";

const store = new Map();
let puts = 0, gates = 0, quota = false, ip = 0;
const env = {
  RATE_LIMITER: { async limit() { gates++; return { success: true }; } },
  SKINS: {
    async get(key, type) { const v = store.get(key); return v === undefined ? null : type === "json" ? JSON.parse(v) : v; },
    async put(key, value) { if (quota) throw Error("limit exceeded"); puts++; store.set(key, value); },
  },
};
const uuid = randomUUID(), token = "cosmetics-test-private-token";
async function call(path, data, secret = token, address = `10.20.0.${++ip}`) {
  return worker.fetch(new Request("https://test.invalid" + path, {
    method: data === undefined ? "GET" : "POST",
    headers: { "CF-Connecting-IP": address, "Content-Type": "application/json",
      ...(secret ? { Authorization: `Bearer ${secret}` } : {}) },
    ...(data === undefined ? {} : { body: JSON.stringify(data) }),
  }), env);
}
const selected = { uuid, back: "back_void_wings", shoulder: "shoulder_star_owl" };
assert.equal((await call("/api/cosmetics", selected, null)).status, 401);
assert.equal((await call("/api/cosmetics", selected)).status, 403);
assert.equal(puts, 0, "Cosmetic publication cannot claim an identity");
assert.equal((await call("/api/heartbeat", { uuid, username: "CosmeticPeer" })).status, 200);
let response = await call("/cosmetics/cosmeticpeer.json");
assert.deepEqual(await response.json(), { version: 1, username: "cosmeticpeer", uuid, back: null, shoulder: null });
let before = puts;
assert.equal((await call("/api/cosmetics", selected)).status, 200);
assert.equal(puts, before + 1);
assert.equal((await call("/api/cosmetics", selected)).status, 200);
assert.equal(puts, before + 1, "Unchanged selection costs zero writes");
response = await call("/cosmetics/CosmeticPeer.json");
assert.equal(response.headers.get("Cache-Control"), "public, max-age=60");
assert.equal((await response.json()).back, selected.back);
assert.equal((await call("/api/cosmetics", selected, "some-other-private-token")).status, 403);
assert.equal(puts, before + 1);
for (const bad of [{ back: "shoulder_star_owl" }, { shoulder: "https://bad.invalid/x" }, { back: "back_void_wings_flat" }, { back: "no_such_item" }, { shoulder: 2 }]) {
  assert.equal((await call("/api/cosmetics", { ...selected, ...bad })).status, 400);
}
const catalog = JSON.parse(readFileSync(new URL("../assets/cosmetics/catalog.json", import.meta.url)));
for (const item of catalog.items) {
  const payload = { uuid, back: null, shoulder: null, [item.slot]: item.id };
  assert.equal((await call("/api/cosmetics", payload)).status, 200, `Worker catalogue accepts ${item.id}`);
  assert.equal((await (await call("/cosmetics/cosmeticpeer.json")).json())[item.slot], item.id);
}
assert.equal((await call("/api/cosmetics", { uuid, back: null, shoulder: null })).status, 200);
assert.equal((await (await call("/cosmetics/cosmeticpeer.json")).json()).back, null, "None clears shared selection");
assert.equal((await call("/cosmetics/UnknownPeer.json")).status, 404);
assert.equal((await call("/cosmetics/a.json")).status, 404);
store.set(`blocked:${uuid}`, "1");
assert.equal((await call("/api/cosmetics", selected)).status, 403);
assert.equal((await call("/cosmetics/cosmeticpeer.json")).status, 404);
store.delete(`blocked:${uuid}`);
quota = true;
assert.equal((await call("/api/cosmetics", selected)).status, 429);
quota = false;
const gateBefore = gates;
for (let count = 0; count < 240; count++)
  assert.equal((await call("/cosmetics/cosmeticpeer.json", undefined, null, "10.30.0.1")).status, 200);
assert.equal(gates, gateBefore, "Read lookups do not consume the write limiter");
assert.equal((await call("/cosmetics/cosmeticpeer.json", undefined, null, "10.30.0.1")).status, 429);
assert.equal(store.get(`owner:${uuid}`), createHash("sha256").update(token).digest("hex"));
console.log("Cosmetic ownership, catalogue parity, read/write limits, zero-write dedupe, clearing, blocking and quota checks passed.");
