'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const web = path.join(root, 'web');
function response() {
  return {headers: {}, setHeader(key, value) { this.headers[key.toLowerCase()] = value; }, end(body) {this.body = body;}};
}
const retired = require('../web/api/retired.js');
for (const method of ['GET', 'HEAD', 'POST']) {
  const res = response();
  retired({url: '/cubeon-bench/workspace?code=200', method}, res);
  assert.equal(res.statusCode, 410);
  assert.equal(res.headers['x-robots-tag'], 'noindex');
  assert.equal(res.headers['cache-control'], 'no-store');
  if (method === 'HEAD') assert.equal(res.body, undefined);
  else assert.ok(!res.body.includes('Cubeon Bench'));
}
const status = require('../web/api/status.js');
for (const code of [403, 404, 429, 500, 502, 503]) {
  const res = response();
  status({url: '/api/status?code=' + code, method: 'GET'}, res);
  assert.equal(res.statusCode, code);
}
console.log('PASS retired editor returns 410/noindex, HEAD and status pages');

async function browserChecks() {
  const {chromium} = require('playwright');
  const browser = await chromium.launch({headless: true,
    ...(process.env.CUBEON_TEST_CHROMIUM ? {executablePath: process.env.CUBEON_TEST_CHROMIUM} : {})});
  const html = fs.readFileSync(path.join(web, 'store.html'), 'utf8');
  const decode = s => s.replace(/&(amp|quot|lt|gt|#x27);/g, (_, code) => ({amp:'&',quot:'"',lt:'<',gt:'>','#x27':"'"})[code]);
  const png = fs.readFileSync(path.join(web, 'assets/favicon.png')).toString('base64');
  const snapshot = [...html.matchAll(/data-id="([^"]+)" data-sha="([^"]+)" data-kind="([^"]+)" data-name="([^"]+)" data-description="([^"]*)"/g)]
    .map(m => ({id:m[1],sha256:m[2],kind:m[3],name:decode(m[4]),description:decode(m[5]),preview_png:png}));
  const bundled = Object.values(JSON.parse(fs.readFileSync(path.join(root, 'assets/cosmetics/store-catalog.json'), 'utf8')))
    .flatMap(page => page.items);
  const revisions = items => items.map(({id, kind, sha256}) => ({id, kind, sha256}))
    .sort((a, b) => a.id.localeCompare(b.id));
  assert.deepEqual(revisions(snapshot), revisions(bundled), 'website posters match every bundled Store revision');
  assert.ok(snapshot.length >= 27, 'existing owner collection remains available');
  for (const id of ['cubeon-morpho-orbit', 'cubeon-zephyr-sprite', 'cubeon-dune-runner-cap',
                    'cubeon-cloudlet-headwings', 'cubeon-dawnflare-halo']) {
    assert.ok(!snapshot.some(item => item.id === id));
  }
  for (const id of ['cubeon-midnight-cowl', 'cubeon-crimson-web-mask', 'cubeon-winter-snowcap']) {
    assert.ok(snapshot.some(item => item.id === id));
  }
  const captures = path.join(root, 'archive/ui-captures/store');
  fs.mkdirSync(captures, {recursive:true});
  let mode = 'live', items = snapshot, catalogGate;
  const route = async request => {
    const url = new URL(request.request().url());
    if (url.hostname !== 'cubeon.test') return request.abort();
    if (url.pathname === '/api/cosmetics') {
      assert.equal(url.searchParams.get('models'), '3');
      const offset = Number(url.searchParams.get('offset'));
      if (mode === 'error') return request.fulfill({status:503,json:{error:'store_unavailable'}});
      if (offset > 0 && mode === 'late-error') return request.fulfill({status:503,json:{error:'store_unavailable'}});
      if (offset > 0 && catalogGate) await catalogGate;
      const rows = mode === 'duplicate' ? [items[0], items[0]] : items.slice(offset,offset+12);
      return request.fulfill({json:{schema:1,offset,page_size:12,has_more:mode !== 'duplicate' && items.length>offset+12,items:rows}});
    }
    let file = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
    if (!path.extname(file)) file += '.html';
    const local = path.join(web,file);
    if (!local.startsWith(web + path.sep) || !fs.existsSync(local)) return request.fulfill({status:404,body:'Not found'});
    return request.fulfill({path:local});
  };
  for (const width of [1440,768,390,320]) {
    const page = await browser.newPage({viewport:{width,height:1000},reducedMotion:'reduce'});
    const errors=[];
    page.on('pageerror',error=>errors.push(String(error)));
    await page.route('**/*',route);
    await page.goto('https://cubeon.test/store');
    await page.waitForFunction(()=>document.getElementById('storeStatus').textContent.includes('Download these cosmetics in Cubeon'));
    assert.equal(await page.locator('.store-card').count(),snapshot.length);
    for (const image of await page.locator('.store-card img').all()) {
      await image.scrollIntoViewIfNeeded();
      await image.evaluate(async img=>{await img.decode();});
      assert.ok(await image.evaluate(img=>img.naturalWidth===420));
    }
    await page.locator('[data-store-kind="wing"]').click();
    assert.equal(await page.locator('.store-card:visible').count(),snapshot.filter(item => item.kind === 'wing').length);
    await page.locator('#storeSearch').fill('Obsidian');
    assert.equal(await page.locator('.store-card:visible').count(),1);
    await page.locator('.store-card:visible .store-view').click();
    assert.ok(await page.locator('#storeDialog').isVisible());
    assert.equal(await page.locator('#storeDialogTitle').textContent(),'Obsidian Seraph Wings');
    await page.keyboard.press('Escape');
    assert.ok(!(await page.locator('#storeDialog').isVisible()));
    await page.locator('#storeSearch').fill('not-an-existing-cosmetic');
    assert.ok(await page.locator('#storeEmpty').isVisible());
    await page.locator('#storeSearch').fill('');
    await page.locator('[data-store-kind="all"]').click();
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:path.join(captures,'store-'+width+'.png'),fullPage:true});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1), 'horizontal overflow at '+width);
    await page.goto('https://cubeon.test/docs');
    const notes=page.locator('#project-notes');
    assert.equal(await notes.getAttribute('open'),null);
    await notes.locator('summary').scrollIntoViewIfNeeded();
    await notes.locator('summary').focus();
    await page.keyboard.press('Enter');
    assert.ok((await notes.textContent()).includes('Hamza Shahbaz'));
    assert.ok((await notes.textContent()).includes('shadow457'));
    assert.ok(await notes.locator('p').isVisible());
    assert.deepEqual(errors,[]);
    await page.close();
  }
  const page=await browser.newPage();
  await page.route('**/*',route);
  items=[...snapshot,{...snapshot[0],id:'test-butterfly-aura',sha256:'b'.repeat(64),name:'Celestial Butterfly Aura',kind:'aura'}];
  await page.goto('https://cubeon.test/store');
  await page.waitForFunction(()=>document.querySelector('#storeStatus').textContent.includes('Download these cosmetics in Cubeon'));
  await page.locator('[data-store-kind="aura"]').click();
  assert.equal(await page.locator('.store-card:visible').count(),1);
  await page.locator('.store-card:visible .store-view').click();
  assert.equal(await page.locator('#storeDialogTitle').textContent(),'Celestial Butterfly Aura');
  assert.ok((await page.locator('#storeDialogEquip').textContent()).includes('equip it in Aura'));
  await page.keyboard.press('Escape');
  items=[...snapshot,{...snapshot[0],id:'new-item',sha256:'a'.repeat(64),name:'<svg onload="alert(1)">',kind:'pet'}];
  await page.goto('https://cubeon.test/store');
  await page.waitForFunction(count=>document.querySelectorAll('.store-card').length===count,snapshot.length+1);
  const extra=page.locator('[data-id="new-item"]');
  assert.equal(await extra.locator('h2').textContent(),'<svg onload="alert(1)">');
  assert.equal(await extra.locator('svg').count(),0);
  assert.ok((await extra.locator('img').getAttribute('src')).startsWith('data:image/png;base64,'));
  for (const failure of ['error','duplicate']) {
    mode=failure;
    await page.reload();
    await page.waitForFunction(()=>document.getElementById('storeStatus').textContent.includes('Couldn’t load the latest items'));
    assert.equal(await page.locator('.store-card').count(),snapshot.length,'failed catalog leaves fallback intact');
  }
  items=[{...snapshot[0],id:'test-butterfly-aura',sha256:'b'.repeat(64),name:'Celestial Butterfly Aura',kind:'aura'},...snapshot];
  mode='live';
  let releaseCatalog;
  catalogGate=new Promise(resolve=>{releaseCatalog=resolve;});
  await page.reload();
  await page.locator('[data-store-kind="aura"]').click();
  await page.locator('[data-id="test-butterfly-aura"]').waitFor({state:'visible'});
  assert.ok(!(await page.locator('#storeStatus').textContent()).includes('Download these cosmetics in Cubeon'));
  await page.locator('.store-card:visible .store-view').click();
  assert.equal(await page.locator('#storeDialogTitle').textContent(),'Celestial Butterfly Aura','Aura is usable before later pages complete');
  await page.keyboard.press('Escape');
  releaseCatalog();
  catalogGate=null;
  await page.waitForFunction(()=>document.getElementById('storeStatus').textContent.includes('Download these cosmetics in Cubeon'));
  assert.equal(await page.locator('.store-card').count(),items.length);
  mode='late-error';
  await page.reload();
  await page.waitForFunction(()=>document.getElementById('storeStatus').textContent.includes('Couldn’t load the latest items'));
  await page.locator('[data-store-kind="aura"]').click();
  assert.equal(await page.locator('.store-card:visible').count(),1,'later failure retains a validated Aura');
  assert.equal(await page.locator('.store-card').count(),snapshot.length+1,'later failure retains the offline collection');
  await page.close();
  const plain=await browser.newPage({javaScriptEnabled:false,viewport:{width:390,height:800}});
  await plain.route('**/*',route);
  await plain.goto('https://cubeon.test/store');
  assert.equal(await plain.locator('.store-card').count(),snapshot.length);
  assert.ok(await plain.locator('.store-card h2').first().isVisible());
  assert.ok(!(await plain.locator('#storeTools').isVisible()));
  assert.ok(await plain.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1));
  await browser.close();
  console.log(`PASS live Store, ${snapshot.length} posters, matching bundled revisions, retired entries removed, two masks and Christmas hat, filters/search/dialogs, new uploads, malformed/offline fallback, quiet keyboard-accessible credit, and 1440/768/390/320px layouts`);
}
if (process.argv.includes('--browser')) browserChecks().catch(error=>{console.error(error);process.exitCode=1;});
