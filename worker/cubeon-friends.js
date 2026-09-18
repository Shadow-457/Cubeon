/**
 * Cubeon friends API - Cloudflare Worker + a single Durable Object (free tier,
 * no VPS, nothing for the owner to host).
 *
 * The realtime social layer: a unique Cubeon name, a friends list, presence
 * (online/offline + which Minecraft version each friend is in), direct and
 * group chat, and voice-call signalling.
 *
 *   POST /claim        claim or re-verify a Cubeon name   {name, secret}
 *   GET  /name/<name>  does this name exist / is it online
 *   GET  /uid/<uid>    resolve a 12-digit Cubeon ID to its name / presence
 *   POST /pubkey       publish this name's E2EE public key {name, secret, pubkey}
 *   GET  /pubkey/<name>  fetch a friend's E2EE public key (opaque to us)
 *   GET  /ws           WebSocket upgrade - the realtime channel
 *   GET  /health       plain-text OK, for debugging by hand
 *
 * ------------------------------------------------------------------------
 * THE 12-DIGIT ID (uid)
 *
 * A Cubeon name is human-readable but easy to typo, and the launcher's Chat
 * surface now hands out a stable numeric ID instead. The first account ever
 * registered gets 000000000001, the next 000000000002, and so on. It is
 * allocated here, by the one global Durable Object, so it is unique and
 * sequential across every Cubeon install - never derived from the secret, which
 * is why the same account keeps its ID across a rename (the row is updated, not
 * re-created). Names still key the friend graph internally; the ID is just the
 * public handle friends type.
 *
 * ------------------------------------------------------------------------
 * WHY A DURABLE OBJECT AND NOT KV
 *
 * The sibling Workers (skins, invites) use KV because their traffic is a
 * request here and there. This one can't: presence and chat are *live*, and
 * KV's free tier allows ~1000 writes/day across every Cubeon user combined - a
 * single 30-second presence heartbeat would spend 2880/day on its own.
 *
 * A Durable Object holds the live WebSocket connections in one place and keeps
 * its own state in a per-object SQLite database. That storage is not metered
 * like KV writes, so chat history and the friend graph cost nothing against the
 * KV budget. One global DO ("global") is the whole backend; at Cubeon's scale
 * (a few hundred concurrent) a single object is plenty, and the name registry
 * could move to KV later to shard it if that ever changes.
 *
 * Free-tier notes baked into this file:
 *   - The DO is declared with `new_sqlite_classes` in wrangler (SQLite storage
 *     is the backend available on the free plan; the older key-value DO storage
 *     is not).
 *   - It uses the WebSocket *Hibernation* API (acceptWebSocket +
 *     webSocketMessage/Close handlers), so an idle DO with connections open is
 *     evicted from memory and stops accruing duration charges, then wakes on
 *     the next frame. Nothing realtime is kept in instance memory - every
 *     lookup derives from getWebSockets() + SQL, both of which survive
 *     hibernation.
 *
 * ------------------------------------------------------------------------
 * IDENTITY - THE SAME TRICK AS INVITE CODES
 *
 * Cracked accounts have no identity, so a friends list keyed on an in-game
 * username would be built on names anyone can impersonate. Instead a Cubeon
 * name is owned by a capability secret: the launcher generates 256 bits, sends
 * it once, and this Worker stores only its SHA-256. Every later connection must
 * present the same secret. No signup, nothing to phish, and a database dump
 * leaks no secret that can be replayed. A fresh name has no rightful owner to
 * impersonate, so ownership is created at claim time - exactly the escape hatch
 * cubeon/invites.js documents for invite codes.
 *
 * ------------------------------------------------------------------------
 * PROTOCOL PARITY
 *
 * Every message `t` (type) string and the name format below must stay identical
 * to cubeon/friends.py. tools/test_friends.py reads this file and asserts they
 * agree, because a silent divergence would mean the launcher speaks a dialect
 * this server rejects, and only in production.
 * ------------------------------------------------------------------------
 */

// Must equal cubeon/friends.py `_NAME_RE`. Names are matched case-insensitively
// (stored canonical lower-case, displayed in their first-claimed casing).
const NAME_RE = /^[A-Za-z0-9_]{3,16}$/;

// Must equal cubeon/friends.py `_RESERVED`.
const RESERVED = new Set(["cubeon", "admin", "system", "server", "moderator", "mod", "staff"]);

// A Cubeon ID is exactly 12 decimal digits, zero-padded (000000000001...).
// Must equal cubeon/friends.py `_UID_RE`.
const UID_RE = /^[0-9]{12}$/;
const UID_WIDTH = 12;

// Message types - mirror of the T_* constants in cubeon/friends.py.
const T = {
  HELLO: "hello", ADD: "add", REMOVE: "remove", ACCEPT: "accept",
  DECLINE: "decline", DM: "dm", GROUP_NEW: "group_new", GROUP_MSG: "group_msg",
  GROUP_LEAVE: "group_leave", VERSION: "version", STATUS: "status",
  HISTORY: "history", CALL_INVITE: "call_invite", CALL_ACCEPT: "call_accept",
  CALL_DECLINE: "call_decline", CALL_END: "call_end", SIGNAL: "signal",
  TYPING: "typing", METADATA: "metadata",
  // server -> client
  HELLO_OK: "hello_ok", ERROR: "error", ROSTER: "roster", PRESENCE: "presence",
  REQUEST: "request", FRIEND_ADDED: "friend_added", FRIEND_REMOVED: "friend_removed",
  GROUP_CREATED: "group_created", GROUP_UPDATE: "group_update", SYSTEM: "system",
};

const MAX_TEXT = 2000;        // one chat message
export const MAX_DM_ENVELOPE_CHARS = 2000;
const MAX_GROUP_NAME = 32;
const MAX_GROUP_MEMBERS = 50;
const HISTORY_KEEP = 50;      // messages retained per conversation
const MAX_BODY_BYTES = 1024;  // /claim body - a handful of short fields

// --------------------------------------------------------------------- Worker

