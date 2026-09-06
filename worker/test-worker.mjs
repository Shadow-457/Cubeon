/**
 * Tests for worker/cubeon-skins.js - run with:
 *
 *     node worker/test-worker.mjs
 *
 * Needs nothing installed: no wrangler, no npm, no Cloudflare account. It
 * imports the Worker module directly and hands it a stub KV namespace, which
 * works because the Worker only uses `env.SKINS.get(key, type)`.
 *
 * Worth keeping: the byte-identical check below caught a real corrupted-base64
 * bug that would only have shown up as a broken cape in-game.
 */
import { createHash, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import worker from "./cubeon-skins.js";

const PROJECT = dirname(dirname(fileURLToPath(import.meta.url)));
const CAPE_PNG = join(PROJECT, "assets", "capes", "cubeon_cape.png");

// --- Stub KV: just the subset of the API the Worker actually calls ---------
const store = new Map();
let putCount = 0;  // so a test can prove the report path dedupes its writes
const env = {
  SKINS: {
    async get(key, type) {
      if (!store.has(key)) return null;
      const value = store.get(key);
      return type === "json" ? JSON.parse(value) : value;
    },
    async put(key, value, _options) {
      putCount++;
      store.set(key, String(value));  // real KV coerces to string; mirror that
    },
  },
};

const capeBytes = readFileSync(CAPE_PNG);
const capeSha = createHash("sha256").update(capeBytes).digest("hex");

const get = (path) => worker.fetch(new Request("https://test.invalid" + path), env);
const post = (path, obj, token = null) =>
  worker.fetch(new Request("https://test.invalid" + path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(obj),
  }), env);

// A header-valid PNG: real 8-byte signature + an IHDR chunk carrying the given
// dimensions. The Worker's isSkinPng() parses only the header (it documents
// "cheap header parse, no decode"), so this exercises exactly what it checks
// without pulling in a PNG encoder. `tag` varies a trailing byte so two skins
// hash to different content ids.
function pngBytes(width, height, tag = 0) {
  const be = (n) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];
  return new Uint8Array([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,   // signature (bytes 0-7)
    ...be(13), 0x49, 0x48, 0x44, 0x52,                // IHDR length=13, "IHDR"
    ...be(width),                                     // width  (bytes 16-19)
    ...be(height),                                    // height (bytes 20-23)
    0x08, 0x06, 0x00, 0x00, 0x00,                     // 8-bit RGBA
    tag & 255,                                        // content salt
  ]);
}
const b64 = (bytes) => Buffer.from(bytes).toString("base64");
const sha = (bytes) => createHash("sha256").update(Buffer.from(bytes)).digest("hex");

let failures = 0;
function check(label, ok, extra = "") {
  console.log(`${ok ? "  ok  " : " FAIL "} ${label}${extra ? "  " + extra : ""}`);
  if (!ok) failures++;
}

// CSL emulation: a profile's texture values are BARE ids, and CustomSkinLoader
// resolves them as `root + "textures/" + <id>` against the CustomSkinAPI root
// ".../skins/". So every value in a served profile must 200 at
// /skins/textures/<id>. This is the regression test for the URL-instead-of-id
// bug, which made CSL fetch a double-prefixed path and silently drop skins.
async function checkTexturesResolve(label, textures) {
  for (const [kind, id] of Object.entries(textures)) {
    const res = await get(`/skins/textures/${id}`);
    check(`${label}: "${kind}" resolves as /skins/textures/<id>`,
      res.status === 200 && res.headers.get("Content-Type") === "image/png",
      `id=${id.slice(0, 12)}…`);
  }
}
// Back a synthetic (non-uploaded) texture id with real bytes so CSL emulation
// can resolve it, mirroring how an upload stores both the record and the bytes.
const seedTexture = (id) => store.set(`texture:${id}`, b64(pngBytes(64, 64, 7)));

