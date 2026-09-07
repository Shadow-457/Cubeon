/**
 * Cubeon identity + skin API - Cloudflare Worker (free tier, no VPS).
 *
 * Dual-layer identity model: skins are anchored strictly to a persistent
 * UUID v4 (the one each launcher generates in auth_key.json and passes to
 * Minecraft via --uuid), while display names are ephemeral pointers.
 * Writes are authorized with each machine's private secret token, presented
 * as a Bearer header - only its SHA-256 is ever stored, so a leaked public
 * UUID alone lets nobody overwrite anyone's skin or pointer.
 *
 *   POST /api/heartbeat      {username, uuid}   Bearer -> claim/verify UUID,
 *                                               repoint username at it
 *   POST /api/skin           {uuid, model, skin} Bearer -> publish a sheet
 *   GET  /api/unlocks        Bearer -> this UUID's earned-milestone ids
 *   POST /api/unlocks        {uuid, milestones} Bearer -> merge unlocks
 *   GET  /skins/<name>.json  CustomSkinAPI lookup for CustomSkinLoader:
 *                            name -> UUID -> texture id (CSL then fetches
 *                            <root>/skins/textures/<id> for the bytes)
 *   GET  /skins/textures/<id> the PNG bytes CSL requests for one texture
 *   GET  /textures/<id>      the same PNG bytes, alias for hand-seeding
 *   POST /report             {username, reason?} flag a published skin
 *   GET  /health             plain-text OK, for debugging by hand
 *
 * Deployed at: https://cubeon-skins.hamza-457-shahbaz.workers.dev/
 * Bindings required: KV namespace bound as SKINS.
 *
 * ------------------------------------------------------------------------
 * KV LAYOUT
 *
 *   pointer:<lowercase-username> TEXT  the UUID this name currently points at
 *   skin:<uuid>                  JSON  {"id": "<content id>", "model": "default"|"slim"}
 *   owner:<uuid>                 TEXT  SHA-256 of the secret allowed to write
 *                                      this UUID (set on first write; TOFU)
 *   texture:<sha256>             TEXT  base64 of the PNG
 *   report:<uuid>                JSON  a pending moderation report (self-expiring)
 *   blocked:<uuid>               any   presence = moderation kill-switch
 *   unlocks:<uuid>               TEXT  comma-joined earned milestone ids
 *
 * The unlocks ledger is a single comma-joined string (not per-milestone
 * keys, no timestamps): a milestone unlock costs exactly ONE write ever -
 * the merge below only PUTs when the set GREW, so re-posting an identical
 * set, or a reinstall restoring its ledger from the server, costs zero
 * writes. Reads are free; the launcher caches them anyway.
 *
 * The plan's `skin:` value is a bare content id; we store {"id","model"} so
 * the CSL payload can put the id under the right key ("default" vs "slim")
 * without a second KV read - slim skins served as "default" render with 4px
 * arms, which is exactly the bug that field prevents. The id, never a URL, is
 * what goes in the profile: CSL resolves textures as `root + "textures/" +
 * <id>`, so a URL value makes it fetch a double-prefixed path and drop the
 * texture.
 *
 * Textures are stored base64-as-text rather than binary on purpose: it means a
 * skin can be pasted straight into the KV dashboard by hand, with no wrangler
 * and no Node install. Skins are 2-8 KB, so the ~33% base64 overhead is
 * irrelevant against KV's 25 MB value limit.
 *
 * Usernames are lowercased for pointer keys because CustomSkinAPI lookups are
 * case-insensitive, while the profile response echoes what was asked for.
 * ------------------------------------------------------------------------
 */

/**
 * The Cubeon cape, inlined as base64 (269 bytes).
 *
 * Every Cubeon user gets this cape - it is the launcher's main growth loop
 * ("what cape is that?" -> "what launcher is that?"). It is inlined rather
 * than stored in KV because it is by far the most-requested texture: one
 * fetch per player per session. Inlining keeps it at zero KV reads, which
 * matters against the free tier's 100k reads/day.
 *
 * DO NOT EDIT THESE TWO CONSTANTS BY HAND. Run `python tools/make_cape.py` -
 * it regenerates the PNG and rewrites both values here. Transcribing base64
 * manually corrupted one character the first time it was tried, which serves
 * as a broken PNG that only reveals itself in-game. CAPE_ID must stay equal
 * to the file's real sha256 so the texture is content-addressed and safe to
 * cache immutably.
 */
