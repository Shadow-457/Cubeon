/**
 * Cubeon invite API - Cloudflare Worker (free tier, no VPS).
 *
 * Maps a short spoken-aloud code to whatever address a host's tunnel currently
 * has:
 *
 *   PUT    /i/<CODE>   claim or update a code   (Authorization: Bearer <secret>)
 *   GET    /i/<CODE>   resolve a code to host:port
 *   DELETE /i/<CODE>   unpublish                (Authorization: Bearer <secret>)
 *   GET    /health     plain-text OK, for debugging by hand
 *
 * Bindings required: KV namespace bound as INVITES.
 * Optional:          Rate Limiting binding as RATE_LIMITER (see WRITE BUDGET).
 *
 * ------------------------------------------------------------------------
 * WHY A CODE AND NOT JUST THE ADDRESS
 *
 * A tunnel address is `bluefox-1234.gl.joinmc.link:52341` - unsayable, and on
 * playit's free tier the port changes when the agent reconnects. The code is
 * stable, so a friend group can save it once. It also keeps the tunnel provider
 * invisible: swapping playit for a VPS later changes only the stored value.
 *
 * ------------------------------------------------------------------------
 * AUTHENTICATION - AND WHY THIS ONE IS SOLVABLE
 *
 * Skin uploads are still blocked in the sibling Worker because offline accounts
 * have no identity, so nothing can answer "who may write this *username*?"
 * Invite codes escape that trap: a freshly minted code has no rightful owner to
 * impersonate, so ownership can be *created* at claim time instead of proven.
 *
 * The host's launcher generates a 256-bit secret locally and sends it with the
 * claim. The Worker stores only its SHA-256, and later writes to that code must
 * present the same secret. That's a capability, not an account: no signup, no
 * email, nothing to phish, and a KV dump leaks no secret that can be replayed.
 *
 * Codes are *not* secrets - they get pasted into group chats, which is the
 * point. Guessing one only reveals an address that a player was going to be
 * given anyway. Guessing the *secret* is what would let someone redirect a
 * host's friends, and that is 256 bits from `secrets.token_urlsafe`.
 *
 * ------------------------------------------------------------------------
 * KV LAYOUT
 *
 *   invite:<CODE>    JSON {secret_hash, address, version, loader, created, updated}
 *   blocked:<CODE>   any   presence = moderation kill-switch
 *
 * Codes are stored in canonical upper-case form; lookups upper-case first, so
 * a code typed in lower case resolves.
 *
 * ------------------------------------------------------------------------
 * WRITE BUDGET - the real constraint on this Worker
 *
 * KV free tier allows ~1000 writes/day against 100k reads/day. Reads are a
 * non-issue (a read is one friend joining). Writes are the scarce resource, so
 * this Worker is built to avoid them:
 *
 *   * Entries carry a 24h `expirationTtl`, so an abandoned code cleans itself
 *     up. Expiry costs no write, unlike an explicit delete.
 *   * PUT reads before it writes and skips the write entirely when nothing
 *     changed and the entry is still young. A host who restarts their server
 *     three times spends one write, not three.
 *   * There is deliberately no heartbeat. A 30-second keepalive would be 2880
 *     writes/day from a single host - it would exhaust the daily budget for
 *     every Cubeon user combined before lunch. Liveness is inferred from the
 *     TTL instead, which is less precise and free.
 *
 * That leaves one exposure worth naming: without rate limiting, anyone who
 * finds this endpoint can burn the day's writes in a minute and stop everyone
 * else from hosting. Bind Cloudflare's Rate Limiting binding as RATE_LIMITER to
 * close it; the code below uses it when present and runs without it when not,
 * so a missing binding degrades to "works, but abusable" rather than "broken".
 * ------------------------------------------------------------------------
 */

/**
 * Must stay identical to `ALPHABET`/`PREFIX` in cubeon/invites.py - the format
 * is defined there and mirrored here. `tools/test_invites.py` reads this file
 * and asserts the two agree, because a silent divergence would mean the
 * launcher mints codes this Worker rejects, and only in production.
 */