// The Worker's embedded cape must be exactly the PNG on disk. If this fails,
// run `python tools/make_cape.py` - never patch the constants by hand.
const served = Buffer.from(await (await get(`/textures/${capeSha}`)).arrayBuffer());
check("embedded cape is byte-identical to assets/capes/cubeon_cape.png",
  served.equals(capeBytes), `sha=${capeSha.slice(0, 12)}…`);

// ------------------------------------------------------------- CSL reads --
// Per the identity API contract, an unresolved name is a hard 404 - there is
// no cape-only half-profile anymore. A 404 lets CSL fall through to its next
// source instead of rendering something half-baked.
check("unknown user -> 404 (no pointer)", (await get("/NewPlayer.json")).status === 404);

// CustomSkinAPI lookups are case-insensitive, but the response echoes the name
// as it was asked for. Texture values are BARE content ids (never URLs): CSL
// resolves them as `root + "textures/" + <id>`, so a URL here would make CSL
// fetch a double-prefixed path and drop the texture.
const UUID_A = randomUUID();
const TEXTURE_A = "a".repeat(64);
seedTexture(TEXTURE_A);
store.set("pointer:bluefox", UUID_A.toLowerCase());
store.set(`skin:${UUID_A.toLowerCase()}`, JSON.stringify({
  id: TEXTURE_A, model: "slim",
}));
let body = await (await get("/skins/BlueFox.json")).json();
check("case-insensitive lookup, echoes original case",
  body.username === "BlueFox"
  && body.textures.slim === TEXTURE_A
  && body.textures.cape === capeSha,
  JSON.stringify(body.textures));
await checkTexturesResolve("BlueFox", body.textures);

// Key order in `textures` is the preference order, so the skin must precede
// the cape.
check("skin key ordered before cape",
  Object.keys(body.textures).join(",") === "slim,cape",
  Object.keys(body.textures).join(","));

const UUID_B = randomUUID();
const TEXTURE_B = "b".repeat(64);
seedTexture(TEXTURE_B);
store.set("pointer:classicguy", UUID_B.toLowerCase());
store.set(`skin:${UUID_B.toLowerCase()}`, JSON.stringify({
  id: TEXTURE_B, model: "default",
}));
body = await (await get("/skins/ClassicGuy.json")).json();
check("non-slim model -> 'default' key", "default" in body.textures);

// A record seeded in the OLD {"url": "<origin>/textures/<id>"} format (pre-2026
// uploads, or a hand-seed from an older README) must still serve its skin - the
// id is the last path segment. Dropping these on redeploy would silently erase
// every skin uploaded under the old format.
const UUID_LEGACY = randomUUID();
const TEXTURE_LEGACY = "d".repeat(64);
seedTexture(TEXTURE_LEGACY);
store.set("pointer:legacyurlguy", UUID_LEGACY.toLowerCase());
store.set(`skin:${UUID_LEGACY.toLowerCase()}`, JSON.stringify({
  url: `https://cubeon-skins.hamza-457-shahbaz.workers.dev/textures/${TEXTURE_LEGACY}`,
  model: "slim",
}));
body = await (await get("/skins/LegacyUrlGuy.json")).json();
check("legacy url-form record still serves its bare id",
  body.textures.slim === TEXTURE_LEGACY && body.textures.cape === capeSha,
  JSON.stringify(body.textures));
await checkTexturesResolve("LegacyUrlGuy", body.textures);

// A pointer with NO skin record is a CAPE-ONLY profile: this player launched
// Cubeon (so they heartbeated -> pointer) but never uploaded anything. They
// wear the cape without Steve being shipped as a fake custom skin.
const UUID_C = randomUUID();
store.set("pointer:barepointer", UUID_C.toLowerCase());
let bare = await (await get("/skins/BarePointer.json")).json();
check("pointer without skin -> 200, cape only",
  bare.username === "BarePointer"
  && bare.textures.cape === capeSha
  && !("default" in bare.textures) && !("slim" in bare.textures),
  JSON.stringify(bare.textures));
await checkTexturesResolve("BarePointer", bare.textures);