const CAPE_B64 =
  "iVBORw0KGgoAAAANSUhEUgAAAEAAAAAgCAYAAACinX6EAAAA1ElEQVR4nO3XMQrCMBQG4L/FK3kDZ8ce" +
  "wN0ziGtXOzh5BnEM8QQuQgUXTyB4Bp0sCS8KhTRP0/+bMjzKez9pQgoAWB1mT0S0ntsi5veGVMYeHogf" +
  "6JAm78VmcfpauNxNu3Wf2l9XajegLRhAYys0tkrdiwoRgDv4GELwAggNnHsIXgDWtKJgWx+TNaNB/AJu" +
  "CLkPDzjXoMuaFrfzPXUvKngNajegzQtgX19FwcU8kjWjQewAN4Tchwc+HIKhnZCr0Z8B3Q7o84L7p9ce" +
  "EREREREREQkvl8czzu3uCb0AAAAASUVORK5CYII=";

const CAPE_ID = "c9124188d636edfeaa78b07cdb123dd22026dad435330fdd2c6ef3497f4be789";

/** Content-addressed, so a given id's bytes can never change. Cache hard. */
const IMMUTABLE = "public, max-age=31536000, immutable";
/**
 * Profiles are mutable (a player can change skin), so only cache briefly.
 * Long enough to absorb a room full of players joining at once, short enough
 * that a new upload shows up without the user wondering if it broke.
 */
const PROFILE_CACHE = "public, max-age=60";

const USERNAME_RE = /^[A-Za-z0-9_]{3,16}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TEXTURE_ID_RE = /^[a-f0-9]{64}$/;

// Upload limits. A 64x64 skin PNG is ~1-6 KB; 24 KB is generous headroom while
// still rejecting anything that clearly isn't a skin. The JSON body carries the
// PNG base64-encoded (~33% larger) plus model/uuid.
const MAX_SKIN_BYTES = 24 * 1024;
const MAX_SKIN_BODY = 48 * 1024;
const MAX_HEARTBEAT_BODY = 1024;
const MAX_REPORT_BODY = 1024;

// Moderation reports self-expire (seconds): long enough for a human to review,
// short enough to reclaim KV without a cron.
const REPORT_TTL = 60 * 60 * 24 * 30;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = decodeURIComponent(url.pathname);

    // Write routes first, so the read-only guard below can't swallow them.
    if (path === "/api/heartbeat") {
      if (request.method !== "POST") return methodNotAllowed("POST");
      return handleHeartbeat(request, env);
    }
    if (path === "/api/skin") {
      if (request.method !== "POST") return methodNotAllowed("POST");
      return handleSkinUpload(request, env);
    }
    if (path === "/api/unlocks") {
      if (request.method === "POST") return handleUnlocksPost(request, env);
      if (request.method === "GET") return handleUnlocksGet(request, env);
      return methodNotAllowed("GET, POST");
    }
    if (path === "/report") {
      if (request.method !== "POST") return methodNotAllowed("POST");
      return handleReport(request, env);
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed("GET, HEAD");
    }

    if (path === "/health") {
      return new Response("cubeon-skins ok\n", {
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }

    if (path.startsWith("/textures/")) {
      return serveTexture(path.slice("/textures/".length), env);
    }

    // CSL resolves profile texture values as `root + "textures/" + <id>` with
    // root = ".../skins/", so this is the path CSL actually fetches the PNGs
    // from. /textures/<id> above is kept as an alias (hand-seeding, old
    // records) but serves the exact same bytes.
    if (path.startsWith("/skins/textures/")) {
      return serveTexture(path.slice("/skins/textures/".length), env);
    }

    // CustomSkinAPI route: /skins/<username>.json
    if (path.startsWith("/skins/") && path.endsWith(".json")) {
      const rawName = path.slice("/skins/".length, -".json".length);
      return serveProfile(rawName, env);
    }

    // Face avatars: /faces/<username>.png - the 8x8 head crop (hat layer
    // included), upscaled to 128. Rendered and uploaded BY THE LAUNCHER as a
    // content-addressed texture (crops can't be decoded in a Worker without
    // a PNG codec), then keyed by uuid. Same resolution chain as
    // serveProfile: name -> pointer -> uuid -> face texture.
    if (path.startsWith("/faces/") && path.endsWith(".png")) {
      const rawName = path.slice("/faces/".length, -".png".length);
      return serveFace(rawName, env);
    }

    return notFound();
  },
};

