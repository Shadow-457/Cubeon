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
 *   POST /unsubscribe {email} -> { removed, count } delete an email record
 *   GET  /unsubscribe?email=... -> a plain HTML "you're off the list" page, for
 *                                  the unsubscribe link inside an email
 *   GET  /health      -> plain-text OK, for debugging by hand
 *
 * The unsubscribe route is what a mailing list legally needs (a working, one
 * click opt-out) and it doubles as the "delete my data" path: it removes the KV
 * record and drops the person from the tally, in two writes at most. It is
 * deliberately reachable by GET, because an email link cannot POST - the worst
 * an abuser can do with it is unsubscribe an address they already know.
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
      // A link in an email can only be a GET, so the unsubscribe link lands
      // here and answers with a plain HTML page (the JSON route below is for
      // clients). Nothing else about GET changes.
      if (url.pathname === "/unsubscribe") {
        return handleUnsubscribeLink(url, env);
      }
      return json({ count: await readCount(env) });
    }

    if (request.method === "POST") {
      // Two POST shapes, one body cap: the signup (default) and the deletion /
      // unsubscribe request a mailing link points at.
      if (url.pathname === "/unsubscribe") {
        return handleUnsubscribe(request, env);
      }
      return handleJoin(request, env);
    }

    return json({ error: "method not allowed" }, 405);
  },
};

// The only field is one email; anything bigger is not a real client. Checked
// against the declared Content-Length AND the decoded length (the header is a
// hint a client controls), matching the sibling workers - an uncapped
// request.json() would parse an arbitrarily large body into memory.
const MAX_BODY_BYTES = 1024;

// Shared by the signup and the deletion paths: one JSON body, one `email`
// field, capped at MAX_BODY_BYTES. Returns { error } (ready to become a
// response) or { email } already trimmed and lower-cased.
async function readEmail(request) {
  const declared = Number(request.headers.get("Content-Length") || "0");
  let raw = "";
  if (declared <= MAX_BODY_BYTES) {
    try {
      raw = await request.text();
    } catch (_) {
      raw = "";
    }
  }
  if (raw.length > MAX_BODY_BYTES) return { error: "bad json" };
  let body;
  try {
    body = JSON.parse(raw);
  } catch (_) {
    return { error: "bad json" };
  }
  const email = (body && typeof body.email === "string" ? body.email : "").trim().toLowerCase();
  if (email.length > MAX_EMAIL || !EMAIL_RE.test(email)) {
    return { error: "invalid email" };
  }
  return { email };
}

function emailError(parsed) {
  return json({ error: parsed.error }, parsed.error === "invalid email" ? 422 : 400);
}

async function handleJoin(request, env) {
  const parsed = await readEmail(request);
  if (parsed.error) return emailError(parsed);
  const email = parsed.email;

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

// "Delete my data" / unsubscribe over JSON. A mailing list has to offer a
// working opt-out, and anyone can ask for their record to go: this removes the
// KV record and drops the tally (never below zero). Two writes at most - the
// same budget a signup costs, so a deletion wave can't drain the daily quota
// any faster than the signups that put the addresses there.
async function handleUnsubscribe(request, env) {
  const parsed = await readEmail(request);
  if (parsed.error) return emailError(parsed);
  return json(await deleteEmail(env, parsed.email));
}

// The same deletion, for a human clicking a link in an email. Answers with a
// small self-contained page: no assets, no fonts, no third-party anything.
async function handleUnsubscribeLink(url, env) {
  const raw = (url.searchParams.get("email") || "").trim().toLowerCase();
  if (raw.length > MAX_EMAIL || !EMAIL_RE.test(raw)) {
    return unsubscribePage("That link is missing a valid address. Copy the address out of the email and send it to the contact address in the footer, and it will be removed by hand.", false);
  }
  const data = await deleteEmail(env, raw);
  return unsubscribePage(data.removed
    ? "You're off the list. The address is deleted and nothing else was kept - no copy, no backup, no \"suppression list\"."
    : "That address wasn't on the list, so there was nothing to delete. If you got an email anyway, tell the contact address in the footer.", data.removed);
}

// The one implementation both routes share. Returns { removed, count } - never
// a Response, so the HTML route can tell a successful deletion from a no-op.
async function deleteEmail(env, email) {
  const key = `email:${await sha256(email)}`;
  if (!(await env.WAITLIST.get(key))) {
    // Never joined, or already deleted: report the truth rather than pretend.
    return { removed: false, count: await readCount(env) };
  }
  await env.WAITLIST.delete(key);

  const count = Math.max(0, (await readCount(env)) - 1);
  try {
    await env.WAITLIST.put("count", String(count));
  } catch (e) {
    // The record is gone, which is the part that matters; a stale tally is
    // cosmetic, so don't fail the deletion over it.
    if (String(e && e.message).includes("limit exceeded")) {
      return { removed: true, count: await readCount(env) };
    }
    throw e;
  }
  return { removed: true, count };
}

function unsubscribePage(message, removed) {
  const colour = removed ? "#83C13D" : "#E6B23C";
  return new Response(
    `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex" />
<title>${removed ? "Removed" : "Nothing to remove"} — Cubeon</title></head>
<body style="margin:0;background:#FFFCF3;color:#4c5a40;font-family:system-ui,sans-serif">
  <main style="max-width:640px;margin:12vh auto;padding:28px;border:3px solid #20260F;background:#fff;box-shadow:8px 8px 0 #20260F">
    <p style="margin:0 0 14px;display:inline-block;background:${colour};border:2px solid #20260F;padding:6px 10px;font-weight:700;color:#20260F">
      ${removed ? "DELETED" : "NO RECORD"}
    </p>
    <p style="font-size:17px;font-weight:600;line-height:1.6;color:#20260F;margin:0">${message}</p>
    <p style="font-size:14px;font-weight:600;line-height:1.6;margin:18px 0 0">Cubeon only ever stored the address and the time it arrived. The launcher itself never needed one.</p>
  </main>
</body></html>`,
    { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", ...CORS } },
  );
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
