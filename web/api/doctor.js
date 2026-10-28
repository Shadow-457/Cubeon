/* Vercel Node function. The browser never receives the Kilo credential. */
'use strict';
const {createHash} = require('node:crypto');
const D = require('../assets/doctor-core.js');
const MODEL = 'kilo-auto/free';
const GATEWAY = 'https://ai-gateway.kilo.ai/api/v1/chat/completions';
const MAX_BODY = 300000;
const windows = new Map();
let inflight = 0;

function reply(res, status, value) {
  res.statusCode = status;
  res.setHeader('Content-Type','application/json; charset=utf-8');
  res.setHeader('Cache-Control','no-store');
  res.setHeader('X-Content-Type-Options','nosniff');
  res.end(JSON.stringify(value));
}
function permitted(req, env) {
  const allowed = new Set(['https://cubeon.ylet.online','https://cubeon.vercel.app']);
  for (const host of [env.VERCEL_URL,env.VERCEL_BRANCH_URL,env.VERCEL_PROJECT_PRODUCTION_URL]) {
    if (host && /^[a-z0-9.-]+$/i.test(host)) allowed.add('https://' + host);
  }
  const origin = req.headers.origin;
  if (typeof origin !== 'string') return false;
  if (/^http:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?$/.test(origin) &&
      new URL(origin).host === req.headers.host && env.NODE_ENV !== 'production') return true;
  return allowed.has(origin) && req.headers['sec-fetch-site'] !== 'cross-site';
}
function throttled(req, now) {
  // Instance-local fallback, no log or raw IP retention. For globally enforced
  // limits configure the hosting firewall; instances do not share this map.
  const raw = String(req.headers['x-vercel-forwarded-for'] || req.headers['x-forwarded-for'] || req.socket?.remoteAddress || 'unknown').split(',')[0].trim();
  const key = createHash('sha256').update(raw).digest('hex');
  for (const [k,v] of windows) if (now - v.start >= 60000) windows.delete(k);
  let value = windows.get(key);
  if (!value) {
    if (windows.size >= 2000) return true;
    value = {start:now,count:0}; windows.set(key,value);
  }
  return ++value.count > 5 || inflight >= 8;
}
async function input(req) {
  const declared = Number(req.headers['content-length']);
  if (Number.isFinite(declared) && declared > MAX_BODY) throw Object.assign(new Error('large'),{status:413});
  if (req.body !== undefined) {
    const bytes = typeof req.body === 'string' || Buffer.isBuffer(req.body) ? req.body : JSON.stringify(req.body);
    if (Buffer.byteLength(bytes) > MAX_BODY) throw Object.assign(new Error('large'),{status:413});
    return typeof req.body === 'object' && !Buffer.isBuffer(req.body) ? req.body : JSON.parse(String(req.body));
  }
  let total = 0; const chunks=[];
  for await (const part of req) {
    const chunk = Buffer.from(part); total += chunk.length;
    if (total > MAX_BODY) throw Object.assign(new Error('large'),{status:413});
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
async function providerJson(response) {
  // Bound gateway output too; a malformed upstream must not exhaust memory.
  const reader = response.body.getReader(), chunks=[]; let total=0;
  try {
    while (true) {
      const {value,done} = await reader.read(); if (done) break;
      total += value.byteLength;
      if (total > 100000) throw new Error('large_response');
      chunks.push(Buffer.from(value));
    }
  } finally { await reader.cancel().catch(()=>{}); }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
function createHandler({fetch:fetcher=globalThis.fetch,env=process.env,now=Date.now,timeout=45000,budget=52000}={}) {
  return async function doctor(req,res) {
    if (req.method !== 'POST') { res.setHeader('Allow','POST'); return reply(res,405,{error:'method_not_allowed'}); }
    if (!permitted(req,env)) return reply(res,403,{error:'origin_not_allowed'});
    if (!/^application\/json(?:\s*;|$)/i.test(req.headers['content-type'] || '')) return reply(res,415,{error:'json_required'});
    let data;
    try { data = await input(req); }
    catch (error) { return reply(res,error.status || 400,{error:error.status === 413 ? 'log_too_large' : 'invalid_report'}); }
    if (!data || Array.isArray(data) || typeof data.log !== 'string' || !data.log.trim() || data.log.length > D.MAX_LOG ||
        (data.version !== undefined && (typeof data.version !== 'string' || data.version.length > 240))) return reply(res,400,{error:'invalid_report'});
    if (throttled(req,now())) { res.setHeader('Retry-After','60'); return reply(res,429,{error:'rate_limited'}); }
    const apiKey = env.KILO_API_KEY;
    if (!apiKey) return reply(res,503,{error:'ai_unavailable'});
    const log = D.excerpt(data.log), context = {version:D.redactLog(data.version || '')};
    const cancel = new AbortController();
    const onClose = () => { if (!res.writableEnded) cancel.abort(); };
    res.on?.('close',onClose);
    inflight++;
    const deadline = Date.now() + budget;
    try {
      // Kilo manages free-model routing. Retry once for transient errors or
      // an invalid guide; never substitute a paid model or accept client prompts.
      for (let attempt=0; attempt<2; attempt++) {
        const remaining = deadline - Date.now();
        if (remaining <= 0) break;
        try {
          const result = await D.withTimeout(async signal => {
            const response = await fetcher(GATEWAY,{
              method:'POST',headers:{Authorization:'Bearer ' + apiKey,'Content-Type':'application/json'},signal,
              body:JSON.stringify({model:MODEL,messages:D.prompt(log,context),max_tokens:2600,stream:false})
            });
            if (!response.ok) throw Object.assign(new Error('provider_error'),{status:response.status});
            const body = await providerJson(response);
            const diagnosis = D.parseDiagnosis({message:body.choices?.[0]?.message},log);
            diagnosis.model = 'Kilo auto/free';
            return diagnosis;
          },Math.min(timeout,remaining),cancel.signal);
          if (!cancel.signal.aborted) return reply(res,200,result);
        } catch (error) {
          if (cancel.signal.aborted) return;
          if (error.status === 429) { res.setHeader('Retry-After','60'); return reply(res,429,{error:'rate_limited'}); }
          if ([400,401,402,403].includes(error.status)) return reply(res,503,{error:'ai_unavailable'});
          // No provider error text or request contents are logged/returned.
        }
      }
      return reply(res,503,{error:'ai_unavailable'});
    } finally { inflight--; res.off?.('close',onClose); }
  };
}
module.exports = createHandler();
module.exports.createHandler = createHandler;
