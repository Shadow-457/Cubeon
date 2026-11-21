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
  await call(handler, '/api/cosmetics?kind=all');
  assert.equal(reads, 2, 'cape pages and original model catalogs have separate caches');
  await call(handler, '/api/cosmetics?kind=all&models=2');
  assert.equal(reads, 3, 'expanded model catalogs have a separate cache');
  await call(handler, '/api/cosmetics?kind=all&models=2');
  assert.equal(reads, 3, 'expanded metadata is cached');
  await call(handler, '/api/cosmetics?kind=all&models=3');
  assert.equal(reads, 4, 'Aura catalogs have a separate cache');
  assert.deepEqual(calls[0].params, [0, false, false, false]);
  assert.deepEqual(calls[1].params, [0, true, false, false]);
  assert.deepEqual(calls[2].params, [0, true, true, false]);
  assert.deepEqual(calls[3].params, [0, true, true, true]);
  assert.ok(calls[0].sql.includes("kind = 'cape'"), 'old clients only see compatible capes');
  assert.match(calls[0].sql, /\$2::boolean AND kind IN \('pet', 'wing'\)/);
  assert.match(calls[0].sql, /\$3::boolean AND kind IN \('head', 'feet'\)/);
  assert.match(calls[0].sql, /\$4::boolean AND kind = 'aura'/);
  const kinds = ['cape', 'pet', 'wing', 'head', 'feet', 'aura'];
  const compatible = createHandler({query: async (sql, [, all, expanded, auras]) =>
    kinds.filter(kind => kind === 'cape' || (all && ['pet', 'wing'].includes(kind)) ||
      (expanded && ['head', 'feet'].includes(kind)) || (auras && kind === 'aura')).map(kind => ({...item, id: 'test-' + kind, kind}))});
  assert.deepEqual(body(await call(compatible)).items.map(entry => entry.kind), ['cape']);
  const originalPath = '/api/cosmetics?kind=all';
  const expandedPath = originalPath + '&models=2';
  const original = await call(compatible, originalPath);
  const expanded = await call(compatible, expandedPath);
  assert.deepEqual(body(original).items.map(entry => entry.kind), ['cape', 'pet', 'wing']);
  assert.deepEqual(body(expanded).items.map(entry => entry.kind), kinds.slice(0, 5));
  const withAura = await call(compatible, originalPath + '&models=3');
  assert.deepEqual(body(withAura).items.map(entry => entry.kind), kinds);
  assert.notEqual(withAura.headers.etag, expanded.headers.etag);
  assert.deepEqual((await call(compatible, expandedPath)).body, expanded.body,
    'Aura requests cannot contaminate older expanded catalogs');
  assert.notEqual(original.headers.etag, expanded.headers.etag);
  assert.deepEqual((await call(compatible, originalPath)).body, original.body,
    'expanded requests cannot contaminate older client catalogs');
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
    '?kind=unknown', '?kind=all&kind=all', '?kind=all&id=test-cape&sha256=' + sha,
    '?models=2', '?kind=all&models=1', '?kind=all&models=02', '?kind=all&models=',
    '?kind=all&models=2&models=2', '?models=2&id=test-cape&sha256=' + sha,
    '?kind=all&models=2&id=test-cape&sha256=' + sha,
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
  const modelBytes = Buffer.from('{"schema":1,"kind":"pet"}');
  const modelSha = createHash('sha256').update(modelBytes).digest('hex');
  const modelHandler = createHandler({query: async () => [{mime_type: 'application/vnd.cubeon.cosmetic+json',
    byte_size: modelBytes.length, sha256: modelSha, payload: modelBytes.toString('base64')}]});
  const modelFile = await call(modelHandler, '/api/cosmetics?id=my-pet&sha256=' + modelSha);
  assert.equal(modelFile.statusCode, 200);
  assert.deepEqual(modelFile.body, modelBytes);
  assert.match(modelFile.headers['content-disposition'], /my-pet\.json/);
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