// ------------------------------------------------------------------- writes

/**
 * Extracts and SHA-256-hashes the Bearer secret, or returns null when the
 * header is absent/malformed/too short to be real.
 */
async function bearerSecretHash(request) {
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Bearer ")) return null;
  const secret = header.slice("Bearer ".length).trim();
  if (secret.length < 16 || secret.length > 256) return null;
  return sha256Hex(secret);
}

/**
 * Trust-on-first-use ownership of a UUID, shared by every write route:
 * the first writer claims owner:<uuid> by having its secret hash recorded;
 * every later write must present a secret with the SAME hash. Only the hash
 * is stored, so a KV dump leaks nothing replayable. Returns true when the
 * caller may proceed.
 */
async function ownsUuid(uuid, secretHash, env) {
  const owner = await env.SKINS.get(`owner:${uuid}`);
  if (owner === null) {
    // First-contact TOFU claim. A quota-exhausted put throws; translate it
    // so callers see a retryable 429 instead of a 500 (the client cools
    // off either way, but a clean status keeps tail logs honest).
    let freshClaim;
    try {
      await env.SKINS.put(`owner:${uuid}`, secretHash);
      freshClaim = true;
    } catch (e) {
      if (String(e && e.message).includes("limit exceeded")) {
        return "quota";
      }
      throw e;
    }
    // Race fix (TOCTOU): two concurrent FIRST writes for the same uuid can
    // both see owner === null and both PUT (KV has no compare-and-swap on
    // the free tier). The last put wins silently otherwise - so re-read and
    // verify the recorded hash is OURS. A losing racer gets the honest 403
    // instead of a false "claimed". Costs one free read, only on the
    // first-contact path (once per identity, ever).
    const settled = await env.SKINS.get(`owner:${uuid}`);
    if (settled !== null && settled !== secretHash) {
      return false;
    }
    // "claimed" (not true): tells the heartbeat this was the identity's
    // very first contact, so its initial name pointer is a fresh claim,
    // not a "move" - the anti-hijack cooldown must not throttle it, and
    // it must not stamp lastmove for the rename that follows a typo fix.
    return freshClaim ? "claimed" : true;
  }
  // Constant-time compare (mirrors cubeon-friends.js) so a timing side channel
  // can't reveal how many leading hex chars of the owner hash matched.
  return constantTimeEqual(owner, secretHash);
}

/**
 * put-if-changed: KV reads are free (100k/day), writes are the scarce thing
 * (1k/day account-wide on the free tier). Every steady-state heartbeat /
 * re-upload used to re-PUT identical bytes, so a fleet of idle launchers
 * burned the whole account's budget by lunchtime. Compare-then-write keeps
 * the steady state at ZERO writes.
 */
async function putIfChanged(env, key, value, options) {
  if (options && options.expirationTtl) {
    // TTL puts can't be compared against a plain read (a fresh read of a
    // TTL'd key returns the value, but re-putting is what refreshes the
    // clock) - so TTL writes always go through.
    try {
      await env.SKINS.put(key, value, options);
    } catch (e) {
      if (String(e && e.message).includes("limit exceeded")) {
        return "quota";
      }
      throw e;
    }
    return true;
  }
  const existing = await env.SKINS.get(key);
  if (existing === value) return false;
  try {
    await env.SKINS.put(key, value);
  } catch (e) {
    if (String(e && e.message).includes("limit exceeded")) {
      return "quota";
    }
    throw e;
  }
  return true;
}

/**
 * How long an identity must wait between MOVING name pointers. Honest
 * renames are rare (minutes-to-months apart); pointer hijacking is the one
 * griefing vector this API has (names are unowned labels, last-writer
 * wins). A per-identity cooldown makes "keep flipping someone else's name
 * to me" cost an hour per flip while costing honest users nothing.
 *
 * Implementation: lastmove:<uuid> records the second of this identity's
 * last pointer move. The FIRST move an identity ever makes is its initial
 * claim (no prior stamp) and is free - otherwise a fresh install plus an
 * immediate typo-fix rename would be throttled. Steady-state heartbeats
 * (pointer already ours) cost zero writes and consume no cooldown, and a
 * victim reclaiming their name after a hijack is fast because the
 * HIJACKER's move is what got stamped - the cooldown is per-identity.
 */
