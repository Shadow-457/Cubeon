import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { Hub } from "./cubeon-friends.js";

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
const hub = new Hub({ storage: { sql }, getWebSockets: () => sockets }, {});
let passed = 0;
function check(label, actual, expected) {
  assert.deepEqual(actual, expected, label);
  passed++;
  console.log(`  ok   ${label}`);
}
async function connect(name, minecraft_username) {
  const ws = {
    attachment: { ip: "test" }, frames: [],
    deserializeAttachment() { return this.attachment; },
    serializeAttachment(value) { this.attachment = value; },
    send(raw) { this.frames.push(JSON.parse(raw)); },
    close() {},
  };
  sockets.push(ws);
  await send(ws, { t: "hello", name, secret: `test-secret-${name}`, minecraft_username });
  return ws;
}
const send = (ws, frame) => hub.webSocketMessage(ws, JSON.stringify(frame));
const caller = await connect("Player_11111111", "BlueFox");
const peer = await connect("Player_22222222", "RubyFox");
await send(caller, { t: "add", name: "Player_22222222" });
check("requester initially sees outgoing request", caller.frames.at(-1).requests_out, ["Player_22222222"]);
check("target initially sees incoming request", peer.frames.at(-1).requests_in, ["Player_11111111"]);
caller.frames.length = peer.frames.length = 0;
await send(peer, { t: "decline", name: "Player_11111111" });
check("decline sends requester a refreshed roster", caller.frames.map((f) => f.t), ["roster"]);
check("decline sends target a refreshed roster", peer.frames.map((f) => f.t), ["roster"]);
check("requester's outgoing strings cleared", caller.frames.at(-1).requests_out, []);
check("requester's outgoing details cleared", caller.frames.at(-1).requests_out_details, []);
check("target's incoming strings cleared", peer.frames.at(-1).requests_in, []);
check("target's incoming details cleared", peer.frames.at(-1).requests_in_details, []);
check("declined request removed from SQL", hub.requestExists("player_11111111", "player_22222222"), false);

await send(caller, { t: "add", name: "Player_22222222" });
await send(peer, { t: "accept", name: "Player_11111111" });
sockets.splice(sockets.indexOf(peer), 1);
for (const kind of ["p2p", "sync", "askjoin"]) {
  caller.frames.length = peer.frames.length = 0;
  await send(caller, { t: "call_invite", to: "pLaYeR_22222222", kind });
  check(`${kind}: only failure reaches caller`, caller.frames.map((f) => f.t), ["call_end"]);
  const failure = caller.frames[0];
  check(`${kind}: requested handle and kind preserved`, [failure.to, failure.kind], ["pLaYeR_22222222", kind]);
  check(`${kind}: offline reason and message preserved`, [failure.reason, failure.message], ["offline", "Player_22222222 is offline."]);
  check(`${kind}: recipient identity enriched`, [failure.to_uid, failure.to_minecraft_username], ["000000000002", "RubyFox"]);
  check(`${kind}: room has been cleaned up`, hub.callMembers(failure.room), []);
  check(`${kind}: offline peer receives nothing`, peer.frames, []);
}
sockets.push(peer);
caller.frames.length = peer.frames.length = 0;
await send(caller, { t: "call_invite", to: "Player_22222222", kind: "sync" });
check("online invite still reaches both sides", [caller.frames.at(-1).t, peer.frames.at(-1).t], ["call_invite", "call_invite"]);
check("online invite kind unchanged", [caller.frames.at(-1).kind, peer.frames.at(-1).kind], ["sync", "sync"]);

await send(caller, { t: "dm", to: "Player_22222222", text: "first", id: "m1" });
await send(peer, { t: "dm", to: "Player_11111111", text: "second", id: "m2" });
await send(peer, { t: "metadata", minecraft_username: "CurrentRuby" });
caller.frames.length = peer.frames.length = 0;
await send(caller, { t: "history", peer: "Player_22222222" });
const history = caller.frames.at(-1);
check("history retains peer routing handle", [history.t, history.peer], ["history", "Player_22222222"]);
check("history envelope carries current peer identity", [history.peer_uid, history.peer_minecraft_username], ["000000000002", "CurrentRuby"]);
check("history preserves message ordering and legacy fields", history.messages.map(({ from, text, id }) => ({ from, text, id })), [
  { from: "Player_11111111", text: "first", id: "m1" },
  { from: "Player_22222222", text: "second", id: "m2" },
]);
check("each sender carries its own current metadata", history.messages.map((m) => [m.from_uid, m.from_minecraft_username]), [
  ["000000000001", "BlueFox"], ["000000000002", "CurrentRuby"],
]);
check("history is not broadcast to peer", peer.frames, []);

await send(caller, { t: "group_new", name: "Room", members: ["Player_22222222"] });
const gid = caller.frames.find((f) => f.t === "group_created").gid;
hub.store(`g:${gid}`, "player_22222222", "OldDisplay", "known", 1, "g1");
hub.store(`g:${gid}`, "legacy_sender", "LegacySender", "older", 2, "g2");
await send(caller, { t: "history", gid });
const groupHistory = caller.frames.at(-1);
check("group history retains gid without inventing peer", [groupHistory.gid, "peer_uid" in groupHistory, "peer_minecraft_username" in groupHistory], [gid, false, false]);
check("sender lookup uses stored sender not historical display", groupHistory.messages[0], {
  from: "OldDisplay", text: "known", ts: 1, id: "g1",
  from_uid: "000000000002", from_minecraft_username: "CurrentRuby",
});
check("unknown sender retains legacy shape without empty metadata", groupHistory.messages[1], {
  from: "LegacySender", text: "older", ts: 2, id: "g2",
});
sql.exec("UPDATE names SET minecraft_username=NULL WHERE name=?", "player_22222222");
await send(caller, { t: "history", peer: "Player_22222222" });
const partialHistory = caller.frames.at(-1);
check("unknown peer username stays absent while known UID remains", [partialHistory.peer_uid, "peer_minecraft_username" in partialHistory], ["000000000002", false]);
check("unknown sender username stays absent while known UID remains", [partialHistory.messages[1].from_uid, "from_minecraft_username" in partialHistory.messages[1]], ["000000000002", false]);
db.close();
console.log(`\n${passed} passed, 0 failed`);