// ...but the branding boundary holds: no pointer at all is still a hard 404,
// so non-Cubeon players are never dressed in the cape.
check("no pointer -> still 404", (await get("/skins/NeverHeartbeated.json")).status === 404);

// Moderation kill-switch is keyed by the DURABLE uuid and applies to
// cape-only players too.
store.set(`blocked:${UUID_C.toLowerCase()}`, "1");
check("blocked uuid with pointer-but-no-skin -> 404",
  (await get("/skins/BarePointer.json")).status === 404);
store.delete(`blocked:${UUID_C.toLowerCase()}`);

// Moderation kill-switch is keyed by the DURABLE uuid (a rename can't dodge
// it). 404 makes the client fall back to vanilla Steve/Alex rather than keep
// showing a reported skin.
store.set(`blocked:${UUID_A.toLowerCase()}`, "1");
check("blocked user -> 404", (await get("/skins/BlueFox.json")).status === 404);
store.delete(`blocked:${UUID_A.toLowerCase()}`);

// Anything that isn't a real Minecraft username is rejected before it can
// become part of a KV key.
for (const bad of ["/skins/ab.json", "/skins/way_too_long_username.json",
                   "/skins/has-dash.json", "/skins/a%2Fb.json",
                   "/skins/sub/dir.json", "/skins/.json"]) {
  check(`rejects ${bad}`, (await get(bad)).status === 404);
}
check("rejects non-sha256 texture id", (await get("/textures/nope")).status === 404);
check("rejects non-sha256 id under /skins/textures/",
  (await get("/skins/textures/nope")).status === 404);
check("unknown texture -> 404", (await get(`/textures/${"c".repeat(64)}`)).status === 404);
check("unknown texture under /skins/textures/ -> 404",
  (await get(`/skins/textures/${"c".repeat(64)}`)).status === 404);

// Textures are content-addressed, so they can be cached forever; profiles
// change when a player re-uploads, so they cannot.
const texRes = await get(`/textures/${capeSha}`);
check("texture cached immutably", texRes.headers.get("Cache-Control").includes("immutable"));
const profRes = await get("/skins/ClassicGuy.json");
check("profile cached briefly",
  /max-age=\d+/.test(profRes.headers.get("Cache-Control")) &&
  !profRes.headers.get("Cache-Control").includes("immutable"));

check("POST rejected with 405",
  (await worker.fetch(new Request("https://test.invalid/skins/x.json", { method: "POST" }), env)).status === 405);
check("/health -> 200", (await get("/health")).status === 200);

// ------------------------------------------------------------- heartbeat --
// The authenticated pointer updater: Bearer secret + {username, uuid}. First
// contact claims ownership of the UUID (TOFU); afterwards only the same
// secret may repoint it.
const SECRET_A = "sec_a-real-looking-secret-0123456789abcdef";
const SECRET_B = "sec_a-different-secret-9876543210zzzzzzzz";
const UUID_U = randomUUID();

let res = await post("/api/heartbeat", { username: "Uploader", uuid: UUID_U });
check("heartbeat without token -> 401", res.status === 401);

res = await post("/api/heartbeat", { username: "Uploader", uuid: UUID_U }, "short");
check("heartbeat with short token -> 401", res.status === 401);

res = await post("/api/heartbeat", { username: "Uploader" }, SECRET_A);
check("heartbeat without uuid -> 400 bad_uuid", res.status === 400 && (await res.json()).error === "bad_uuid");

res = await post("/api/heartbeat", { username: "bad name", uuid: UUID_U }, SECRET_A);
check("heartbeat bad username -> 400 bad_username", res.status === 400 && (await res.json()).error === "bad_username");

res = await post("/api/heartbeat", { username: "Uploader", uuid: "not-a-uuid" }, SECRET_A);
check("heartbeat malformed uuid -> 400", res.status === 400);

res = await post("/api/heartbeat", { username: "Uploader", uuid: UUID_U }, SECRET_A);
check("heartbeat happy path -> 200 ok", res.status === 200 && (await res.json()).status === "ok");
check("heartbeat wrote the pointer",
  store.get(`pointer:uploader`) === UUID_U.toLowerCase());
