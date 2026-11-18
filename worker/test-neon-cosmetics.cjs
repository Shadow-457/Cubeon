'use strict';
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const {createHandler} = require('../web/api/cosmetics.js');
const {createQuery, endpoint} = require('../web/server/neon.js');
const bytes = Buffer.from('verified test cape');
const sha = createHash('sha256').update(bytes).digest('hex');
const item = {id: 'test-cape', kind: 'cape', name: 'Test Cape', description: 'Sample',
  mime_type: 'image/png', byte_size: String(bytes.length), sha256: sha, preview: 'cHJldmlldw=='};
function response() {
  return {headers: {}, setHeader(k, v) {this.headers[k.toLowerCase()] = v;},
    end(body) {this.body = body;}};
}
async function call(handler, path = '/api/cosmetics', method = 'GET', headers = {}) {
  const res = response();
  await handler({url: path, method, headers}, res);
  return res;
}
const body = res => JSON.parse(res.body.toString());

(async () => {
  let reads = 0;
  const calls = [];
  const query = async (sql, params) => {
    reads++; calls.push({sql, params});
    return sql.includes('AS payload') ? [{mime_type: item.mime_type, byte_size: item.byte_size,
      sha256: sha, payload: bytes.toString('base64')}] : [item];
  };
  const handler = createHandler({query});
  const catalog = await call(handler);
  assert.equal(catalog.statusCode, 200);
  assert.deepEqual(body(catalog).items, [{...item, byte_size: bytes.length,
    preview: undefined, preview_png: item.preview}].map(({preview, ...entry}) => entry));
  assert.ok(!catalog.body.includes('NEON_DATABASE_URL'));
  const repeated = await call(handler);
  assert.equal(reads, 1, 'metadata is cached');
  assert.deepEqual(repeated.body, catalog.body);
  const conditional = await call(handler, '/api/cosmetics', 'GET', {'if-none-match': catalog.headers.etag});
  assert.equal(conditional.statusCode, 304);
  assert.equal(conditional.body, undefined);
  const head = await call(handler, '/api/cosmetics', 'HEAD');
  assert.equal(head.statusCode, 200);
  assert.equal(head.body, undefined);
  assert.equal(head.headers['content-length'], catalog.body.length);
  const filePath = '/api/cosmetics?id=test-cape&sha256=' + sha;
  const file = await call(handler, filePath);
  assert.equal(file.statusCode, 200);
  assert.deepEqual(file.body, bytes);
  assert.equal(file.headers.etag, '"' + sha + '"');
  assert.match(file.headers['cache-control'], /immutable/);
  assert.deepEqual(calls.at(-1).params, ['test-cape', sha]);
  assert.ok(calls.at(-1).sql.includes('id = $1 AND sha256 = $2'));
  for (const method of ['POST', 'PUT', 'DELETE', 'OPTIONS']) {
    assert.equal((await call(handler, filePath, method)).statusCode, 405);
  }
  for (const path of ['?id=test-cape', '?sha256=' + sha, '?offset=-1', '?offset=1e2',
    '?offset=10001', '?offset=1&offset=2', '?url=https://elsewhere.invalid',
    '?id=../../private&sha256=' + sha, '?id=a%27%3Bdrop%20table&sha256=' + sha]) {
    assert.equal((await call(handler, '/api/cosmetics' + path)).statusCode, 400, path);
  }
  const missing = createHandler({query: async () => []});
  assert.equal((await call(missing, filePath)).statusCode, 404);
  const broken = createHandler({query: async () => {throw new Error('private credential');}});
  const failure = await call(broken);
  assert.equal(failure.statusCode, 503);
  assert.ok(!failure.body.includes('private credential'));
  assert.equal((await call(createHandler({env: {}}))).statusCode, 503);
  const corrupt = createHandler({query: async () => [{mime_type: 'image/png', byte_size: bytes.length,
    sha256: sha, payload: Buffer.from('changed').toString('base64')}]});
  assert.equal((await call(corrupt, filePath)).statusCode, 503);
  let clock = 0, rateReads = 0;
  const limited = createHandler({now: () => clock, query: async () => {rateReads++; return [item];}});
  for (let i = 0; i < 120; i++) assert.equal((await call(limited)).statusCode, 200);
  const refusal = await call(limited);
  assert.equal(refusal.statusCode, 429);
  assert.equal(rateReads, 1);
  clock = 60001;
  assert.equal((await call(limited)).statusCode, 200);
  assert.equal(rateReads, 2);
  const pagination = createHandler({query: async () => Array.from({length: 13}, (_, i) => ({...item, id: 'cape-' + i}))});
  const page = body(await call(pagination, '/api/cosmetics?offset=12'));
  assert.equal(page.items.length, 12);
  assert.equal(page.has_more, true);
  assert.equal(page.offset, 12);
  const connection = 'postgresql://owner:test-password@ep-example-pooler.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require';
  assert.equal(endpoint(connection), 'https://ep-example.c-9.us-east-2.aws.neon.tech/sql');
  for (const bad of ['https://neon.tech', 'postgresql://x:y@evil.invalid/db', 'postgresql://x@y.neon.tech/db'])
    assert.throws(() => endpoint(bad));
  const neon = createQuery({connection, fetcher: async (url, init) => {
    assert.equal(url, endpoint(connection));
    assert.equal(init.redirect, 'error');
    assert.equal(init.headers['Neon-Connection-String'], connection);
    assert.deepEqual(JSON.parse(init.body), {query: 'SELECT $1', params: ['value']});
    return new Response(JSON.stringify({rows: [{value: 'ok'}]}));
  }});
  assert.deepEqual(await neon('SELECT $1', ['value']), [{value: 'ok'}]);
  console.log('Passed Neon catalog, downloads, SQL parameters, cache, HEAD, errors, pagination and rate-limit checks.');
})().catch(error => {console.error(error); process.exitCode = 1;});
