/**
 * Cubeon waitlist API - Cloudflare Worker (free tier, no VPS).
 *
 * Backs the "N in line" counter on the marketing site (web/index.html). The
 * site works without this - it falls back to a local placeholder count - but
 * pointing WAITLIST_ENDPOINT at this Worker makes the number real and shared
 * across everyone who visits, and it captures the emails so the launch email
 * can actually go out.
 *
 *   GET  /            -> { count }                 the public tally
 *   POST /  {email}   -> { count, joined }         add an email (deduped)
 *   GET  /health      -> plain-text OK, for debugging by hand
 *
 * Bindings required: KV namespace bound as WAITLIST.
 *
 * ------------------------------------------------------------------------
 * KV LAYOUT
 *
 *   count                 TEXT   the running total, as a decimal string
 *   email:<sha256(addr)>  JSON   {"email": "<raw addr>", "at": <epoch ms>}
 *
 * Emails are keyed by hash so a repeat signup is a cheap point-read instead of
 * a list scan, and so the same address can't inflate the count. The raw
 * address is kept in the VALUE (not the key) so the list can be exported later
 * to actually email people - read them from the KV dashboard or with
 * `wrangler kv:key list`.
 *
 * WRITES ARE THE SCARCE RESOURCE on the free tier (~1k writes/day), not reads
 * (~100k/day). A new signup costs exactly two writes (the email record + the
 * bumped counter); a duplicate or a bad email costs zero. A GET costs one
 * read. That keeps a launch-day traffic spike from blowing the daily quota.
 *
 * The counter is a plain KV string, so two truly-simultaneous signups can race
 * and lose one increment. For a vanity waitlist tally that is fine - it drifts
 * by a handful at most under load and never blocks a signup. If it ever needs
 * to be exact, move `count` into a Durable Object like cubeon-friends.js.
 * ------------------------------------------------------------------------
 */

// Public, uncredentialed endpoint (no cookies, no secrets) - "*" is safe and
// lets the site be served from any origin (cubeon domain, a Pages preview, or
// a file:// dev open) without a per-origin allow-list to maintain.
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

// Deliberately loose - this mirrors the browser's own check, it is not an
// authorization boundary. Length is capped so a junk body can't become a
// giant KV key/value.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_EMAIL = 254; // RFC 5321 practical maximum

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return new Response("cubeon-waitlist ok\n", {
        headers: { "Content-Type": "text/plain; charset=utf-8", ...CORS },
      });
    }

    if (request.method === "GET") {
      return json({ count: await readCount(env) });
    }

    if (request.method === "POST") {
      return handleJoin(request, env);
    }

    return json({ error: "method not allowed" }, 405);
  },
};

async function handleJoin(request, env) {
  let email = "";
  try {
    const body = await request.json();
    email = (body && typeof body.email === "string" ? body.email : "").trim().toLowerCase();
  } catch (_) {
    return json({ error: "bad json" }, 400);
  }

  if (email.length > MAX_EMAIL || !EMAIL_RE.test(email)) {
    return json({ error: "invalid email" }, 422);
  }

  const key = `email:${await sha256(email)}`;

  // Already on the list: zero writes, just hand back the current tally so the
  // UI can show "you're already in line" without changing the number.
  if (await env.WAITLIST.get(key)) {
    return json({ count: await readCount(env), joined: false });
  }

  // KV writes are metered (1k/day on the free tier, account-wide). When the
  // day's budget is gone, a raw put() THROWS and surfaces as a 500 "error
  // code: 1101" - which the site shows as a generic failure and any client
  // hammers with retries. Translate it into a clean 429 so callers can back
  // off, and say so honestly.
  try {
    await env.WAITLIST.put(key, JSON.stringify({ email, at: Date.now() }));
  } catch (e) {
    if (String(e && e.message).includes("limit exceeded")) {
      return json({ error: "daily write budget exhausted - try again tomorrow" }, 429);
    }
    throw e;
  }
  const count = (await readCount(env)) + 1;
  try {
    await env.WAITLIST.put("count", String(count));
  } catch (e) {
    // The email itself is saved - the worst case is a miscounted tally, so
    // the signup still succeeds rather than erroring after the fact.
    if (String(e && e.message).includes("limit exceeded")) {
      return json({ count, joined: true });
    }
    throw e;
  }

  return json({ count, joined: true });
}

async function readCount(env) {
  const raw = await env.WAITLIST.get("count");
  const n = parseInt(raw || "0", 10);
  return Number.isFinite(n) && n >= 0 ? n : 0;
}

async function sha256(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...CORS,
    },
  });
}
