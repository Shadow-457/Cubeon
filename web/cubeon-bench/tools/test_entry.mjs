import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const entry = fs.readFileSync(new URL('../entry.js', import.meta.url), 'utf8');
function visit(surface, url, values = {}, blocked = false) {
  const changes = [], storage = {...values}, current = new URL(url);
  vm.runInNewContext(entry, {
    document: {currentScript: {dataset: {benchSurface: surface}}, baseURI: new URL('./', url).href},
    location: {protocol: current.protocol, pathname: current.pathname, hash: current.hash, replace: target => changes.push(target)},
    localStorage: {
      getItem(key) { if (blocked) throw new Error('Storage blocked'); return storage[key] ?? null; },
      setItem(key, value) { if (blocked) throw new Error('Storage blocked'); storage[key] = value; },
    },
    URL,
  });
  return {changes, storage};
}

const base = 'https://www.ylet.online/cubeon-bench/';
assert.deepEqual(visit('landing', base).changes, []);
const opened = visit('workspace', base + 'workspace');
assert.equal(opened.storage['cb-bench-entered'], '1');
assert.deepEqual(visit('landing', base, opened.storage).changes, [base + 'workspace']);
const legacy = {'cb-data': JSON.stringify({projects: [{id: 'unchanged'}]})};
assert.deepEqual(visit('landing', base, legacy).changes, [base + 'workspace']);
assert.equal(visit('workspace', base + 'workspace', legacy).storage['cb-data'], legacy['cb-data']);
assert.deepEqual(visit('landing', base + 'landing', opened.storage).changes, []);
assert.deepEqual(visit('landing', base + '#questions', opened.storage).changes, []);
assert.deepEqual(visit('landing', base, {}, true).changes, []);
assert.deepEqual(visit('workspace', base + 'workspace', {}, true).changes, []);
assert.deepEqual(visit('landing', base, {...opened.storage, 'cb-data': 'corrupt'}).changes, [base + 'workspace']);
assert.deepEqual(visit('landing', 'file:///tmp/bench/index.html', opened.storage).changes, ['file:///tmp/bench/workspace.html']);

const listeners = {}, worker = {URL, self: {location: {href: base + 'sw.js', hostname: 'www.ylet.online'},
  addEventListener: (name, handler) => { listeners[name] = handler; }}};
vm.createContext(worker);
vm.runInContext(fs.readFileSync(new URL('../sw.js', import.meta.url), 'utf8'), worker);
for (const [path, expected] of [['', 'index.html'], ['index.html', 'index.html'],
  ['workspace', 'workspace.html'], ['workspace.html', 'workspace.html'],
  ['landing', 'landing.html'], ['landing.html', 'landing.html'], ['missing', null]]) {
  assert.equal(worker.navigationPage(new URL(path, base)), expected);
}
let intercepted = false;
listeners.fetch({request: {method: 'GET', mode: 'cors', url: 'https://www.ylet.online/_vercel/insights/script.js'},
  respondWith() { intercepted = true; }});
assert.equal(intercepted, false);
for (const asset of worker.SHELL) assert.ok(fs.existsSync(new URL('../' + asset, import.meta.url)), asset);
console.log('Bench first/returning visits, legacy saves, blocked storage, file mode and offline routes passed.');
