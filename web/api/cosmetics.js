/* Public read-only catalog. Only the owner CLI writes to Neon. */
'use strict';
const {createHash} = require('node:crypto');
const {createQuery} = require('../server/neon.js');
const PAGE_SIZE = 12;
const MAX_FILE_BYTES = 2097152;
const ID = /^[a-z][a-z0-9_-]{2,63}$/;
const SHA = /^[a-f0-9]{64}$/;
const LIST_SQL = `SELECT id, kind, name, description, mime_type, byte_size, sha256,
  encode(preview_png, 'base64') AS preview FROM cubeon_cosmetics
  WHERE published AND ($2::boolean OR kind = 'cape') ORDER BY updated_at DESC, id LIMIT 13 OFFSET $1`;
const FILE_SQL = `SELECT mime_type, byte_size, sha256, encode(file_bytes, 'base64') AS payload
  FROM cubeon_cosmetics WHERE published AND id = $1 AND sha256 = $2`;

function send(req, res, status, body, type = 'application/json; charset=utf-8', cache = 'no-store') {
  const bytes = Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body));
  res.statusCode = status;
  res.setHeader('Content-Type', type);
  res.setHeader('Cache-Control', cache);
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Content-Length', bytes.length);
  res.end(req.method === 'HEAD' ? undefined : bytes);
}

function createHandler({env = process.env, fetch: fetcher = globalThis.fetch,
                        now = Date.now, query: suppliedQuery} = {}) {
  let query, inflight = 0;
  const visitors = new Map(), pages = new Map(), pending = new Map();
  function throttle(req) {
    const time = now();
    const raw = String(req.headers['x-vercel-forwarded-for'] || req.headers['x-forwarded-for'] ||
      req.socket?.remoteAddress || 'unknown').split(',')[0].trim();
    const key = createHash('sha256').update(raw).digest('hex');
    // Fixed one-minute windows, bounded memory, no raw addresses retained.
    for (const [id, entry] of visitors) if (time - entry.start >= 60000) visitors.delete(id);
    const entry = visitors.get(key);
    if (entry && entry.count >= 120) return 429;
    if (inflight >= 8 || (!entry && visitors.size >= 2000)) return 503;
    visitors.set(key, {start: entry?.start ?? time, count: (entry?.count || 0) + 1});
    return 0;
  }
  async function list(offset, all) {
    const key = `${offset}:${all}`;
    const cached = pages.get(key);
    if (cached && now() - cached.time < 60000) return cached.body;
    if (pending.has(key)) return pending.get(key);
    const job = (async () => {
      const rows = await query(LIST_SQL, [offset, all], 450000);
      const body = {schema: 1, offset, page_size: PAGE_SIZE, has_more: rows.length > PAGE_SIZE,
        items: rows.slice(0, PAGE_SIZE).map(row => ({id: row.id, kind: row.kind,
          name: row.name, description: row.description, mime_type: row.mime_type,
          byte_size: Number(row.byte_size), sha256: row.sha256,
          preview_png: String(row.preview).replace(/\s/g, '')}))};
      if (pages.size >= 64) pages.delete(pages.keys().next().value);
      pages.set(key, {time: now(), body});
      return body;
    })();
    pending.set(key, job);
    try { return await job; } finally { pending.delete(key); }
  }
  return async function cosmetics(req, res) {
    if (!['GET', 'HEAD'].includes(req.method)) {
      res.setHeader('Allow', 'GET, HEAD');
      return send(req, res, 405, {error: 'method_not_allowed'});
    }
    const url = new URL(req.url, 'https://cubeon.invalid');
    const allowed = new Set(['offset', 'id', 'sha256', 'kind']);
    if ([...url.searchParams.keys()].some(key => !allowed.has(key) || url.searchParams.getAll(key).length !== 1))
      return send(req, res, 400, {error: 'invalid_query'});
    const id = url.searchParams.get('id'), sha = url.searchParams.get('sha256');
    const offsetText = url.searchParams.get('offset') ?? '0';
    const kind = url.searchParams.get('kind');
    if (kind !== null && (kind !== 'all' || id !== null || sha !== null))
      return send(req, res, 400, {error: 'invalid_query'});
    if ((id !== null || sha !== null) ? (!ID.test(id || '') || !SHA.test(sha || '') || url.searchParams.has('offset'))
        : (!/^(0|[1-9][0-9]{0,4})$/.test(offsetText) || Number(offsetText) > 10000))
      return send(req, res, 400, {error: 'invalid_query'});
    const limited = throttle(req);
    if (limited) {
      res.setHeader('Retry-After', '60');
      return send(req, res, limited, {error: limited === 429 ? 'rate_limited' : 'store_busy'});
    }
    inflight++;
    try {
      query ||= suppliedQuery || createQuery({connection: env.NEON_DATABASE_URL || env.DATABASE_URL, fetcher});
      if (id) {
        const [file] = await query(FILE_SQL, [id, sha]);
        if (!file) return send(req, res, 404, {error: 'cosmetic_unavailable'});
        const data = Buffer.from(file.payload, 'base64');
        if (file.sha256 !== sha || data.length !== Number(file.byte_size) ||
            !data.length || data.length > MAX_FILE_BYTES ||
            !['image/png', 'image/gif', 'application/vnd.cubeon.cosmetic+json'].includes(file.mime_type) ||
            createHash('sha256').update(data).digest('hex') !== sha) throw new Error('invalid_file');
        res.setHeader('Content-Disposition', `attachment; filename="${id}.${file.mime_type === 'image/gif' ? 'gif' : file.mime_type === 'image/png' ? 'png' : 'json'}"`);
        res.setHeader('ETag', `"${sha}"`);
        if (req.headers['if-none-match'] === `"${sha}"`) {
          res.statusCode = 304;
          res.setHeader('Cache-Control', 'public, max-age=31536000, s-maxage=31536000, immutable');
          return res.end();
        }
        return send(req, res, 200, data, file.mime_type,
          'public, max-age=31536000, s-maxage=31536000, immutable');
      }
      const body = await list(Number(offsetText), kind === 'all');
      const etag = '"' + createHash('sha256').update(JSON.stringify(body)).digest('hex') + '"';
      res.setHeader('ETag', etag);
      if (req.headers['if-none-match'] === etag) {
        res.statusCode = 304;
        res.setHeader('Cache-Control', 'public, max-age=60, s-maxage=60');
        return res.end();
      }
      return send(req, res, 200, body, undefined, 'public, max-age=60, s-maxage=60');
    } catch {
      res.setHeader('Retry-After', '60');
      return send(req, res, 503, {error: 'store_unavailable'});
    } finally { inflight--; }
  };
}

module.exports = createHandler();
module.exports.createHandler = createHandler;