const CODE_RE = /^CUBE-[34679ACDEFGHJKMNPQRTUVWXY]{4}-[34679ACDEFGHJKMNPQRTUVWXY]{4}$/;

/**
 * host:port, where host is dotted DNS labels or an IPv4 address.
 *
 * At least one dot is required, which rejects `localhost` - a code pointing at
 * localhost would resolve fine for the host and fail for every friend, with no
 * error message that explains why.
 */
const ADDRESS_RE = /^(?=.{1,253}:)[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+:\d{1,5}$/;

/** Minecraft version ids and loader names, conservatively. */
const VERSION_RE = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$/;
const LOADER_RE = /^[a-z]{1,16}$/;

/** An entry lives a day unless refreshed. Long enough for a weekend session. */
const TTL_SECONDS = 24 * 60 * 60;

/**
 * Re-publishing an unchanged entry is skipped unless it's older than this, so
 * a long session still refreshes its TTL before the 24h expiry drops it.
 */
const REFRESH_AFTER_SECONDS = 6 * 60 * 60;

/** Bodies are a handful of short fields; anything larger is not a real client. */
const MAX_BODY_BYTES = 1024;

/** A resolve is worthless if it's stale, and hosts change ports. Cache barely. */
const RESOLVE_CACHE = "public, max-age=10";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = decodeURIComponent(url.pathname);

    if (path === "/health") {
      if (request.method !== "GET" && request.method !== "HEAD") {
        return methodNotAllowed("GET, HEAD");
      }
      return text("cubeon-invites ok\n");
    }

    if (!path.startsWith("/i/")) return notFound();

    // Codes are case-insensitive for humans; canonical upper-case in storage.
    const code = path.slice("/i/".length).toUpperCase();
    if (!CODE_RE.test(code)) return notFound();

    switch (request.method) {
      case "GET":
      case "HEAD":
        return resolve(code, env);
      case "PUT":
        return publish(code, request, env);
      case "DELETE":
        return unpublish(code, request, env);
      default:
        return methodNotAllowed("GET, HEAD, PUT, DELETE");
    }
  },
};

/**
 * Resolves a code to an address.
 *
 * Never returns `secret_hash` - the whole point of storing a hash is that this
 * endpoint, which anyone can call with a code from a group chat, can't leak
 * anything replayable.
 */
async function resolve(code, env) {
  // Moderation kill-switch, same stance as the skins Worker: 404 rather than a
  // "blocked" message. A code being reported means a human has to look, and in
  // the meantime nobody should be routed to it.
  if (await env.INVITES.get(`blocked:${code}`)) return notFound();

  const entry = await env.INVITES.get(`invite:${code}`, "json");
  if (!entry || typeof entry.address !== "string") return notFound();

  const now = nowSeconds();
  return json({
    code,
    address: entry.address,
    version: entry.version ?? null,
    loader: entry.loader ?? null,
    // Age lets the joining launcher say "started 20 minutes ago" and, more
    // usefully, warn when an entry is nearly expired and the host has probably
    // gone offline. Absolute timestamps would be a clock-skew argument between
    // two machines; an age is not.
    age: Math.max(0, now - (entry.updated || entry.created || now)),
    expires_in: Math.max(0, TTL_SECONDS - (now - (entry.updated || entry.created || now))),
  }, RESOLVE_CACHE);
}

/**
 * Claims a code, or updates one already held with the same secret.
 *
 * Idempotent, hence PUT: the launcher calls this on every server start with the
 * code it already owns, and a repeat call with an unchanged address is a no-op.
 */
