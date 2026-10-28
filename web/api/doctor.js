/* Vercel Node function. Provider credentials stay on the server. */
'use strict';
const {createHash,randomInt} = require('node:crypto');
const D = require('../assets/doctor-core.js');
const MODEL = 'kilo-auto/free';
const GATEWAY = 'https://ai-gateway.kilo.ai/api/v1/chat/completions';
const GROQ_GATEWAY = 'https://api.groq.com/openai/v1/chat/completions';
const MAX_BODY = 300000;
const RATE_LIMIT = 3;
const RATE_WINDOW_MS = 30 * 60 * 1000;
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
  for (const [k,times] of windows) {
    const recent = times.filter(time => now - time < RATE_WINDOW_MS);
    if (!recent.length) windows.delete(k);
    else windows.set(k,recent);
  }
  const times = windows.get(key) || [];
  if (times.length >= RATE_LIMIT) return {error:'rate_limited',scope:'visitor',
    retry_after:Math.max(1,Math.ceil((times[0] + RATE_WINDOW_MS - now)/1000))};
  if (inflight >= 8 || (!windows.has(key) && windows.size >= 2000))
    return {error:'ai_busy',retry_after:60};
  times.push(now);
  windows.set(key,times);
  return null;
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
function createHandler({fetch:fetcher=globalThis.fetch,env=process.env,now=Date.now,timeout=45000,groqTimeout=15000,budget=52000,chooseModel=randomInt}={}) {
  return async function doctor(req,res) {
    if (req.method !== 'POST') { res.setHeader('Allow','POST'); return reply(res,405,{error:'method_not_allowed'}); }
    if (!permitted(req,env)) return reply(res,403,{error:'origin_not_allowed'});
    if (!/^application\/json(?:\s*;|$)/i.test(req.headers['content-type'] || '')) return reply(res,415,{error:'json_required'});
    let data;
    try { data = await input(req); }
    catch (error) { return reply(res,error.status || 400,{error:error.status === 413 ? 'log_too_large' : 'invalid_report'}); }
    if (!data || Array.isArray(data) || typeof data.log !== 'string' || !data.log.trim() || data.log.length > D.MAX_LOG ||
        (data.version !== undefined && (typeof data.version !== 'string' || data.version.length > 240))) return reply(res,400,{error:'invalid_report'});
    const limited = throttled(req,now());
    if (limited) {
      res.setHeader('Retry-After',String(limited.retry_after));
      return reply(res,limited.error === 'rate_limited' ? 429 : 503,limited);
    }
    const groqKey = (env.GROQ_API_KEY || '').trim();
    const kiloKey = (env.KILO_API_KEY || '').trim();
    if (!groqKey && !kiloKey) return reply(res,503,{error:'ai_not_configured'});
    const attempts = [];
    if (groqKey) attempts.push({provider:'groq',key:groqKey,url:GROQ_GATEWAY,
      model:D.GROQ_MODELS[chooseModel(D.GROQ_MODELS.length)],limit:groqTimeout});
    if (kiloKey) for (let retry=0;retry<2;retry++) attempts.push({provider:'kilo',key:kiloKey,url:GATEWAY,model:MODEL,limit:timeout});
    const log = D.excerpt(data.log), context = {version:D.redactLog(data.version || '')};
    const cancel = new AbortController();
    const onClose = () => { if (!res.writableEnded) cancel.abort(); };
    res.on?.('close',onClose);
    inflight++;
    const deadline = Date.now() + budget;
    let failure = 'ai_provider_unavailable';
    let failureProvider;
    let upstreamRateLimited = false;
    try {
      // One random Groq model first. Any failure advances to Kilo's free
      // router, with one transient/invalid-guide retry inside the shared budget.
      for (const attempt of attempts) {
        const remaining = deadline - Date.now();
        if (remaining <= 0) break;
        try {
          const result = await D.withTimeout(async signal => {
            const tokens = attempt.provider === 'groq' ? {max_completion_tokens:3500,response_format:{type:'json_object'}} : {max_tokens:2600};
            const response = await fetcher(attempt.url,{
              method:'POST',headers:{Authorization:'Bearer ' + attempt.key,'Content-Type':'application/json'},signal,
              body:JSON.stringify({model:attempt.model,messages:D.prompt(log,context),...tokens,stream:false})
            });
            if (!response.ok) {
              await response.body?.cancel().catch(()=>{});
              throw Object.assign(new Error('provider_error'),{status:response.status});
            }
            let diagnosis;
            try {
              const body = await providerJson(response);
              diagnosis = D.parseDiagnosis({message:body.choices?.[0]?.message},log);
            } catch (error) {
              throw Object.assign(new Error('invalid_guide'),{kind:'ai_bad_response'});
            }
            diagnosis.provider = attempt.provider;
            diagnosis.model = attempt.provider === 'groq' ? attempt.model : 'Kilo auto/free';
            return diagnosis;
          },Math.min(attempt.limit,remaining),cancel.signal);
          if (!cancel.signal.aborted) return reply(res,200,result);
        } catch (error) {
          if (cancel.signal.aborted) return;
          failureProvider = attempt.provider;
          upstreamRateLimited = error.status === 429;
          failure = upstreamRateLimited ? 'rate_limited' : [401,403].includes(error.status) ? 'ai_credentials_invalid' :
            error.status === 402 ? 'ai_quota_exhausted' : [400,404,413].includes(error.status) ? 'ai_request_rejected' :
            error.message === 'request_timeout' ? 'ai_timeout' : error.kind || 'ai_provider_unavailable';
          // Groq authentication, quota and missing-model errors still fall
          // back to Kilo. Retrying these on the same provider cannot help.
          if (attempt.provider === 'kilo' && [400,401,402,403,404,413,429].includes(error.status)) break;
          // No provider error text or request contents are logged/returned.
        }
      }
      if (upstreamRateLimited) res.setHeader('Retry-After','60');
      return reply(res,upstreamRateLimited ? 429 : 503,{error:failure,provider:failureProvider});
    } finally { inflight--; res.off?.('close',onClose); }
  };
}
module.exports = createHandler();
module.exports.createHandler = createHandler;
