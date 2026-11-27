import assert from "node:assert/strict";
import worker, { Hub } from "./cubeon-friends.js";

const sockets = [];
const ctx = { getWebSockets: () => sockets };
// Reconstruct only the socket-reading side of the hub. The count must work
// without a database or a connection handler having run in this isolate.
const makeHub = () => Object.assign(Object.create(Hub.prototype), { ctx });
let hub = makeHub();
const env = { HUB: {
  idFromName(name) { assert.equal(name, "global"); return name; },
  get() { return hub; },
} };
const request = (method = "GET") => worker.fetch(
  new Request("https://friends.example/online", { method }), env);
const socket = (attachment, readyState = 1) => ({
  readyState,
  deserializeAttachment: () => attachment,
});

const originalNow = Date.now;
let now = originalNow();
Date.now = () => now;
try {
  const response = await request();
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), "*");
  assert.equal(response.headers.get("Cache-Control"), "public, max-age=15");
  assert.deepEqual(await response.json(), { online: 0 });

  sockets.push(
    socket({ ip: "upgraded-before-hello" }),
    socket({ name: "legacy", status: "online" }),
    socket({ name: "legacy", status: "online" }),
    socket({ name: "current", version: "1.21.11" }),
    socket({ name: "closing" }, 2),
  );
  now += 14999;
  assert.deepEqual(await (await request()).json(), { online: 0 });
  now++;
  assert.deepEqual(await (await request()).json(), { online: 2 });

  hub = makeHub();
  assert.deepEqual(await (await request()).json(), { online: 2 });
  sockets[1].readyState = 3;
  now += 15000;
  assert.deepEqual(await (await request()).json(), { online: 2 });
  sockets[2].readyState = 3;
  now += 15000;
  assert.deepEqual(await (await request()).json(), { online: 1 });

  const rejected = await request("POST");
  assert.equal(rejected.status, 405);
  assert.equal(rejected.headers.get("Allow"), "GET");
} finally {
  Date.now = originalNow;
}
console.log("Online count reuses authenticated sockets across hub wakes and deduplicates connections.");