check("heartbeat locked ownership to sha256(secret)",
  store.get(`owner:${UUID_U.toLowerCase()}`) === sha(Buffer.from(SECRET_A)));

// An impostor presenting a different secret cannot steal the pointer...
res = await post("/api/heartbeat", { username: "Uploader", uuid: UUID_U }, SECRET_B);
check("wrong secret -> 403 not_yours", res.status === 403 && (await res.json()).error === "not_yours");

// ...and the failed attempt didn't change anything.
check("failed hijack left the pointer alone",
  store.get("pointer:uploader") === UUID_U.toLowerCase());

// The rightful owner CAN rename: same secret, new name, same UUID.
res = await post("/api/heartbeat", { username: "RenamedUploader", uuid: UUID_U }, SECRET_A);
check("owner renames via heartbeat -> 200", res.status === 200);
check("rename moved the pointer to the new name",
  store.get("pointer:renameduploader") === UUID_U.toLowerCase());

// ----------------------------------------------------------- skin uploads --
// Content-addressing: the id the Worker returns is the sha256 of the exact
// bytes sent, same scheme as the cape, so client and Worker agree without
// coordinating.
const skinA = pngBytes(64, 64, 1);
const skinIdFor = (bytes) => sha(bytes);  // the bare content id the profile now carries

res = await post("/api/skin", { uuid: UUID_U, model: "default", skin: b64(skinA) });
check("upload without token -> 401", res.status === 401);

res = await post("/api/skin", { uuid: UUID_U, model: "default", skin: b64(skinA) }, SECRET_B);
check("upload by impostor -> 403 not_yours", res.status === 403 && (await res.json()).error === "not_yours");

res = await post("/api/skin", { uuid: UUID_U, model: "default", skin: b64(skinA) }, SECRET_A);
let up = await res.json();
check("upload happy path -> 200 + content id",
  res.status === 200 && up.ok === true && up.id === sha(skinA), up.id?.slice(0, 12) + "…");

// The uploaded skin is now visible through the normal CustomSkinAPI read path,
// alongside the shared cape - and every value resolves for CSL.
body = await (await get("/skins/RenamedUploader.json")).json();
check("uploaded skin shows in profile (default), keeps cape",
  body.textures.default === skinIdFor(skinA) && body.textures.cape === capeSha,
  JSON.stringify(body.textures));
await checkTexturesResolve("RenamedUploader(uploaded)", body.textures);

// ...and its bytes come back byte-identical, the check that caught the cape bug.
const back = Buffer.from(await (await get(`/textures/${sha(skinA)}`)).arrayBuffer());
check("uploaded texture round-trips byte-identical", back.equals(Buffer.from(skinA)));

// The rightful owner CAN update their own skin (same secret, new bytes/model).
const skinA2 = pngBytes(64, 64, 3);
res = await post("/api/skin", { uuid: UUID_U, model: "slim", skin: b64(skinA2) }, SECRET_A);
check("owner updates own skin -> 200", res.status === 200 && (await res.json()).id === sha(skinA2));
body = await (await get("/skins/RenamedUploader.json")).json();
check("update took effect (new bytes + slim, no stale default)",
  body.textures.slim === skinIdFor(skinA2) && !("default" in body.textures));
await checkTexturesResolve("RenamedUploader(updated)", body.textures);

// A slim upload under a fresh identity is stored and served under 'slim'.
const UUID_S = randomUUID();
await post("/api/heartbeat", { username: "SlimGal", uuid: UUID_S }, SECRET_B);
await post("/api/skin", { uuid: UUID_S, model: "slim", skin: b64(pngBytes(64, 64, 9)) }, SECRET_B);
body = await (await get("/skins/SlimGal.json")).json();
check("slim model stored under 'slim'",
  body.textures.slim === skinIdFor(pngBytes(64, 64, 9)));
await checkTexturesResolve("SlimGal", body.textures);

