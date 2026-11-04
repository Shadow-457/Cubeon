(function () {
  'use strict';
  var mode = 'opening', queued = null, waiters = [], timer = 0, writing = null, fileCache = new Map();
  var status = {state: 'opening', mode: mode};
  var database = new Promise(function (resolve) {
    try {
      var request = indexedDB.open('cubeon-bench-local', 1);
      request.onupgradeneeded = function () {
        var db = request.result;
        if (!db.objectStoreNames.contains('workspace')) db.createObjectStore('workspace');
        if (!db.objectStoreNames.contains('pack-files')) db.createObjectStore('pack-files');
      };
      request.onsuccess = function () {
        mode = 'indexedDB';
        request.result.onversionchange = function () { request.result.close(); };
        resolve(request.result);
      };
      request.onerror = request.onblocked = function () { mode = 'localStorage'; resolve(null); };
    } catch (_) { mode = 'localStorage'; resolve(null); }
  });

  function signal(state, error) {
    status = {state: state, mode: mode, error: error && error.message};
    window.dispatchEvent(new CustomEvent('cb-storage', {detail: status}));
  }
  function get(db, store, key) {
    return new Promise(function (resolve, reject) {
      var request = db.transaction(store, 'readonly').objectStore(store).get(key);
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error); };
    });
  }
  function put(db, store, key, value) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(store, 'readwrite');
      tx.objectStore(store).put(value, key);
      tx.oncomplete = function () { resolve(); };
      tx.onerror = tx.onabort = function () { reject(tx.error || new Error('Local storage could not be written.')); };
    });
  }
  function legacy() {
    try { return JSON.parse(localStorage.getItem('cb-data') || 'null'); } catch (_) { return null; }
  }
  async function loadState() {
    var db = await database;
    var persisted = db && await get(db, 'workspace', 'state');
    var state = persisted || legacy();
    if (!persisted && state && state.localDatabase) {
      throw new Error('The local project database is unavailable. Reopen this page in the browser where you saved your projects, or restore an exported ZIP backup.');
    }
    signal('saved');
    return state;
  }
  function bootstrap(state) {
    var small = Object.assign({}, state, {localDatabase: true, projects: state.projects.map(function (p) {
      var info = Object.assign({}, p);
      delete info.edits; delete info.packMeta; delete info.textures; delete info.originalDescription;
      return info;
    })});
    try { localStorage.setItem('cb-data', JSON.stringify(small)); } catch (_) {}
  }
  async function flush() {
    clearTimeout(timer); timer = 0;
    if (writing) { var previous = await writing; return queued ? flush() : previous; }
    if (!queued) return status.state !== 'error';
    var state = structuredClone(queued), batch = waiters;
    queued = null; waiters = [];
    writing = (async function () {
      try {
        var db = await database;
        if (db) { await put(db, 'workspace', 'state', state); bootstrap(state); }
        else localStorage.setItem('cb-data', JSON.stringify(state));
        signal(queued ? 'saving' : 'saved'); batch.forEach(function (w) { w.resolve(true); });
        return true;
      } catch (error) {
        signal('error', error); batch.forEach(function (w) { w.reject(error); });
        return false;
      }
    })();
    var success = await writing; writing = null;
    if (queued) return (await flush()) && success;
    return success;
  }
  function saveState(state) {
    queued = state; clearTimeout(timer); signal('saving'); timer = setTimeout(flush, 140);
    return new Promise(function (resolve, reject) { waiters.push({resolve: resolve, reject: reject}); });
  }
  async function putFiles(id, files) {
    var db = await database;
    if (!db) throw new Error('This browser cannot store large packs here. Open Cubeon Bench through a local server to enable local project storage.');
    await put(db, 'pack-files', id, files); fileCache.set(id, files);
    while (fileCache.size > 2) fileCache.delete(fileCache.keys().next().value);
  }
  async function getFiles(id) {
    if (!id) return {};
    if (fileCache.has(id)) return fileCache.get(id);
    var db = await database, files = db && await get(db, 'pack-files', id);
    if (!files) throw new Error('The imported pack files are missing from this browser. Import your ZIP backup to restore them.');
    fileCache.set(id, files);
    while (fileCache.size > 2) fileCache.delete(fileCache.keys().next().value);
    return files;
  }
  async function cleanFiles(projects) {
    var db = await database; if (!db) return;
    var keep = new Set(projects.map(function (p) { return p.assetId; }).filter(Boolean));
    return new Promise(function (resolve, reject) {
      var tx = db.transaction('pack-files', 'readwrite'), store = tx.objectStore('pack-files'), request = store.getAllKeys();
      request.onsuccess = function () { request.result.forEach(function (id) { if (!keep.has(id)) { store.delete(id); fileCache.delete(id); } }); };
      tx.oncomplete = resolve; tx.onerror = tx.onabort = function () { reject(tx.error); };
    });
  }
  window.addEventListener('pagehide', function () { flush(); });
  document.addEventListener('visibilitychange', function () { if (document.hidden) flush(); });
  window.LocalStore = {ready: database, loadState: loadState, saveState: saveState, flush: flush,
    putFiles: putFiles, getFiles: getFiles, cleanFiles: cleanFiles, mode: function () { return mode; },
    status: function () { return status; }};
})();