const POINTER_MOVE_COOLDOWN_S = 3600;

/**
 * Whether a name is currently "contested" from one identity's point of
 * view: a DIFFERENT identity held the pointer recently (within the move
 * cooldown). `current` must be the PRE-move holder, so callers pass what
 * they read BEFORE their own write. Pure read, no writes.
 */
async function nameContested(current, uuidLower, env) {
  if (current === null || current === uuidLower) return false;
  const theirMove = await env.SKINS.get(`lastmove:${current}`);
  if (theirMove === null) return true; // held by someone else, no stamp: pre-guard holder
  const elapsed = nowSeconds() - parseInt(theirMove, 10);
  return !Number.isNaN(elapsed) && elapsed < POINTER_MOVE_COOLDOWN_S;
}

async function handleHeartbeat(request, env) {
  const secretHash = await bearerSecretHash(request);
  if (!secretHash) return problem(401, "missing_or_bad_token");

  const body = await readJsonLimited(request, MAX_HEARTBEAT_BODY);
  if (!body) return problem(400, "bad_body");

  const { username, uuid } = body;
  if (typeof username !== "string" || !USERNAME_RE.test(username)) {
    return problem(400, "bad_username");
  }
  if (typeof uuid !== "string" || !UUID_RE.test(uuid)) {
    return problem(400, "bad_uuid");
  }

  const uuidLower = uuid.toLowerCase();
  const nameKey = `pointer:${username.toLowerCase()}`;

  const claimed = await ownsUuid(uuidLower, secretHash, env);
  if (claimed === "quota") {
    return problem(429, "kv_write_budget_exhausted");
  }
  if (!claimed) {
    return problem(403, "not_yours");
  }

  const current = await env.SKINS.get(nameKey);
  if (current === uuidLower) {
    // Steady state: already our pointer. Zero writes, no cooldown consumed.
    // No contest possible: the pre-read holder IS us.
    return json({ status: "ok", name_contested: false }, "no-store");
  }

  // This heartbeat would MOVE the pointer. First contact ("claimed" from
  // ownsUuid) means the identity held no name before - the initial claim is
  // free and unthrottled (a fresh install followed by a typo-fix rename
  // must work). Every later move is cooldown-checked: a stamp exists from
  // the identity's first real move, and a victim reclaiming their name
  // stays fast because the HIJACKER's move is what got stamped.
  if (claimed !== "claimed") {
    const lastMove = await env.SKINS.get(`lastmove:${uuidLower}`);
    if (lastMove !== null) {
      const elapsed = nowSeconds() - parseInt(lastMove, 10);
      if (!Number.isNaN(elapsed) && elapsed < POINTER_MOVE_COOLDOWN_S) {
        return problem(429, "name_move_cooldown");
      }
    }
  }

  // Compare-then-write: a repeat heartbeat under the same name (every
  // launcher start) must cost ZERO writes - only a real rename PUTs.
  const put = await putIfChanged(env, nameKey, uuidLower);
  if (put === "quota") {
    return problem(429, "kv_write_budget_exhausted");
  }
  if (put && claimed !== "claimed") {
    // A real (non-first) move happened - stamp this identity's move time so
    // rapid further moves are throttled. First claims don't stamp. Guard
    // against a quota failure here too; an unstamped move just means one
    // un-throttled extra move, not a correctness break.
    try {
      await env.SKINS.put(`lastmove:${uuidLower}`, String(nowSeconds()));
    } catch (e) {
      if (!String(e && e.message).includes("limit exceeded")) throw e;
    }
  }

  // Name-in-use signal: `current` is the PRE-move holder, so if it was a
  // DIFFERENT identity that moved onto this name recently, we just took
  // the label away from them. The launcher surfaces this as a warning
  // instead of a silent last-writer-wins mystery.
  return json({ status: "ok", name_contested: await nameContested(current, uuidLower, env) }, "no-store");
}