// --- upload rejections ---
res = await post("/api/skin", { uuid: UUID_U, model: "default", skin: b64(pngBytes(32, 32, 1)) }, SECRET_A);
check("wrong dimensions -> 400 bad_skin", res.status === 400 && (await res.json()).error === "bad_skin");

res = await post("/api/skin", { uuid: UUID_U, model: "default",
  skin: b64(new Uint8Array(Array.from({ length: 24 }, (_, i) => i + 1))) }, SECRET_A);
check("non-PNG bytes -> 400 bad_skin", res.status === 400);

res = await post("/api/skin", { uuid: "not-a-uuid", model: "default", skin: b64(skinA) }, SECRET_A);
check("upload bad uuid -> 400 bad_uuid", res.status === 400 && (await res.json()).error === "bad_uuid");

res = await post("/api/skin", { uuid: UUID_U, model: "default" }, SECRET_A);
check("missing skin -> 400 bad_skin", res.status === 400 && (await res.json()).error === "bad_skin");

// Oversize skin: over MAX_SKIN_BYTES but small enough that the JSON body is
// still under MAX_SKIN_BODY, so it reaches (and trips) the byte-length guard.
const bigSkin = new Uint8Array(25 * 1024);
bigSkin.set(pngBytes(64, 64, 1), 0);
res = await post("/api/skin", { uuid: UUID_U, model: "default", skin: b64(bigSkin) }, SECRET_A);
check("oversize skin -> 400", res.status === 400);

// A body larger than MAX_SKIN_BODY is rejected before it's even parsed.
res = await post("/api/skin", { uuid: UUID_U, model: "default", skin: b64(new Uint8Array(40 * 1024)) }, SECRET_A);
check("oversize body -> 400", res.status === 400);

// The moderation freeze blocks new uploads for a player, not just reads - so
// a reported skin can't just be re-uploaded.
store.set(`blocked:${UUID_S.toLowerCase()}`, "1");
res = await post("/api/skin", { uuid: UUID_S, model: "default", skin: b64(skinA) }, SECRET_B);
check("blocked player can't upload -> 403 blocked", res.status === 403 && (await res.json()).error === "blocked");
store.delete(`blocked:${UUID_S.toLowerCase()}`);

// All write endpoints are POST-only.
check("GET /api/heartbeat -> 405", (await get("/api/heartbeat")).status === 405);
check("GET /api/skin -> 405", (await get("/api/skin")).status === 405);
check("GET /report -> 405", (await get("/report")).status === 405);

