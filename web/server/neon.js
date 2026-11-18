'use strict';

// Neon's SQL-over-HTTPS protocol, also used by its official serverless driver.
// https://github.com/neondatabase/serverless -- no client-side database access.
function endpoint(connection) {
  const url = new URL(connection);
  if (!['postgres:', 'postgresql:'].includes(url.protocol) || !url.username ||
      !url.password || !/^ep-[a-z0-9-]+\.[a-z0-9.-]+\.neon\.tech$/.test(url.hostname) ||
      !url.pathname.slice(1) || url.hash) throw new Error('invalid_neon_configuration');
  return 'https://' + url.hostname.replace('-pooler.', '.') + '/sql';
}

async function readJson(response, limit) {
  const reader = response.body.getReader(), chunks = [];
  let size = 0;
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error('neon_response_too_large');
      chunks.push(Buffer.from(value));
    }
  } finally { await reader.cancel().catch(() => {}); }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function createQuery({connection, fetcher = globalThis.fetch, timeout = 15000}) {
  const destination = endpoint(connection);
  return async (query, params = [], limit = 3500000) => {
    const response = await fetcher(destination, {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(timeout),
      headers: {'Content-Type': 'application/json', 'Neon-Connection-String': connection,
        'Neon-Raw-Text-Output': 'true', 'Neon-Array-Mode': 'false'},
      body: JSON.stringify({query, params}),
    });
    if (!response.ok) {
      await response.body?.cancel().catch(() => {});
      // Upstream messages may contain private configuration; never return them.
      throw new Error('neon_query_failed');
    }
    const data = await readJson(response, limit);
    if (!Array.isArray(data.rows)) throw new Error('invalid_neon_response');
    return data.rows;
  };
}

module.exports = {createQuery, endpoint};