/**
 * Whether a name pointer was moved by a DIFFERENT identity recently - i.e.
 * two Cubeon users are fighting over the label. Pure read, no writes.
/**
 * POST /api/skin - publish a player's own skin against their UUID.
 *
 * Body (JSON): { uuid, model: "default"|"slim", skin: <base64 PNG> },
 * Authorization: Bearer <secret_token>.
 *
 * Content-addressed id (SHA-256 of the exact bytes), matching the cape's
 * scheme - so /textures/<id> is safe to cache immutably and re-uploading an
 * unchanged skin overwrites the same keys instead of leaking storage.
 *
 * The record stores the bare id, not a URL: CSL resolves textures as
 * `root + "textures/" + <value>`, so the profile value must be just the id
 * (see serveProfile) - handing it a URL made CSL fetch a nonsense double
 * prefixed path and silently drop the skin/cape.
 */
async function handleSkinUpload(request, env) {
  const secretHash = await bearerSecretHash(request);
  if (!secretHash) return problem(401, "missing_or_bad_token");

  const body = await readJsonLimited(request, MAX_SKIN_BODY);
  if (!body) return problem(400, "bad_body");

  const uuid = typeof body.uuid === "string" ? body.uuid.toLowerCase() : "";
  if (!UUID_RE.test(uuid)) return problem(400, "bad_uuid");

  let bytes;
  try {
    bytes = base64ToBytes(body.skin);
  } catch {
    return problem(400, "bad_skin");
  }
  if (bytes.length > MAX_SKIN_BYTES || !isSkinPng(bytes)) return problem(400, "bad_skin");
  const model = body.model === "slim" ? "slim" : "default";

  const claimed = await ownsUuid(uuid, secretHash, env);
  if (claimed === "quota") {
    return problem(429, "kv_write_budget_exhausted");
  }
  if (!claimed) {
    return problem(403, "not_yours");
  }

  // A moderator-frozen player can't be written to (serveProfile 404s them on
  // read too), so a reported skin can't just be re-uploaded.
  if (await env.SKINS.get(`blocked:${uuid}`)) return problem(403, "blocked");

  const id = await sha256HexBytes(bytes);

  // Optional companion face avatar (128x128 head crop, rendered client-side).
  // Content-addressed like the sheet itself: same face -> same id -> zero
  // extra KV writes when the skin didn't change. Missing/invalid face just
  // skips the field - older launchers keep working.
  let faceId = null;
  if (typeof body.face === "string" && body.face.length > 0) {
    let faceBytes;
    try {
      faceBytes = base64ToBytes(body.face);
    } catch {
      faceBytes = null;
    }
    // Face avatars are 128x128 (head crop upscaled client-side), so they get
    // their own dimension guard; anything else about them is content-checked
    // by the hash, not the shape.
    if (faceBytes && faceBytes.length <= MAX_SKIN_BYTES && isPngWithSize(faceBytes, 128, 128)) {
      faceId = await sha256HexBytes(faceBytes);
    }
  }

  // Compare-then-write on every key: a re-upload of unchanged content (the
  // launcher uploads when its local hash state was lost, e.g. after the
  // state file was deleted) must cost ZERO writes, not three.
  const quota = await putSkinRecord(env, uuid, {
    id,
    model,
    face: faceId,
    sheetB64: bytesToBase64(bytes),
    faceB64: faceId ? body.face : null,
  });
  if (quota) return problem(429, "kv_write_budget_exhausted");

  return json({ ok: true, id }, "no-store");
}

/**
 * Persists a skin record and its textures with put-if-changed semantics:
 * textures only when the content id is new, the record only when it differs.
 * Returns true when the write budget was exhausted (caller -> 429).
 */
async function putSkinRecord(env, uuid, { id, model, face, sheetB64, faceB64 }) {
  if ((await env.SKINS.get(`texture:${id}`)) === null) {
    if ((await putIfChanged(env, `texture:${id}`, sheetB64)) === "quota") return true;
  }
  if (face && (await env.SKINS.get(`texture:${face}`)) === null) {
    if ((await putIfChanged(env, `texture:${face}`, faceB64)) === "quota") return true;
  }
  const recordJson = JSON.stringify({
    id,
    model,
    ...(face ? { face } : {}),
  });
  return (await putIfChanged(env, `skin:${uuid}`, recordJson)) === "quota";
}

/**
 * Earned-milestone ids from the unlocks:<uuid> ledger, as a Set.
 * The set is validated against the KNOWN_MILESTONES catalogue so a bad
 * client can't stuff arbitrary strings into the ledger (it's write-once
 * per id, but garbage ids would still bloat the value and the response).
 */
