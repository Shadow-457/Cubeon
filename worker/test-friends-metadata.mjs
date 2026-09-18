import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { Hub, MAX_DM_ENVELOPE_CHARS } from "./cubeon-friends.js";

const db = new DatabaseSync(":memory:");
const sql = {
  exec(query, ...args) {
    if (!args.length && query.includes("CREATE TABLE")) {
      db.exec(query);
      return { toArray: () => [] };
    }
    const rows = db.prepare(query).all(...args);
    return { toArray: () => rows };
  },
};
const sockets = [];
const ctx = { storage: { sql }, getWebSockets: () => sockets };
const hub = new Hub(ctx, {});
const ws = {
  attachment: { ip: "test" },
  frames: [],
  deserializeAttachment() { return this.attachment; },
  serializeAttachment(value) { this.attachment = value; },
  send(raw) { this.frames.push(JSON.parse(raw)); },
  close() {},
};
sockets.push(ws);
await hub.webSocketMessage(ws, JSON.stringify({
  t: "hello", name: "Player_12345678", secret: "test-secret-1234567890",
  minecraft_username: "BlueFox",
}));
assert.equal(hub.nameRow("player_12345678").minecraft_username, "BlueFox");
const hello = ws.frames.find((frame) => frame.t === "hello_ok");
assert.equal(hello.minecraft_username, "BlueFox");
assert.equal(hello.name, "Player_12345678");
assert.equal(hello.uid, "000000000001");
console.log("HELLO metadata persists and returns stable identity");

hub.onMetadata("player_12345678", { minecraft_username: "RedFox" });
assert.equal(hub.nameRow("player_12345678").minecraft_username, "RedFox");
ws.frames.length = 0;
hub.onMetadata("player_12345678", { minecraft_username: "bad name!" });
hub.onMetadata("player_12345678", { minecraft_username: 42 });
hub.onMetadata("player_12345678", {});
assert.equal(hub.nameRow("player_12345678").minecraft_username, "RedFox");
assert.equal(ws.frames.filter((frame) => frame.t === "metadata").length, 0);
console.log("METADATA updates reject invalid values without clearing");

hub.onMetadata("player_12345678", { minecraft_username: "RedFox" });
assert.equal(hub.nameRow("player_12345678").minecraft_username, "RedFox");
assert.equal(ws.frames.filter((frame) => frame.t === "metadata").length, 0);
console.log("METADATA unchanged write is skipped (no broadcast)");

ws.frames.length = 0;
hub.onMetadata("player_12345678", { minecraft_username: "BlueFox" });
assert.equal(hub.nameRow("player_12345678").minecraft_username, "BlueFox");
const metadataFrame = ws.frames.find((frame) => frame.t === "metadata");
assert.ok(metadataFrame);
assert.equal(metadataFrame.minecraft_username, "BlueFox");
assert.equal(metadataFrame.uid, "000000000001");
assert.equal(metadataFrame.name, "Player_12345678");
console.log("METADATA change persists and echoes full identity");

const names = new Set();
for (let i = 0; i < 50; i++) {
  const username = `D${String(i).padStart(2, "0")}${"x".repeat(9)}`;
  hub.onMetadata("player_12345678", { minecraft_username: username });
  names.add(hub.nameRow("player_12345678").minecraft_username);
}
assert.equal(names.size, 50);
assert.equal(hub.nameRow("player_12345678").minecraft_username.length, 12);
const peer = {
  attachment: { ip: "test" },
  frames: [],
  deserializeAttachment() { return this.attachment; },
  serializeAttachment(value) { this.attachment = value; },
  send(raw) { this.frames.push(JSON.parse(raw)); },
  close() {},
};
sockets.push(peer);
await hub.webSocketMessage(peer, JSON.stringify({
  t: "hello", name: "Ruby_87654321", secret: "ruby-secret-123456789012345",
}));
peer.frames.length = 0;
hub.onAdd("player_12345678", "Player_12345678", { uid: "000000000002" });
assert.ok(peer.frames.some((frame) => frame.t === "request" && frame.from_uid === "000000000001"));
ws.frames.length = 0;
hub.onMetadata("player_12345678", { minecraft_username: "NewName" });
assert.ok(peer.frames.some((frame) => frame.t === "metadata"
  && frame.minecraft_username === "NewName" && frame.uid === "000000000001"),
  "pending-request counterpart is notified of label change");