// ------------------------------------------------------- unlocks ledger --
// The milestone ledger's whole design is KV write-frugality: one write per
// milestone EVER. POST the set, then re-POST, and count puts. Also pins the
// merge-only semantics (a leaked secret can't wipe a ledger) and the
// catalogue validation (garbage ids are dropped, not stored).
{
  const UUID_M = randomUUID().toLowerCase();
  // Claim ownership first (the TOFU owner: write happens on first contact).
  await post("/api/heartbeat", { username: "MilestoneGal", uuid: UUID_M }, SECRET_A);

  let res = await post("/api/unlocks", { uuid: UUID_M, milestones: ["veteran", "garbage_id"] }, SECRET_A);
  let body = await res.json();
  check("unlocks POST accepts known ids, drops garbage",
    res.status === 200 && body.milestones.includes("veteran")
      && !body.milestones.includes("garbage_id"));

  const putsAfterFirst = putCount;
  res = await post("/api/unlocks", { uuid: UUID_M, milestones: ["veteran", "party"] }, SECRET_A);
  body = await res.json();
  check("unlocks POST merges (grows the set)",
    body.milestones.sort().join(",") === "party,veteran", JSON.stringify(body.milestones));

  const putsAfterGrow = putCount;
  await post("/api/unlocks", { uuid: UUID_M, milestones: ["veteran", "party"] }, SECRET_A);
  check("re-POST of identical set writes nothing", putCount === putsAfterGrow);

  // A SUBSET post (older launcher, or reinstall mid-restore) must not shrink
  // the ledger - milestones are append-only.
  await post("/api/unlocks", { uuid: UUID_M, milestones: ["veteran"] }, SECRET_A);
  const afterSubset = await (await post("/api/unlocks", { uuid: UUID_M, milestones: [] }, SECRET_A)).json();
  check("subset POST can't shrink the ledger (append-only)",
    afterSubset.milestones.sort().join(",") === "party,veteran",
    JSON.stringify(afterSubset.milestones));

  // Auth: the ledger is player-private.
  res = await post("/api/unlocks", { uuid: UUID_M, milestones: ["host"] }, SECRET_B);
  check("unlocks POST with wrong secret -> 403 not_yours",
    res.status === 403 && (await res.json()).error === "not_yours");
  res = await post("/api/unlocks", { uuid: UUID_M, milestones: ["host"] });
  check("unlocks POST without token -> 401", res.status === 401);

  // GET: the same set back, Bearer + query param.
  res = await get(`/api/unlocks?uuid=${UUID_M}`);
  check("unlocks GET without token -> 401", res.status === 401);
  // (get() helper has no header hook - call fetch directly for the auth'd GET)
  res = await worker.fetch(new Request(`https://test.invalid/api/unlocks?uuid=${UUID_M}`, {
    headers: { Authorization: `Bearer ${SECRET_A}` },
  }), env);
  check("unlocks GET returns the full ledger",
    res.status === 200 && (await res.json()).milestones.sort().join(",") === "party,veteran");
  res = await worker.fetch(new Request(`https://test.invalid/api/unlocks?uuid=${UUID_M}`, {
    headers: { Authorization: `Bearer ${SECRET_B}` },
  }), env);
  check("unlocks GET with wrong secret -> 403", res.status === 403);

  // Bad bodies.
  res = await post("/api/unlocks", { milestones: ["host"] }, SECRET_A);
  check("unlocks POST missing uuid -> 400", res.status === 400);
  res = await post("/api/unlocks", { uuid: "not-a-uuid", milestones: [] }, SECRET_A);
  check("unlocks POST bad uuid -> 400", res.status === 400);
  check("unlocks DELETE -> 405", (await worker.fetch(
    new Request("https://test.invalid/api/unlocks", { method: "DELETE" }), env)).status === 405);
}


// ---------------------------------------------------------------- reports --
// Reporting an uploaded skin records a pending report for a human; it must NOT
// auto-block (auto-block on report hands any griefer a remote censor button).
// Reports go in by NAME and are stored against the resolved UUID, so they
// survive renames.
res = await post("/report", { username: "RenamedUploader", reason: "test reason" });
check("report known skin -> 200 + recorded", res.status === 200 && store.has(`report:${UUID_U.toLowerCase()}`));
check("report does NOT auto-block", !store.has(`blocked:${UUID_U.toLowerCase()}`));

// A second report of the same player writes nothing (KV writes are scarce).
let before = putCount;
await post("/report", { username: "RenamedUploader", reason: "again" });
check("duplicate report writes nothing", putCount === before);

// You can't report a name with no published skin (can't report vanilla Steve),
// and it costs no write.
before = putCount;
res = await post("/report", { username: "NobodyHome" });
check("report of unknown skin -> 200, no write",
  res.status === 200 && putCount === before && !store.has("report:nobodyhome"));

// --- rate limiter (from cubeon-friends.js, pure, no DO needed) -----------
import { limiterAllow } from "./cubeon-friends.js";
const rl = new Map();
let t = 1_000_000;
check("limiter allows up to max", [1, 2, 3].every(() => limiterAllow(rl, "k", 3, 60_000, t)));
check("limiter refuses past max", limiterAllow(rl, "k", 3, 60_000, t) === false);
check("limiter is per-key", limiterAllow(rl, "other", 3, 60_000, t) === true);
t += 61_000;
check("limiter window slides", limiterAllow(rl, "k", 3, 60_000, t) === true);

console.log(failures ? `\n${failures} CHECK(S) FAILED` : "\nALL WORKER CHECKS PASSED");
process.exit(failures ? 1 : 0);