const KNOWN_MILESTONES = new Set(["founder", "veteran", "party", "host"]);

async function readUnlockSet(env, uuid) {
  const raw = await env.SKINS.get(`unlocks:${uuid}`);
  if (!raw) return new Set();
  return new Set(String(raw).split(",").filter((m) => KNOWN_MILESTONES.has(m)));
}

/**
 * GET /api/unlocks - the ledger for this UUID, for cross-install restore.
 * Body: none, Authorization: Bearer <secret>. The secret must own the UUID
 * (same TOFU check as the write routes - the ledger is player-private).
 */
async function handleUnlocksGet(request, env) {
  const secretHash = await bearerSecretHash(request);
  if (!secretHash) return problem(401, "missing_or_bad_token");

  const url = new URL(request.url);
  const uuid = (url.searchParams.get("uuid") || "").toLowerCase();
  if (!UUID_RE.test(uuid)) return problem(400, "bad_uuid");

  const claimed = await ownsUuid(uuid, secretHash, env);
  if (claimed === "quota") return problem(429, "kv_write_budget_exhausted");
  if (!claimed) return problem(403, "not_yours");

  const set = await readUnlockSet(env, uuid);
  return json({ milestones: [...set].sort() }, "no-store");
}

/**
 * POST /api/unlocks - merge the launcher's earned set into the ledger.
 *
 * Body (JSON): { uuid, milestones: string[] }, Authorization: Bearer.
 *
 * Write discipline (the whole point of this endpoint's shape): the merged
 * set is PUT only when it GAINED at least one id - i.e. exactly one write
 * per milestone ever earned by this player. Re-posting the same set, the
 * reinstall-restore flow, or a fleet of launchers checking in costs zero
 * writes. Milestones can never be REMOVED through this route (a leaked
 * secret could grief by wiping a ledger otherwise); the response always
 * carries the full server-side set so the client can union locally.
 */
async function handleUnlocksPost(request, env) {
  const secretHash = await bearerSecretHash(request);
  if (!secretHash) return problem(401, "missing_or_bad_token");

  const body = await readJsonLimited(request, MAX_HEARTBEAT_BODY);
  if (!body) return problem(400, "bad_body");

  const uuid = typeof body.uuid === "string" ? body.uuid.toLowerCase() : "";
  if (!UUID_RE.test(uuid)) return problem(400, "bad_uuid");

  const incoming = Array.isArray(body.milestones)
    ? body.milestones.filter((m) => typeof m === "string" && KNOWN_MILESTONES.has(m))
    : [];
  if (incoming.length > KNOWN_MILESTONES.size) return problem(400, "bad_milestones");

  const claimed = await ownsUuid(uuid, secretHash, env);
  if (claimed === "quota") return problem(429, "kv_write_budget_exhausted");
  if (!claimed) return problem(403, "not_yours");

  const existing = await readUnlockSet(env, uuid);
  const merged = new Set([...existing, ...incoming]);
  if (merged.size > existing.size) {
    // Sort before joining so identical sets always serialize identically -
    // putIfChanged's byte comparison then keeps idempotent posts at zero
    // writes regardless of the client's ordering.
    const put = await putIfChanged(env, `unlocks:${uuid}`, [...merged].sort().join(","));
    if (put === "quota") {
      // Ledger couldn't persist. Answer 429 (the client backs off to the
      // daily-window retry and re-posts later) instead of 200-with-old-set
      // - the 200 shape was indistinguishable from success, which made the
      // client's ambiguity heuristics necessary. The local state stands
      // either way; only the backup write is deferred.
      return problem(429, "kv_write_budget_exhausted");
    }
  }
  return json({ milestones: [...merged].sort() }, "no-store");
}

/**
 * POST /report - flag a skin for a human to review. Body: { username, reason? }.
 *
 * Deliberately does NOT block: auto-blocking on report would hand any griefer
 * a censor button. It records report:<uuid>; a human sets blocked:<uuid> by
 * hand in the KV dashboard - the kill-switch serveProfile already honors.
 *
 * Write-frugal: only players with a resolved pointer AND a published skin can
 * be reported, and a cheap read dedupes repeated reports into zero writes.
 */