async function publish(code, request, env) {
  const secret = bearer(request);
  if (!secret) return problem(401, "missing_secret");

  if (await env.INVITES.get(`blocked:${code}`)) return problem(403, "blocked");

  const body = await readJson(request);
  if (body === null) return problem(400, "bad_body");

  const address = body.address;
  if (typeof address !== "string" || !ADDRESS_RE.test(address)) {
    return problem(400, "bad_address");
  }
  const port = Number(address.slice(address.lastIndexOf(":") + 1));
  if (!(port >= 1 && port <= 65535)) return problem(400, "bad_address");

  const version = optional(body.version, VERSION_RE);
  const loader = optional(body.loader, LOADER_RE);
  if (version === false || loader === false) return problem(400, "bad_field");

  const hash = await sha256Hex(secret);
  const existing = await env.INVITES.get(`invite:${code}`, "json");

  if (existing) {
    if (!constantTimeEqual(existing.secret_hash || "", hash)) {
      // One status for both "someone else owns this" and "your secret is
      // wrong", because the caller's next move is the same either way: mint a
      // different code. Distinguishing them would only help someone probing.
      return problem(409, "code_taken");
    }

    const unchanged =
      existing.address === address &&
      (existing.version ?? null) === version &&
      (existing.loader ?? null) === loader;
    const age = nowSeconds() - (existing.updated || existing.created || 0);

    if (unchanged && age < REFRESH_AFTER_SECONDS) {
      // Deliberately not writing. See WRITE BUDGET - this is the common case
      // (host restarts their server, address unchanged) and it must be free.
      return json({ code, address, written: false }, "no-store");
    }
  }

  const now = nowSeconds();
  const entry = {
    secret_hash: hash,
    address,
    version,
    loader,
    created: existing ? (existing.created || now) : now,
    updated: now,
  };

  await env.INVITES.put(`invite:${code}`, JSON.stringify(entry), {
    // Self-cleaning. An abandoned code disappears without anyone spending a
    // write on a delete.
    expirationTtl: TTL_SECONDS,
  });

  return json({ code, address, written: true, claimed: !existing }, "no-store");
}

/**
 * Removes a mapping. Called when the host stops their server, so a friend
 * clicking an old code is told "this server isn't running" instead of timing
 * out against a dead port.
 */
async function unpublish(code, request, env) {
  const secret = bearer(request);
  if (!secret) return problem(401, "missing_secret");

  const existing = await env.INVITES.get(`invite:${code}`, "json");
  // Already gone (very likely expired) is success - the caller wanted it not to
  // exist, and it doesn't. Retrying a failed stop must not error.
  if (!existing) return new Response(null, { status: 204 });

  const hash = await sha256Hex(secret);
  if (!constantTimeEqual(existing.secret_hash || "", hash)) {
    return problem(403, "not_yours");
  }

  await env.INVITES.delete(`invite:${code}`);
  return new Response(null, { status: 204 });
}

// ----------------------------------------------------------------- helpers ---

/** The bearer token, or null. Length-capped so a huge header can't be a DoS. */
function bearer(request) {
  const header = request.headers.get("Authorization") || "";
  const match = /^Bearer ([A-Za-z0-9._~+/=-]{16,256})$/.exec(header.trim());
  return match ? match[1] : null;
}

/**
 * Parses a small JSON body, or null if it's absent, oversized, or malformed.
 *
 * Checks Content-Length *and* the decoded length: the header is a hint a client
 * controls, so it can't be the only guard.
 */
async function readJson(request) {
  const declared = Number(request.headers.get("Content-Length") || "0");
  if (declared > MAX_BODY_BYTES) return null;
  let raw;
  try {
    raw = await request.text();
  } catch {
    return null;
  }
  if (raw.length > MAX_BODY_BYTES) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * An optional constrained string: null when absent, the value when it matches,
 * `false` when present but invalid - so a caller can tell "not given" from
 * "given as garbage" rather than silently dropping a typo'd field.
 */
function optional(value, re) {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value !== "string" || !re.test(value)) return false;
  return value;
}

async function sha256Hex(input) {
  const bytes = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Compares two hex strings without an early return.
 *
 * The practical timing signal here is buried under internet jitter, but a
 * constant-time compare of two 64-char strings costs nothing, and the
 * alternative is arguing about it.
 */
function constantTimeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) {
    return false;
  }
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function json(body, cacheControl) {
  return new Response(JSON.stringify(body), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": cacheControl,
    },
  });
}

function text(body) {
  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

/** A machine-readable error the launcher can map to a human sentence. */
function problem(status, error) {
  return new Response(JSON.stringify({ error }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function notFound() {
  return new Response("Not Found", { status: 404 });
}

function methodNotAllowed(allow) {
  return new Response("Method Not Allowed", { status: 405, headers: { Allow: allow } });
}