console.log("pending-request counterpart notified on metadata change");

const hub2 = new Hub(ctx, {});
assert.ok(hub2.nameRow("player_12345678").minecraft_username === "NewName");
hub2.nameRow("player_12345678");
console.log("repeat Hub construction (schema migration) is idempotent");

const dmReceiver = peer;
hub.onAccept("ruby_87654321", "Ruby_87654321", { name: "Player_12345678" });
ws.frames.length = 0;
dmReceiver.frames.length = 0;
const oversizedEnvelope = JSON.stringify({
  v: 1, from: "Player_12345678", to: "Ruby_87654321", ts: 1,
  spub: "a".repeat(43), nonce: "b".repeat(16),
  ct: "c".repeat(MAX_DM_ENVELOPE_CHARS),
});
await hub.webSocketMessage(ws, JSON.stringify({ t: "dm", to: "Ruby_87654321", text: oversizedEnvelope }));
const tooLarge = ws.frames.at(-1);
assert.equal(tooLarge.t, "error");
assert.equal(tooLarge.code, "dm_too_large");
assert.equal(tooLarge.message, "Message too long to send. Try a shorter one.");
assert.equal(dmReceiver.frames.filter((frame) => frame.t === "dm").length, 0);
assert.equal(db.prepare(
  "SELECT COUNT(*) AS n FROM messages WHERE conv LIKE 'd:%'").get().n, 0,
  "oversized envelope is never stored");
console.log("DM envelope over cap is rejected with an error and never stored");

ws.frames.length = 0;
dmReceiver.frames.length = 0;
const fitsCap = JSON.stringify({
  v: 1, from: "Player_12345678", to: "Ruby_87654321", ts: 1,
  spub: "a".repeat(43), nonce: "b".repeat(16),
  ct: "c".repeat(2 * MAX_DM_ENVELOPE_CHARS - oversizedEnvelope.length),
});
assert.equal(fitsCap.length, MAX_DM_ENVELOPE_CHARS);
await hub.webSocketMessage(ws, JSON.stringify({ t: "dm", to: "Ruby_87654321", text: fitsCap }));
assert.ok(ws.frames.at(-1).t === "dm" && ws.frames.at(-1).text === fitsCap,
  "envelope under the cap is echoed back intact, untruncated");
assert.ok(dmReceiver.frames.at(-1).t === "dm"
  && dmReceiver.frames.at(-1).text === fitsCap, "friend receives the intact envelope");
assert.equal(db.prepare(
  "SELECT text FROM messages WHERE conv LIKE 'd:%' ORDER BY ts DESC LIMIT 1").get().text,
  fitsCap, "stored text is the full envelope, byte-for-byte");
console.log("DM envelope at cap is stored and delivered intact");
hub.onHistory(ws, "player_12345678", { peer: "Ruby_87654321" });
assert.equal(ws.frames.at(-1).messages[0].text, fitsCap);
await hub.webSocketMessage(ws, JSON.stringify({ t: "dm", to: "Ruby_87654321", text: fitsCap + " " }));
assert.equal(ws.frames.at(-1).code, "dm_too_large");
assert.equal(db.prepare("SELECT COUNT(*) AS n FROM messages").get().n, 1);
await hub.webSocketMessage(ws, JSON.stringify({ t: "dm", to: "Ruby_87654321", text: "  plain legacy DM  " }));
assert.equal(ws.frames.at(-1).text, "plain legacy DM");
assert.equal(dmReceiver.frames.at(-1).text, "plain legacy DM");
console.log("DM history preserves envelopes; cap+1 rejects; plain-DM trimming stays compatible");

ws.frames.length = 0;
dmReceiver.frames.length = 0;
await hub.webSocketMessage(ws, JSON.stringify({ t: "dm", to: "Ruby_87654321", text: "   " }));
assert.equal(ws.frames.at(-1).code, "dm_empty", "blank DM still refuses with dm_empty");
console.log("blank DMs keep their existing refusal");
db.close();