async function handleReport(request, env) {
  const body = await readJsonLimited(request, MAX_REPORT_BODY);
  if (!body) return problem(400, "bad_body");
  const username = body.username;
  if (typeof username !== "string" || !USERNAME_RE.test(username)) {
    return problem(400, "bad_username");
  }

  // Resolve the ephemeral name to the durable identity before storing
  // anything - reports survive renames, and blocking is per-player not
  // per-name (otherwise a banned player could dodge it by renaming).
  const targetUuid = await env.SKINS.get(`pointer:${username.toLowerCase()}`);
  if (!targetUuid) return json({ ok: true });                    // nobody home
  if (!(await env.SKINS.get(`skin:${targetUuid}`))) return json({ ok: true });  // nothing to report
  if (await env.SKINS.get(`report:${targetUuid}`)) return json({ ok: true });   // already flagged

  const reason = typeof body.reason === "string" ? body.reason.slice(0, 200) : "";
  const put = await putIfChanged(env, `report:${targetUuid}`,
    JSON.stringify({ reason, ts: nowSeconds() }),
    { expirationTtl: REPORT_TTL });
  if (put === "quota") return problem(429, "kv_write_budget_exhausted");
  return json({ ok: true });
}

// -------------------------------------------------------------------- reads

/**
 * Extracts the content id from a skin:<uuid> record, whatever shape it is in.
 *
 * The plan's record is {"id","model"} - the bare content id. Records written
 * before that (or hand-seeded from an older README) carry an absolute
 * `{"url": "<origin>/textures/<id>", ...}` instead; the id is its last path
 * segment. Both must resolve, or a player who uploaded under the old format
 * would silently lose their skin the moment the Worker is redeployed.
 * Returns null when there is no usable skin id (record absent, or neither
 * field holds a plausible 64-hex content id).
 */
function skinTextureId(record) {
  if (!record) return null;
  if (typeof record.id === "string" && TEXTURE_ID_RE.test(record.id)) return record.id;
  if (typeof record.url === "string") {
    const last = record.url.split("/").pop();
    if (TEXTURE_ID_RE.test(last)) return last;
  }
  return null;
}

/**
 * GET /skins/<name>.json - CustomSkinAPI profile lookup.
 *
 * Resolves the ephemeral name to the durable UUID, then hands CSL the master
 * skin id. Key ordering inside `textures` is the preference order, so the
 * skin comes before the cape.
 *
 * Texture VALUES ARE BARE IDS, never URLs: CSL resolves them as
 * `root + "textures/" + <value>` with root = ".../skins/", so an absolute URL
 * value makes CSL fetch ".../skins/textures/https://..." and silently drop the
 * skin. The id is what the texture is content-addressed by, and serveTexture
 * under /skins/textures/<id> (and /textures/<id>) is where the bytes live.
 *
 * The pointer gate IS the branding boundary: only a player this launcher has
 * heartbeated (i.e. a Cubeon user) ever resolves to a profile. A name with no
 * pointer 404s, so random premium players on a server are never dressed in
 * the Cubeon cape.
 */
async function serveProfile(username, env) {
  if (!USERNAME_RE.test(username)) return notFound();

  const key = username.toLowerCase();

  // 1. Name -> UUID via the pointer table. No pointer = not a Cubeon player
  // = nothing at all (per the identity API contract, so CSL also falls
  // through cleanly to its next source, e.g. LocalSkin).
  const targetUuid = await env.SKINS.get(`pointer:${key}`);
  if (!targetUuid) return notFound();

  // Moderation kill-switch, keyed by the DURABLE uuid (a rename can't dodge
  // it). Serving nothing (404) is deliberate: it makes the player fall back
  // to vanilla Steve/Alex rather than showing a reported skin to a lobby
  // full of kids while a human takes a look.
  if (await env.SKINS.get(`blocked:${targetUuid}`)) return notFound();

  // 2. UUID -> master skin content id. A heartbeated player who never
  // uploaded anything still gets their cape: cape-only profile, 200.
  // (This is the "cape for every Cubeon user" growth loop - a vanilla-Steve
  // Cubeon player is visible as a Cubeon player without shipping Steve as a
  // fake custom skin.)
  const record = await env.SKINS.get(`skin:${targetUuid}`, "json");
  const skinId = skinTextureId(record);
  if (!skinId) {
    return json({ username, textures: { cape: CAPE_ID } },
                PROFILE_CACHE);
  }

  // 3. Full profile. "slim" is the 3px-arm Alex model; anything else is
  // classic. The shared Cubeon cape rides along in its own texture slot -
  // and a user's own uploaded cape would override it once uploads exist (M3).
  const textures = {
    [record.model === "slim" ? "slim" : "default"]: skinId,
    cape: CAPE_ID,
  };

  return json({ username, textures }, PROFILE_CACHE);
}