// decodeURIComponent throws URIError on a malformed escape sequence, and an
// unhandled throw in fetch() surfaces as a Cloudflare "error 1101" page.
// A URL can't contain a raw invalid %-sequence (URL parsing percent-encodes
// it), so falling back to the encoded pathname is always safe to route on -
// worst case the pattern match 404s, which is the right answer for garbage.
function safePathname(url) {
  try {
    return decodeURIComponent(url.pathname);
  } catch {
    return url.pathname;
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = safePathname(url);

    if (path === "/health") {
      return new Response("cubeon-friends ok\n", {
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }

    // Everything stateful lives in the one global hub object. Forwarding the
    // request wholesale keeps the Worker a thin router and the DO the single
    // source of truth for names, the friend graph, chat, and presence.
    if (path === "/claim" || path === "/pubkey" || path.startsWith("/name/") ||
        path.startsWith("/uid/") || path.startsWith("/pubkey/") || path === "/ws") {
      const id = env.HUB.idFromName("global");
      return env.HUB.get(id).fetch(request);
    }

    return new Response("Not Found", { status: 404 });
  },
};

// ------------------------------------------------------------ Durable Object

// Sliding-window rate limiter (pure, unit-testable without a Durable Object):
// key -> array of timestamps inside the window. In-memory only, per DO
// isolate - good enough for abuse damping, deliberately not another table.
export function limiterAllow(map, key, max, windowMs, now = Date.now()) {
  let arr = map.get(key);
  if (!arr) { arr = []; map.set(key, arr); }
  while (arr.length && now - arr[0] > windowMs) arr.shift();
  if (arr.length >= max) return false;
  arr.push(now);
  return true;
}

export class Hub {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.sql = ctx.storage.sql;
    this.rl = new Map();  // limiter state, see limiterAllow above
    // CREATE ... IF NOT EXISTS is idempotent and cheap, so running it on every
    // wake is fine and avoids a separate migration step. SQLite exec is
    // synchronous, so no blockConcurrencyWhile is needed to order it.
    this.sql.exec(`
      CREATE TABLE IF NOT EXISTS names (
        name TEXT PRIMARY KEY, display TEXT, secret_hash TEXT, uuid TEXT,
        uid INTEGER, blocked INTEGER DEFAULT 0, created INTEGER
      );
      CREATE TABLE IF NOT EXISTS friends (owner TEXT, friend TEXT, PRIMARY KEY (owner, friend));
      CREATE TABLE IF NOT EXISTS requests (requester TEXT, target TEXT, PRIMARY KEY (requester, target));
      CREATE TABLE IF NOT EXISTS groups (gid TEXT PRIMARY KEY, name TEXT, created INTEGER);
      CREATE TABLE IF NOT EXISTS group_members (gid TEXT, member TEXT, PRIMARY KEY (gid, member));
      CREATE TABLE IF NOT EXISTS messages (
        conv TEXT, sender TEXT, display TEXT, text TEXT, ts INTEGER, mid TEXT
      );
      CREATE INDEX IF NOT EXISTS messages_conv ON messages (conv, ts);
      CREATE TABLE IF NOT EXISTS calls (room TEXT, member TEXT, PRIMARY KEY (room, member));
    `);
    // The E2EE public key column is opaque to this Worker - it just stores and
    // serves it. Older DOs already have a `names` table without the column, so
    // CREATE ... IF NOT EXISTS won't add it; a guarded ALTER is the migration.
    try {
      this.sql.exec("ALTER TABLE names ADD COLUMN pubkey TEXT");
    } catch (e) { /* already added */ }
    // Same migration pattern for the numeric ID. New DOs get it in the CREATE
    // above; an older live DO gets the column here and its rows are assigned on
    // next sight (ensureUid), so a deploy never strands an existing account.
    try {
      this.sql.exec("ALTER TABLE names ADD COLUMN uid INTEGER");
    } catch (e) { /* already added */ }
    if (!this.sql.exec("PRAGMA table_info(names)").toArray()
        .some((column) => column.name === "minecraft_username")) {
      this.sql.exec("ALTER TABLE names ADD COLUMN minecraft_username TEXT");
    }
  }

  async fetch(request) {
    const url = new URL(request.url);
    const path = safePathname(url);

    if (path === "/claim") {
      if (request.method !== "POST") return methodNotAllowed("POST");
      return this.httpClaim(request);
    }
    if (path === "/pubkey") {
      if (request.method !== "POST") return methodNotAllowed("POST");
      return this.httpPubkey(request);
    }
    if (path.startsWith("/name/")) {
      return this.httpNameLookup(path.slice("/name/".length).toLowerCase());
    }
    if (path.startsWith("/uid/")) {
      return this.httpUidLookup(path.slice("/uid/".length));
    }
    if (path.startsWith("/pubkey/")) {
      return this.httpPubkeyLookup(path.slice("/pubkey/".length).toLowerCase());
    }
    if (path === "/ws") {
      if (request.headers.get("Upgrade") !== "websocket") {
        return new Response("Expected WebSocket", { status: 426 });
      }
      const pair = new WebSocketPair();
      const [client, server] = [pair[0], pair[1]];
      // Hibernation accept: the socket survives the DO being evicted from
      // memory, and we authenticate in the first message (the `hello` frame)
      // rather than the URL, so the secret never lands in a request log.
      this.ctx.acceptWebSocket(server);
      // Stash the caller IP on the socket BEFORE any hello: onHello needs it
      // to rate-limit pre-auth connection attempts (an unauthenticated flood
      // of hellos each costs a SHA-256 plus, for unknown names, a claim
      // row). The attachment is the only per-socket storage that survives
      // hibernation; the real identity overwrites this on successful hello,
      // so the IP is merged in there too.
      server.serializeAttachment({
        ip: request.headers.get("CF-Connecting-IP") || "unknown",
      });
      return new Response(null, { status: 101, webSocket: client });
    }
    return new Response("Not Found", { status: 404 });
  }

  // ----------------------------------------------------------- HTTP handlers

  async httpClaim(request) {
    const body = await readJson(request);
    if (body === null) return problem(400, "bad_body");
    const display = body.name;
    const secret = body.secret;
    const canon = canonName(display);
    if (!canon || RESERVED.has(canon)) return problem(400, "bad_name");
    if (typeof secret !== "string" || secret.length < 16 || secret.length > 256) {
      return problem(400, "bad_body");
    }

    const hash = await sha256Hex(secret);
    const row = this.nameRow(canon);
    if (row) {
      if (row.blocked) return problem(403, "blocked");
      // Re-claiming a name this machine already owns is how it's re-verified.
      if (!constantTimeEqual(row.secret_hash || "", hash)) {
        return problem(409, "name_taken");
      }
      const uid = this.ensureUid(row);
      return json({ ok: true, name: row.display, uuid: row.uuid, uid: uidStr(uid) });
    }

    // Fresh name - ownership is created here. The offline UUID is derived from
    // the name identically on both sides (cubeon/config.py offline_uuid); the
    // client sends its own so the server never needs MD5, which Web Crypto in
    // Workers doesn't provide. It's not a secret - anyone can compute it from
    // the public name - so storing the client-sent value is safe.
    const uuid = cleanUuid(body.uuid);
    const uid = this.nextUid();
    try {
      this.sql.exec(
        "INSERT INTO names (name, display, secret_hash, uuid, uid, created) VALUES (?, ?, ?, ?, ?, ?)",
        canon, display, hash, uuid, uid, nowSeconds(),
      );
    } catch (e) {
      // A concurrent /claim (or claim-on-connect) for the same fresh name won
      // the PRIMARY KEY: both requests interleave at the sha256Hex await and
      // both see "no row". Same secret => the same machine double-submitting,
      // answer ok; different secret => the name was just taken, 409 - either
      // way NOT an unhandled 500.
      const winner = this.nameRow(canon);
      if (!winner) throw e;
      if (!constantTimeEqual(winner.secret_hash || "", hash)) {
        return problem(409, "name_taken");
      }
      return json({ ok: true, name: winner.display, uuid: winner.uuid,
                    uid: uidStr(this.ensureUid(winner)) });
    }
    return json({ ok: true, name: display, uuid, uid: uidStr(uid) });
  }

  // Stores (or replaces) the E2EE public key a name advertises for encrypted
  // DMs. Authenticated exactly like /claim: the name + owning secret prove the
  // caller is the account's rightful holder. The key is base64, opaque, and
  // stored as-is - nothing here can or should read what it encrypts.
  async httpPubkey(request) {
    const body = await readJson(request);
    if (body === null) return problem(400, "bad_body");
    const canon = canonName(body.name);
    const pubkey = body.pubkey;
    const secret = body.secret;
    if (!canon) return problem(400, "bad_name");
    if (typeof pubkey !== "string" || pubkey.length < 16 || pubkey.length > 512) {
      return problem(400, "bad_body");
    }
    const row = this.nameRow(canon);
    if (!row) return problem(404, "no_such_name");
    if (row.blocked) return problem(403, "blocked");
    const hash = await sha256Hex(String(secret));
    if (!constantTimeEqual(row.secret_hash || "", hash)) {
      return problem(403, "not_yours");
    }
    this.sql.exec("UPDATE names SET pubkey=? WHERE name=?", pubkey, canon);
    return json({ ok: true, name: row.display });
  }

  // The public key a friend needs before anyone can write them an encrypted DM.
  // A 200 with pubkey "" means the name exists but has never published a key.
  httpPubkeyLookup(canon) {
    if (!NAME_RE.test(canon)) return new Response("Not Found", { status: 404 });
    const row = this.nameRow(canon);
    if (!row || row.blocked) return new Response("Not Found", { status: 404 });
    return json({ name: row.display, pubkey: row.pubkey || "" });
  }

  httpNameLookup(canon) {
    if (!NAME_RE.test(canon)) return new Response("Not Found", { status: 404 });
    const row = this.nameRow(canon);
    if (!row || row.blocked) return new Response("Not Found", { status: 404 });
    return json({ ...this.identityOf(canon), online: this.isOnline(canon) });
  }

  // Resolves the public 12-digit ID a user typed to the account behind it. The
  // client uses this to reject a typo'd ID before sending a request nobody can
  // receive, and to show the friend's name once it resolves.
  httpUidLookup(raw) {
    const uid = uidInt(raw);
    if (uid === null) return new Response("Not Found", { status: 404 });
    const row = this.nameByUid(uid);
    if (!row || row.blocked) return new Response("Not Found", { status: 404 });
    return json({ ...this.identityOf(row.name), online: this.isOnline(row.name) });
  }

  // ------------------------------------------------------ WebSocket handlers

  async webSocketMessage(ws, raw) {
    let msg;
    try {
      msg = JSON.parse(typeof raw === "string" ? raw : "");
    } catch {
      return;
    }
    if (!msg || typeof msg !== "object") return;

    // Until authenticated, only a hello is accepted.
    const att = ws.deserializeAttachment();
    if (!att || !att.name) {
      if (msg.t === T.HELLO) return this.onHello(ws, msg);
      return;
    }
    const me = att.name;      // canonical
    const myDisplay = att.display;

    // Abuse guard: an authenticated socket that floods ANY frame gets its
    // excess dropped silently. 120/min is far above anything a real client
    // generates (the mod sends a few frames a second at absolute peak) but
    // caps the cost of a malicious or runaway client to the DO.
    if (!this.allow(`frames:${me}`, 120, 60_000)) return;

    switch (msg.t) {
      case T.ADD:
        // Friend requests are the frame that costs Durable-Object work
        // (writes + notifications to the target), so they get their own,
        // tighter budget: 10/min, with a visible error so a spam-clicking
        // human isn't left wondering.
        if (!this.allow(`add:${me}`, 10, 60_000)) {
          ws.send(jstr(T.ERROR, { code: "rate_limited",
                                  message: "Too many friend requests too fast - try again in a minute." }));
          return;
        }
        return this.onAdd(me, myDisplay, msg);
      case T.REMOVE: return this.onRemove(me, msg);
      case T.ACCEPT: return this.onAccept(me, myDisplay, msg);
      case T.DECLINE: return this.onDecline(me, msg);
      case T.DM: return this.onDm(ws, me, myDisplay, msg);
      case T.GROUP_NEW: return this.onGroupNew(me, myDisplay, msg);
      case T.GROUP_MSG: return this.onGroupMsg(ws, me, myDisplay, msg);
      case T.GROUP_LEAVE: return this.onGroupLeave(me, msg);
      case T.METADATA: return this.onMetadata(me, msg);
      case T.VERSION: return this.onVersion(ws, me, msg);
      case T.STATUS: return this.onStatus(ws, me, msg);
      case T.HISTORY: return this.onHistory(ws, me, msg);
      case T.CALL_INVITE: return this.onCallInvite(me, myDisplay, msg);
      case T.CALL_ACCEPT: return this.onCallSignalControl(me, myDisplay, msg, T.CALL_ACCEPT);
      case T.CALL_DECLINE: return this.onCallSignalControl(me, myDisplay, msg, T.CALL_DECLINE);
      case T.CALL_END: return this.onCallEnd(me, myDisplay, msg);
      case T.SIGNAL: return this.onSignal(me, myDisplay, msg);
      case T.TYPING: return this.onTyping(me, myDisplay, msg);
      default: return;
    }
  }

  async webSocketClose(ws) {
    const att = ws.deserializeAttachment();
    if (att && att.name && !this.isOnline(att.name)) {
      // That was this user's last socket - tell their friends they went dark.
      this.broadcastPresence(att.name);
    }
  }

  async webSocketError(ws) { /* close handler does the presence cleanup */ }

  // Sliding-window limiter: true if this key has budget left. Delegates to
  // the exported pure function so tests don't need a Durable Object.
  allow(key, max, windowMs, now = Date.now()) {
    return limiterAllow(this.rl, key, max, windowMs, now);
  }

  // --------------------------------------------------------------- actions

  async onHello(ws, msg) {
    const display = msg.name;
    const secret = msg.secret;
    const canon = canonName(display);
    if (!canon || RESERVED.has(canon) || typeof secret !== "string") {
      ws.send(jstr(T.ERROR, { code: "bad_name", message: "That name isn't allowed." }));
      return ws.close(1008, "bad_name");
    }
    // Pre-auth flood gate. Everything above this line is free, but below it
    // every attempt costs a SHA-256, and an unknown name costs a claim row
    // (names are never deleted, so a flood grows the table forever). 30 per
    // IP per 10 minutes is far above any real client - one claim per install,
    // one hello per reconnect - while capping what an anonymous socket can
    // burn. The IP rides the attachment set at upgrade time.
    const pre = ws.deserializeAttachment() || {};
    const ip = typeof pre.ip === "string" ? pre.ip : "unknown";
    if (!this.allow(`hello:${ip}`, 30, 10 * 60_000)) {
      ws.send(jstr(T.ERROR, { code: "rate_limited",
                              message: "Too many connection attempts - try again in a few minutes." }));
      return ws.close(1013, "rate_limited");
    }
    const hash = await sha256Hex(secret);
    let row = this.nameRow(canon);
    if (row && row.blocked) {
      ws.send(jstr(T.ERROR, { code: "blocked", message: "This name was blocked." }));
      return ws.close(1008, "blocked");
    }
    if (row) {
      if (!constantTimeEqual(row.secret_hash || "", hash)) {
        ws.send(jstr(T.ERROR, { code: "not_yours", message: "That name belongs to another computer." }));
        return ws.close(1008, "not_yours");
      }
    } else {
      // Claim-on-connect, so a client that reached the WS without a prior
      // /claim still ends up with a consistent, owned identity.
      const uuid = cleanUuid(msg.uuid);
      const uid = this.nextUid();
      try {
        this.sql.exec(
          "INSERT INTO names (name, display, secret_hash, uuid, uid, created) VALUES (?, ?, ?, ?, ?, ?)",
          canon, display, hash, uuid, uid, nowSeconds(),
        );
      } catch (e) {
        // Two hellos racing the same fresh name interleave at the sha256Hex
        // await above; the loser hits the names PRIMARY KEY. Re-read and
        // fall through to the row-existed semantics instead of throwing out
        // of the socket handler (an unhandled exception here drops the
        // socket with a 1101-style error and strands the client until its
        // next reconnect).
        row = this.nameRow(canon);
        if (!row || row.blocked || !constantTimeEqual(row.secret_hash || "", hash)) {
          ws.send(jstr(T.ERROR, { code: "not_yours", message: "That name belongs to another computer." }));
          return ws.close(1008, "not_yours");
        }
      }
      if (!row) row = this.nameRow(canon);
    }
    const uid = this.ensureUid(row);

    const wasOnline = this.isOnline(canon);
    ws.serializeAttachment({
      ip,                      // keep the upgrade-time IP for later hello retries
      name: canon,
      display: row.display,
      version: typeof msg.version === "string" ? msg.version : null,
      status: typeof msg.status === "string" ? msg.status : "online",
    });
    const metadataChanged = this.updateMetadata(canon, msg.minecraft_username);
    ws.send(jstr(T.HELLO_OK, { ...this.identityOf(canon), uuid: row.uuid, uid: uidStr(uid) }));
    if (metadataChanged) this.broadcastMetadata(canon);
    this.sendRoster(canon);
    // First socket for this user => let friends see them come online.
    if (!wasOnline) this.broadcastPresence(canon);
  }

  onAdd(me, myDisplay, msg) {
    // The Chat surface sends a 12-digit ID; the in-game mod still sends a name.
    // Both resolve to the same canonical name the friend graph is keyed on.
    let other = null;
    if (typeof msg.uid === "string") {
      const uid = uidInt(msg.uid);
      const target = uid === null ? null : this.nameByUid(uid);
      // A moderation-blocked account is treated as nonexistent everywhere
      // else (/name/, /uid/ 404 it) - the in-game mod's name path let it
      // through, so gate both paths identically.
      if (!target || target.blocked) {
        return this.sendTo(me, T.SYSTEM,
          { text: `No Cubeon user with ID ${msg.uid}.` });
      }
      other = target.name;
    } else {
      other = canonName(msg.name);
      if (!other || other === me) return;
      const target = this.nameRow(other);
      if (!target || target.blocked) return this.sendTo(me, T.SYSTEM, { text: `No Cubeon user named "${msg.name}".` });
    }
    if (!other || other === me) return;
    if (this.areFriends(me, other)) return;
    // A request the other way already exists => this is a mutual add, so just
    // accept it instead of stacking a second pending request.
    if (this.requestExists(other, me)) return this.onAccept(me, myDisplay, { name: other });

    this.sql.exec(
      "INSERT OR IGNORE INTO requests (requester, target) VALUES (?, ?)", me, other);
    this.sendRoster(me);
    this.sendTo(other, T.REQUEST, { from: myDisplay, from_uid: uidStr(this.uidOf(me)) });
    this.sendRoster(other);
  }

  onAccept(me, myDisplay, msg) {
    const other = canonName(msg.name);
    if (!other || !this.requestExists(other, me)) return;
    this.sql.exec("DELETE FROM requests WHERE requester=? AND target=?", other, me);
    this.sql.exec("DELETE FROM requests WHERE requester=? AND target=?", me, other);
    this.sql.exec("INSERT OR IGNORE INTO friends (owner, friend) VALUES (?, ?)", me, other);
    this.sql.exec("INSERT OR IGNORE INTO friends (owner, friend) VALUES (?, ?)", other, me);
    this.sendTo(other, T.FRIEND_ADDED, { name: myDisplay });
    this.sendRoster(me);
    this.sendRoster(other);
    // Each now sees the other's live presence without waiting for a change.
    this.sendTo(me, T.PRESENCE, this.presenceOf(other));
    this.sendTo(other, T.PRESENCE, this.presenceOf(me));
  }

  onDecline(me, msg) {
    const other = canonName(msg.name);
    if (!other) return;
    this.sql.exec("DELETE FROM requests WHERE requester=? AND target=?", other, me);
    this.sendRoster(me);
    this.sendRoster(other);
  }

  onRemove(me, msg) {
    const other = canonName(msg.name);
    if (!other) return;
    this.sql.exec("DELETE FROM friends WHERE owner=? AND friend=?", me, other);
    this.sql.exec("DELETE FROM friends WHERE owner=? AND friend=?", other, me);
    this.sendTo(other, T.FRIEND_REMOVED, { name: this.displayOf(me) });
    this.sendRoster(me);
    this.sendRoster(other);
  }

  onDm(ws, me, myDisplay, msg) {
    const to = canonName(msg.to);
    if (typeof msg.text === "string" && msg.text.length > MAX_DM_ENVELOPE_CHARS) {
      ws.send(jstr(T.ERROR, { code: "dm_too_large",
                              message: "Message too long to send. Try a shorter one." }));
      return;
    }
    const text = typeof msg.text === "string" ? msg.text.trim() : null;
    // Refusals must reach the SENDER: the UI renders its own message
    // optimistically and only treats it as delivered when this echo comes
    // back, so a silent drop made a failed DM look like "sent but the other
    // person is ignoring me". Say why instead (the service toasts T.ERROR).
    if (!to) {
      ws.send(jstr(T.ERROR, { code: "dm_bad_recipient",
                              message: "That recipient name isn't valid." }));
      return;
    }
    if (!text) {
      ws.send(jstr(T.ERROR, { code: "dm_empty", message: "Empty message not sent." }));
      return;
    }
    if (!this.areFriends(me, to)) {
      ws.send(jstr(T.ERROR, { code: "dm_not_friends",
                              message: "You can only message friends - add them first." }));
      return;
    }
    const conv = dmConv(me, to);
    const ts = nowSeconds();
    const mid = typeof msg.id === "string" ? msg.id.slice(0, 32) : crypto.randomUUID();
    this.store(conv, me, myDisplay, text, ts, mid);
    const frame = { from: myDisplay, to: this.displayOf(to), text, ts, id: mid };
    this.sendTo(to, T.DM, frame);
    this.sendTo(me, T.DM, frame);  // echo so the sender's own thread confirms it
  }

  // A "friend is typing" hint. Deliberately ephemeral: never stored, never
  // echoed to the sender, and silently dropped if the target isn't a friend /
  // isn't in the group. If nobody's online to receive it, it simply evaporates
  // - sendTo already no-ops for offline names, so a typing frame costs nothing
  // and can never resurrect as stale history the way a DM would.
  onTyping(me, myDisplay, msg) {
    if (typeof msg.gid === "string") {
      const gid = msg.gid;
      if (!this.inGroup(gid, me)) return;
      const frame = { gid, from: myDisplay };
      for (const m of this.groupMembers(gid)) {
        if (m !== me) this.sendTo(m, T.TYPING, frame);
      }
      return;
    }
    const to = canonName(msg.to);
    if (!to || !this.areFriends(me, to)) return;
    this.sendTo(to, T.TYPING, { from: myDisplay });
  }

  onGroupNew(me, myDisplay, msg) {
    const gname = cleanText(msg.name, MAX_GROUP_NAME) || "Group";
    const wanted = Array.isArray(msg.members) ? msg.members : [];
    const members = new Set([me]);
    for (const m of wanted.slice(0, MAX_GROUP_MEMBERS)) {
      const c = canonName(m);
      if (c && this.areFriends(me, c)) members.add(c);  // can only group with friends
    }
    const gid = "g_" + crypto.randomUUID().slice(0, 12);
    const ts = nowSeconds();
    this.sql.exec("INSERT INTO groups (gid, name, created) VALUES (?, ?, ?)", gid, gname, ts);
    for (const m of members) {
      this.sql.exec("INSERT OR IGNORE INTO group_members (gid, member) VALUES (?, ?)", gid, m);
    }
    const info = this.groupInfo(gid);
    for (const m of members) {
      this.sendTo(m, T.GROUP_CREATED, info);
      this.sendRoster(m);
    }
  }

  onGroupMsg(ws, me, myDisplay, msg) {
    const gid = typeof msg.gid === "string" ? msg.gid : null;
    const text = cleanText(msg.text);
    if (!gid || !text || !this.inGroup(gid, me)) return;
    const ts = nowSeconds();
    const mid = typeof msg.id === "string" ? msg.id.slice(0, 32) : crypto.randomUUID();
    this.store("g:" + gid, me, myDisplay, text, ts, mid);
    const frame = { gid, from: myDisplay, text, ts, id: mid };
    for (const m of this.groupMembers(gid)) this.sendTo(m, T.GROUP_MSG, frame);
  }

  onGroupLeave(me, msg) {
    const gid = typeof msg.gid === "string" ? msg.gid : null;
    if (!gid || !this.inGroup(gid, me)) return;
    this.sql.exec("DELETE FROM group_members WHERE gid=? AND member=?", gid, me);
    const remaining = this.groupMembers(gid);
    if (remaining.length === 0) {
      // Nobody left - reclaim the room and its history.
      this.sql.exec("DELETE FROM groups WHERE gid=?", gid);
      this.sql.exec("DELETE FROM messages WHERE conv=?", "g:" + gid);
    } else {
      const info = this.groupInfo(gid);
      for (const m of remaining) {
        this.sendTo(m, T.GROUP_UPDATE, info);
        this.sendRoster(m);
      }
    }
    this.sendRoster(me);
  }

  updateMetadata(me, value) {
    const username = minecraftUsername(value);
    const row = this.nameRow(me);
    if (!username || !row || row.blocked || row.minecraft_username === username) return false;
    this.sql.exec("UPDATE names SET minecraft_username=? WHERE name=?", username, me);
    return true;
  }

  broadcastMetadata(me) {
    const peers = new Set([me, ...this.friendsOf(me)]);
    for (const row of this.sql.exec(
      "SELECT requester, target FROM requests WHERE requester=? OR target=?", me, me).toArray()) {
      peers.add(row.requester);
      peers.add(row.target);
    }
    for (const row of this.sql.exec(
      "SELECT member FROM group_members WHERE gid IN (SELECT gid FROM group_members WHERE member=?)", me).toArray()) {
      peers.add(row.member);
    }
    const metadata = this.identityOf(me);
    for (const peer of peers) this.sendTo(peer, T.METADATA, metadata);
  }

  onMetadata(me, msg) {
    if (this.updateMetadata(me, msg.minecraft_username)) this.broadcastMetadata(me);
  }

  onVersion(ws, me, msg) {
    const version = typeof msg.version === "string" ? msg.version.slice(0, 64) : null;
    this.updateAttachment(me, { version });
    this.broadcastPresence(me);
  }

  onStatus(ws, me, msg) {
    const status = typeof msg.status === "string" ? msg.status.slice(0, 16) : "online";
    this.updateAttachment(me, { status });
    this.broadcastPresence(me);
  }

  onHistory(ws, me, msg) {
    const knownIdentityFields = (canon, prefix) => Object.fromEntries(
      Object.entries(this.identityFields(canon, prefix)).filter(([, value]) => value));
    let conv = null, key = {};
    if (typeof msg.peer === "string") {
      const other = canonName(msg.peer);
      if (!other || !this.areFriends(me, other)) return;
      conv = dmConv(me, other);
      key = { peer: this.displayOf(other), ...knownIdentityFields(other, "peer") };
    } else if (typeof msg.gid === "string" && this.inGroup(msg.gid, me)) {
      conv = "g:" + msg.gid;
      key = { gid: msg.gid };
    } else {
      return;
    }
    // Newest HISTORY_KEEP messages, presented oldest-first for rendering.
    // A bare `ORDER BY ts ASC LIMIT ?` would return the OLDEST page - once a
    // conversation outgrew the retained window, a fresh backfill would show
    // exactly the stale prefix and never the recent messages (the trim in
    // store() keeps only the newest rows, so the oldest are the first that
    // should go). The subquery selects the newest first (rowid, projected as
    // `rid`, breaks ties for same-second messages so the trim and this read
    // agree), then the outer ORDER BY re-orders chronologically for the
    // client. rowid must be projected or the outer sort can't reference it.
    const rows = this.sql.exec(
      `SELECT display, text, ts, mid, sender FROM (
         SELECT display, text, ts, mid, sender, rowid AS rid FROM messages
         WHERE conv=? ORDER BY ts DESC, rowid DESC LIMIT ?
       ) ORDER BY ts ASC, rid ASC`,
      conv, HISTORY_KEEP,
    ).toArray();
    const messages = rows.map((r) => ({ from: r.display, text: r.text, ts: r.ts, id: r.mid,
      ...knownIdentityFields(r.sender, "from") }));
    ws.send(jstr(T.HISTORY, { ...key, messages }));
  }

  // --------------------------------------------------------- voice signalling
  // The server only relays. Room membership is tracked in SQL so it survives a
  // hibernation between two signalling frames; the actual audio negotiation
  // rides opaque `signal` payloads the server never inspects.

  onCallInvite(me, myDisplay, msg) {
    const to = canonName(msg.to);
    if (!to || !this.areFriends(me, to)) return;
    // Each invite mints a room row (calls table) even if the receiver never
    // answers; unbounded inviting would grow that table without bound, so
    // invites share the same abuse budget as friend requests.
    if (!this.allow(`call:${me}`, 10, 60_000)) {
      return this.sendTo(me, T.SYSTEM,
        { text: "Too many call invites too fast - try again in a minute." });
    }
    const room = "r_" + crypto.randomUUID().slice(0, 12);
    this.sql.exec("INSERT OR IGNORE INTO calls (room, member) VALUES (?, ?)", room, me);
    this.sql.exec("INSERT OR IGNORE INTO calls (room, member) VALUES (?, ?)", room, to);
    if (!this.isOnline(to)) {
      this.sql.exec("DELETE FROM calls WHERE room=?", room);
      return this.sendTo(me, T.CALL_END, { room, reason: "offline",
        to: msg.to, kind: typeof msg.kind === "string" ? msg.kind.slice(0, 32) : null,
        message: `${this.displayOf(to)} is offline.` });
    }
    // ``kind`` is optional and intentionally opaque to the Worker. It lets
    // room-based features (currently voice and P2P worlds) tell the receiver
    // what the invite is for before the room is accepted.
    const kind = typeof msg.kind === "string" ? msg.kind.slice(0, 32) : null;
    const invite = { room, from: myDisplay };
    const outgoing = { room, to: this.displayOf(to), outgoing: true };
    if (kind) { invite.kind = kind; outgoing.kind = kind; }
    this.sendTo(to, T.CALL_INVITE, invite);
    this.sendTo(me, T.CALL_INVITE, outgoing);
  }

  onCallSignalControl(me, myDisplay, msg, type) {
    const room = typeof msg.room === "string" ? msg.room : null;
    if (!room || !this.inCall(room, me)) return;
    for (const m of this.callMembers(room)) {
      if (m !== me) this.sendTo(m, type, { room, from: myDisplay });
    }
    if (type === T.CALL_DECLINE) this.sql.exec("DELETE FROM calls WHERE room=?", room);
  }

  onCallEnd(me, myDisplay, msg) {
    const room = typeof msg.room === "string" ? msg.room : null;
    if (!room || !this.inCall(room, me)) return;
    this.sql.exec("DELETE FROM calls WHERE room=? AND member=?", room, me);
    const rest = this.callMembers(room);
    for (const m of rest) this.sendTo(m, T.CALL_END, { room, from: myDisplay });
    if (rest.length <= 1) this.sql.exec("DELETE FROM calls WHERE room=?", room);
  }

  onSignal(me, myDisplay, msg) {
    const room = typeof msg.room === "string" ? msg.room : null;
    const to = canonName(msg.to);
    if (!room || !to || !this.inCall(room, me) || !this.inCall(room, to)) return;
    this.sendTo(to, T.SIGNAL, { room, from: myDisplay, data: msg.data });
  }

  // ----------------------------------------------------------------- queries

  nameRow(canon) {
    const rows = this.sql.exec("SELECT * FROM names WHERE name=?", canon).toArray();
    return rows.length ? rows[0] : null;
  }

  nameByUid(uid) {
    const rows = this.sql.exec("SELECT * FROM names WHERE uid=?", uid).toArray();
    return rows.length ? rows[0] : null;
  }

  uidOf(canon) {
    const row = this.nameRow(canon);
    return row ? this.ensureUid(row) : null;
  }

  // The next free ID. The Durable Object is single-threaded per request, so a
  // MAX+1 here can't race another writer - and names are never deleted, so the
  // sequence only ever moves forward.
  nextUid() {
    const row = this.sql.exec(
      "SELECT COALESCE(MAX(uid), 0) + 1 AS n FROM names").toArray()[0];
    return row.n;
  }

  // Returns a row's ID, assigning one on first sight. Fresh rows are born with
  // an ID; this only matters for a row created before the column existed, so a
  // deploy can't strand an early account without one.
  ensureUid(row) {
    if (!row) return null;
    if (row.uid !== null && row.uid !== undefined) return row.uid;
    const uid = this.nextUid();
    this.sql.exec("UPDATE names SET uid=? WHERE name=?", uid, row.name);
    return uid;
  }

  displayOf(canon) {
    const row = this.nameRow(canon);
    return row ? row.display : canon;
  }

  areFriends(a, b) {
    return this.sql.exec(
      "SELECT 1 FROM friends WHERE owner=? AND friend=? LIMIT 1", a, b).toArray().length > 0;
  }

  requestExists(requester, target) {
    return this.sql.exec(
      "SELECT 1 FROM requests WHERE requester=? AND target=? LIMIT 1",
      requester, target).toArray().length > 0;
  }

  friendsOf(canon) {
    return this.sql.exec("SELECT friend FROM friends WHERE owner=?", canon)
      .toArray().map((r) => r.friend);
  }

  inGroup(gid, member) {
    return this.sql.exec(
      "SELECT 1 FROM group_members WHERE gid=? AND member=? LIMIT 1",
      gid, member).toArray().length > 0;
  }

  groupMembers(gid) {
    return this.sql.exec("SELECT member FROM group_members WHERE gid=?", gid)
      .toArray().map((r) => r.member);
  }

  groupInfo(gid) {
    const g = this.sql.exec("SELECT gid, name FROM groups WHERE gid=?", gid).toArray()[0];
    if (!g) return null;
    const members = this.groupMembers(gid);
    return { gid, name: g.name, members: members.map((m) => this.displayOf(m)),
      member_details: members.map((m) => this.identityOf(m)) };
  }

  inCall(room, member) {
    return this.sql.exec(
      "SELECT 1 FROM calls WHERE room=? AND member=? LIMIT 1",
      room, member).toArray().length > 0;
  }

  callMembers(room) {
    return this.sql.exec("SELECT member FROM calls WHERE room=?", room)
      .toArray().map((r) => r.member);
  }

  store(conv, sender, display, text, ts, mid) {
    this.sql.exec(
      "INSERT INTO messages (conv, sender, display, text, ts, mid) VALUES (?, ?, ?, ?, ?, ?)",
      conv, sender, display, text, ts, mid);
    // Keep only the most recent HISTORY_KEEP per conversation. Trimming on write
    // means history never grows without bound, and DO storage isn't KV-metered.
    this.sql.exec(
      `DELETE FROM messages WHERE conv=? AND rowid NOT IN (
         SELECT rowid FROM messages WHERE conv=? ORDER BY ts DESC LIMIT ?)`,
      conv, conv, HISTORY_KEEP);
  }

  // --------------------------------------------------------------- presence

  // A user is online iff at least one live socket carries their name. Derived
  // from getWebSockets() every time so it's correct across hibernation, where
  // any in-memory map would have been wiped.
  socketsFor(canon) {
    const out = [];
    for (const ws of this.ctx.getWebSockets()) {
      const att = ws.deserializeAttachment();
      if (att && att.name === canon) out.push(ws);
    }
    return out;
  }

  isOnline(canon) {
    return this.socketsFor(canon).length > 0;
  }

  presenceOf(canon) {
    const identity = this.identityOf(canon);
    const socks = this.socketsFor(canon);
    if (socks.length) {
      const att = socks[0].deserializeAttachment();
      return { ...identity, online: true, status: att.status || "online",
               version: att.version || null };
    }
    return { ...identity, online: false, status: "offline", version: null };
  }

  updateAttachment(canon, patch) {
    for (const ws of this.socketsFor(canon)) {
      const att = ws.deserializeAttachment() || {};
      ws.serializeAttachment({ ...att, ...patch });
    }
  }

  broadcastPresence(canon) {
    const p = this.presenceOf(canon);
    for (const f of this.friendsOf(canon)) this.sendTo(f, T.PRESENCE, p);
  }

  // ------------------------------------------------------------------- send

  identityOf(canon) {
    const row = this.nameRow(canon);
    return { name: row ? row.display : canon,
      uid: row ? uidStr(this.ensureUid(row)) : "",
      minecraft_username: row ? minecraftUsername(row.minecraft_username) : "" };
  }

  identityFields(canon, prefix) {
    const identity = this.identityOf(canon);
    return { [`${prefix}_uid`]: identity.uid,
      [`${prefix}_minecraft_username`]: identity.minecraft_username };
  }

  enrichIdentity(type, payload) {
    const out = { ...payload };
    if ([T.HELLO_OK, T.PRESENCE, T.METADATA, T.FRIEND_ADDED,
         T.FRIEND_REMOVED].includes(type) && canonName(out.name)) {
      Object.assign(out, this.identityOf(canonName(out.name)));
    }
    for (const key of ["from", "to", "peer"]) {
      const canon = canonName(out[key]);
      if (canon) Object.assign(out, this.identityFields(canon, key));
    }
    return out;
  }

  sendTo(canon, type, payload) {
    const frame = jstr(type, this.enrichIdentity(type, payload));
    for (const ws of this.socketsFor(canon)) {
      try { ws.send(frame); } catch { /* a dead socket close-handler will clean up */ }
    }
  }

  sendRoster(canon) {
    const friends = this.friendsOf(canon).map((f) => this.presenceOf(f));
    const requests_in_details = this.sql.exec(
      "SELECT requester FROM requests WHERE target=?", canon)
      .toArray().map((r) => this.presenceOf(r.requester));
    const requests_out_details = this.sql.exec(
      "SELECT target FROM requests WHERE requester=?", canon)
      .toArray().map((r) => this.presenceOf(r.target));
    const requests_in = requests_in_details.map((r) => r.name);
    const requests_out = requests_out_details.map((r) => r.name);
    const groups = this.sql.exec(
      "SELECT gid FROM group_members WHERE member=?", canon)
      .toArray().map((r) => this.groupInfo(r.gid)).filter(Boolean);
    this.sendTo(canon, T.ROSTER, { friends, requests_in, requests_out,
      requests_in_details, requests_out_details, groups });
  }
}

// ------------------------------------------------------------------- helpers

function minecraftUsername(value) {
  return typeof value === "string" && /^[A-Za-z0-9_]{3,16}$/.test(value)
    && value.length <= 16 && !value.includes("\n") ? value : "";
}

function canonName(name) {
  if (typeof name !== "string" || !NAME_RE.test(name)) return null;
  return name.toLowerCase();
}

// "42" / 42 / "000000000042" -> 42, or null if it isn't a 12-digit ID. Both the
// zero-padded form the launcher sends and a bare integer are accepted so the
// same helper serves /uid/<uid> and an `add {uid}` frame.
function uidInt(raw) {
  let s;
  if (typeof raw === "number" && Number.isInteger(raw)) {
    s = String(raw).padStart(UID_WIDTH, "0");
  } else if (typeof raw === "string") {
    s = raw.trim();
  } else {
    return null;
  }
  if (!UID_RE.test(s)) return null;
  const n = Number(s);
  return Number.isSafeInteger(n) ? n : null;
}

function uidStr(n) {
  if (n === null || n === undefined) return "";
  return String(n).padStart(UID_WIDTH, "0");
}

// The DM conversation key is the two canonical names sorted and joined, so both
// participants compute the same key regardless of who sent the message.
function dmConv(a, b) {
  return "d:" + [a, b].sort().join(":");
}

function cleanText(text, max = MAX_TEXT) {
  if (typeof text !== "string") return null;
  const trimmed = text.trim().slice(0, max);
  return trimmed.length ? trimmed : null;
}

// A client-sent offline UUID, or null. Not trusted for anything (it's a public
// function of the name); just format-checked so a garbage value can't be stored.
function cleanUuid(u) {
  return (typeof u === "string" && /^[0-9a-fA-F-]{32,36}$/.test(u)) ? u : null;
}

async function sha256Hex(input) {
  const bytes = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function readJson(request) {
  const declared = Number(request.headers.get("Content-Length") || "0");
  if (declared > MAX_BODY_BYTES) return null;
  let raw;
  try { raw = await request.text(); } catch { return null; }
  if (raw.length > MAX_BODY_BYTES) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch { return null; }
}

function nowSeconds() { return Math.floor(Date.now() / 1000); }

function json(body, cacheControl = "no-store") {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": cacheControl },
  });
}

function jstr(type, payload) {
  return JSON.stringify({ t: type, ...(payload || {}) });
}

function problem(status, error) {
  return new Response(JSON.stringify({ error }), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

function methodNotAllowed(allow) {
  return new Response("Method Not Allowed", { status: 405, headers: { Allow: allow } });
}