/**
 * GET /faces/<username>.png - the player's head crop (Discord presence,
 * web profiles, anywhere a small avatar beats a full sheet).
 *
 * Resolution: name -> pointer -> uuid -> skin record -> face id (falling
 * back to the full sheet id when the record predates face uploads - a
 * 64x64 sheet scaled by the client still reads fine as an avatar at
 * Discord's sizes). Cache: the face is content-addressed, so immutable.
 */
async function serveFace(username, env) {
  if (!USERNAME_RE.test(username)) return notFound();

  const targetUuid = await env.SKINS.get(`pointer:${username.toLowerCase()}`);
  if (!targetUuid) return notFound();
  if (await env.SKINS.get(`blocked:${targetUuid}`)) return notFound();

  const record = await env.SKINS.get(`skin:${targetUuid}`, "json");
  const faceId =
    (record && typeof record.face === "string" && TEXTURE_ID_RE.test(record.face))
      ? record.face
      : skinTextureId(record);
  if (!faceId) return notFound();

  const b64 = await env.SKINS.get(`texture:${faceId}`, "text");
  if (!b64) return notFound();
  return png(base64ToBytes(b64));
}

/** Serves one texture's PNG bytes by content id. */

/** Serves one texture's PNG bytes by content id. */
async function serveTexture(id, env) {
  if (id === CAPE_ID) {
    return png(base64ToBytes(CAPE_B64));
  }
  if (!TEXTURE_ID_RE.test(id)) return notFound();

  const b64 = await env.SKINS.get(`texture:${id}`, "text");
  if (!b64) return notFound();

  return png(base64ToBytes(b64));
}

// --------------------------------------------------------------------- crypto

async function sha256HexBytes(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(text) {
  return sha256HexBytes(new TextEncoder().encode(text));
}

function constantTimeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function base64ToBytes(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

// ----------------------------------------------------------------- validation

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

/**
 * A real PNG whose IHDR says 64x64 or legacy 64x32 - the only valid Minecraft
 * skin dimensions. Cheap header parse (no decode): the 8-byte signature, then
 * IHDR's width/height as big-endian uint32s at bytes 16 and 20. Rejecting junk
 * here keeps the texture namespace to actual skins.
 */
function isSkinPng(bytes) {
  return isPngWithSize(bytes, 64, 64) || isPngWithSize(bytes, 64, 32);
}

/** PNG signature + IHDR dimension check; size-bounded above. */
function isPngWithSize(bytes, w, h) {
  if (!bytes || bytes.length < 24) return false;
  for (let i = 0; i < 8; i++) if (bytes[i] !== PNG_SIGNATURE[i]) return false;
  const width = ((bytes[16] << 24) | (bytes[17] << 16) | (bytes[18] << 8) | bytes[19]) >>> 0;
  const height = ((bytes[20] << 24) | (bytes[21] << 16) | (bytes[22] << 8) | bytes[23]) >>> 0;
  return width === w && height === h;
}

// -------------------------------------------------------------------- helpers

function png(bytes) {
  return new Response(bytes, {
    headers: { "Content-Type": "image/png", "Cache-Control": IMMUTABLE },
  });
}

function json(body, cacheControl) {
  return new Response(JSON.stringify(body), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": cacheControl,
    },
  });
}

function notFound() {
  return new Response("Not Found", { status: 404 });
}

function bytesToBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

async function readJsonLimited(request, maxBytes) {
  const declared = Number(request.headers.get("Content-Length") || "0");
  if (declared > maxBytes) return null;
  let raw;
  try { raw = await request.text(); } catch { return null; }
  if (raw.length > maxBytes) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch { return null; }
}

function nowSeconds() { return Math.floor(Date.now() / 1000); }

function problem(status, error) {
  return new Response(JSON.stringify({ error }), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

function methodNotAllowed(allow) {
  return new Response("Method Not Allowed", { status: 405, headers: { Allow: allow } });
}
