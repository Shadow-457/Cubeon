(function () {
  'use strict';
  var CB = window.CB, archive = window.BenchArchive, busy = false;
  function id() { return 'p' + crypto.randomUUID().replace(/-/g, ''); }
  function all(state) { return state.projects.concat(state.trash || []); }
  function encode(value) { return new TextEncoder().encode(JSON.stringify(value)); }
  function parse(bytes) { try { return JSON.parse(new TextDecoder().decode(bytes)); } catch (_) { throw new Error('The workspace backup contains invalid project data.'); } }
  function progress(value, text, state) {
    var host = document.getElementById('workspaceTask'); host.hidden = false; host.dataset.state = state || 'working';
    document.getElementById('workspaceTaskLabel').textContent = text;
    document.getElementById('workspaceTaskProgress').value = value;
    document.getElementById('workspaceTaskClose').hidden = !state;
  }
  async function buildBackup() {
    await CB.ready;
    if (window.Ed) window.Ed.prepareExport();
    // A backup can rescue unsaved data when browser storage is full.
    var state = structuredClone(CB.D), files = Object.create(null), assets = [];
    var identifiers = Array.from(new Set(all(state).map(function (p) { return p.assetId; }).filter(Boolean)));
    for (var i = 0; i < identifiers.length; i++) {
      var original = identifiers[i], stored = await LocalStore.getFiles(original), directory = 'packs/' + i + '/';
      assets.push({id: original, directory: directory, paths: Object.keys(stored)});
      Object.keys(stored).forEach(function (path) { files[directory + path] = stored[path]; });
      progress(.1 + .6 * (i + 1) / identifiers.length, 'Backing up imported files ' + (i + 1) + ' / ' + identifiers.length + '…');
    }
    files['cubeon-workspace.json'] = encode({app: 'cubeon-bench', schema: 1, exported: new Date().toISOString(), state: state, assets: assets});
    progress(.85, 'Building workspace backup…'); return archive.write(files);
  }
  async function exportBackup() {
    if (busy) return; busy = true;
    try {
      progress(.02, 'Preparing workspace backup…');
      archive.download(await buildBackup(), 'Cubeon Bench ' + new Date().toISOString().slice(0, 10) + '.cubeon.zip');
      CB.D.lastBackup = Date.now(); CB.save(); CB.renderAll(); progress(1, 'Workspace backup downloaded', 'done');
      CB.toast('All projects, textures, and imported files backed up.');
    } catch (error) { progress(0, error.message, 'error'); CB.toast(error.message); }
    finally { busy = false; }
  }
  function validateProject(p) {
    if (!p || typeof p !== 'object' || !/^p[a-z0-9.-]+$/i.test(p.id) || typeof p.name !== 'string' || !['skin', 'pack'].includes(p.type)) throw new Error('The backup contains an invalid project.');
    if (![16, 32, 64].includes(p.size)) throw new Error('The backup contains an invalid texture scale.');
    if (!Number.isFinite(p.created) || !Number.isFinite(p.edited)) throw new Error('The backup contains an invalid project date.');
    p.name = p.name.slice(0, 40);
    var edits = p.edits || {};
    if (typeof edits !== 'object' || Array.isArray(edits)) throw new Error('The backup contains invalid texture edits.');
    Object.keys(edits).forEach(function (key) {
      if (!/^[a-z0-9_./:-]+$/.test(key) || key.split('/').includes('..') || ['__proto__', 'constructor', 'prototype'].includes(key)) throw new Error('The backup contains an invalid texture path.');
      TextureCodec.decode(edits[key], p);
    });
    if(p.surfaces)p.surfaces=window.TextureSurface.dictionary(p.surfaces);
    if(p.layers){
      p.layers=window.TextureLayers.dictionary(p.layers);
      Object.keys(p.layers).forEach(function(key){var image=TextureCodec.decode(p.layers[key].items[0].pixels),edit=edits[key]&&TextureCodec.decode(edits[key],p);if(edit&&(edit.width!==image.width||edit.height!==image.height))throw new Error('The backup contains layers with mismatched texture dimensions.');});
    }
    if(p.targetEdition&&!['java','bedrock'].includes(p.targetEdition))throw new Error('The backup contains an invalid pack edition.');
    if(p.surfaceImported&&(!Array.isArray(p.surfaceImported)||!p.surfaceImported.every(window.TextureSurface.validId)))throw new Error('The backup contains invalid depth-map ownership.');
    if (p.textures && !Array.isArray(p.textures)) throw new Error('The backup contains an invalid texture catalog.');
    (p.textures || []).forEach(function (entry) {
      if (!entry || !/^[a-z0-9_./:-]+$/.test(entry.id) || !archive.safePath(entry.path) || !/^assets\/[a-z0-9_.-]+\/textures\/[a-z0-9_./-]+\.png$/.test(entry.path) || entry.src !== entry.path || typeof entry.n !== 'string' || typeof entry.folder !== 'string') throw new Error('The backup contains an invalid imported texture.');
      if (!Number.isInteger(entry.w) || !Number.isInteger(entry.h) || entry.w < 1 || entry.h < 1 || entry.w * entry.h > 67108864 || entry.url) throw new Error('The backup contains invalid texture dimensions.');
    });
    ['thumb', 'icon'].forEach(function (key) { if (p[key] && !/^data:image\/png;base64,[a-z0-9+/=]+$/i.test(p[key])) throw new Error('The backup contains an invalid image.'); });
    return p;
  }
  async function inspectBackup(file) {
    if (file.size > 268435456) throw new Error('Choose a backup smaller than 256 MB.');
    var files = await archive.read(file), bytes = files['cubeon-workspace.json'];
    if (!bytes || bytes.length > 134217728) throw new Error('Choose a Cubeon workspace backup (.cubeon.zip). Resource packs use Import .zip.');
    var backup = parse(bytes), state = backup.state, assets = Object.create(null);
    if (backup.app !== 'cubeon-bench' || backup.schema !== 1 || !state || !Array.isArray(state.projects) || !Array.isArray(backup.assets) || state.trash && !Array.isArray(state.trash)) throw new Error('This workspace backup format is not supported.');
    if (all(state).length > 2000) throw new Error('This backup has too many projects.');
    var seen = new Set();
    all(state).forEach(function (p) { validateProject(p); if (seen.has(p.id)) throw new Error('The backup contains duplicate projects.'); seen.add(p.id); });
    backup.assets.forEach(function (asset) {
      if (!asset || typeof asset.id !== 'string' || !/^packs\/[0-9]+\/$/.test(asset.directory) || !Array.isArray(asset.paths) || Object.prototype.hasOwnProperty.call(assets, asset.id)) throw new Error('The backup contains an invalid file catalog.');
      var stored = Object.create(null);
      asset.paths.forEach(function (path) {
        if (!archive.safePath(path) || !files[asset.directory + path] || Object.prototype.hasOwnProperty.call(stored, path)) throw new Error('The backup is missing imported files.');
        stored[path] = files[asset.directory + path];
      }); assets[asset.id] = stored;
    });
    all(state).forEach(function (p) {
      if (p.assetId && !assets[p.assetId]) throw new Error('The backup is missing imported pack files.');
      (p.textures || []).forEach(function (entry) { if (!p.assetId || !assets[p.assetId][entry.path]) throw new Error('The backup is missing an imported texture.'); });
    });
    return {state: state, assets: assets};
  }
  async function restoreBackup(backup, preferences) {
    if (window.Ed && document.getElementById('ed').classList.contains('show')) window.Ed.close();
    var next = structuredClone(CB.D), assets = Object.create(null), mapping = Object.create(null);
    Object.keys(backup.assets).forEach(function (old) { mapping[old] = id(); assets[mapping[old]] = backup.assets[old]; });
    function copy(p) { var result = structuredClone(p); result.id = id(); if (result.assetId) result.assetId = mapping[result.assetId]; return result; }
    next.projects = backup.state.projects.map(copy).concat(next.projects);
    next.trash = (backup.state.trash || []).map(copy).concat(next.trash || []);
    if (preferences) {
      var source = backup.state.profile || {}, settings = backup.state.set || {};
      next.profile = {name: String(source.name || 'Builder').slice(0, 18), color: /^#[a-f0-9]{6}$/i.test(source.color) ? source.color : '#A4D168', picture: /^data:image\/(png|jpeg|webp);base64,[a-z0-9+/=]+$/i.test(source.picture || '') ? source.picture : ''};
      ['remember', 'calm', 'grid', 'naturalColors'].forEach(function (key) { if (typeof settings[key] === 'boolean') next.set[key] = settings[key]; });
      if (['system', 'light', 'dark'].includes(settings.theme)) next.set.theme = settings.theme;
      if ([16, 32, 64].includes(settings.size)) next.set.size = settings.size;
      if (window.BenchI18n.normalize(settings.language)) next.set.language = window.BenchI18n.normalize(settings.language);
    }
    var activity = backup.state.textureActivity || {};next.textureActivity=next.textureActivity||{};
    Object.keys(activity).forEach(function (key) { if (/^\d{4}-\d{2}-\d{2}$/.test(key) && Array.isArray(activity[key])) {next.textureActivity[key]=Array.from(new Set((next.textureActivity[key]||[]).concat(activity[key].filter(function(item){return typeof item==='string'&&item.length<300}))));next.activity[key]=next.textureActivity[key].length;} });
    progress(.8, 'Saving restored projects and pack files…');
    await LocalStore.commitWorkspace(next, assets); CB.applyWorkspace(next); return backup.state.projects.length;
  }
  async function importBackup(file) {
    if (busy) return; busy = true;
    try {
      progress(.1, 'Checking workspace backup…'); var backup = await inspectBackup(file);
      progress(.6, 'Backup checked · ready to restore', 'done');
      var answer = await AppDialog.open({title: 'Restore workspace backup', accept: 'Restore projects', html: '<p>Restore ' + backup.state.projects.length + ' projects and ' + (backup.state.trash || []).length + ' items in Trash. Your current projects stay on your bench. Restored projects receive new IDs, so existing work is preserved.</p><label class="dialog-check"><input type="checkbox" id="restorePreferences"> Also restore the profile and appearance preferences</label>', read: function (root) { return {preferences: root.querySelector('input').checked}; }});
      if (!answer) return;
      var count = await restoreBackup(backup, answer.preferences); progress(1, count + ' projects restored', 'done'); CB.go('projects'); CB.toast('Backup restored. Your existing projects are preserved.');
    } catch (error) { progress(0, error.message, 'error'); CB.toast(error.message); }
    finally { busy = false; }
  }
  function renderTrash() {
    var trash = CB.D.trash || [], root = document.getElementById('trashList');
    if (!root) return;
    document.getElementById('trashCount').textContent = trash.length + (trash.length === 1 ? ' project in Trash' : ' projects in Trash');
    document.getElementById('emptyTrash').disabled = !trash.length;
    root.innerHTML = trash.length ? trash.map(function (p) { return '<div class="trash-row"><span><b>' + CB.esc(p.name) + '</b><small class="mu">' + (p.type === 'skin' ? 'Skin' : 'Texture pack') + '</small></span><button type="button" class="gb" data-restore="' + CB.esc(p.id) + '">Restore</button></div>'; }).join('') : '<p class="mu">Deleted projects appear here until you empty Trash.</p>';
    window.BenchI18n.text(document.getElementById('backupStatus'),CB.D.lastBackup?'Last backup: {text}':'Back up every project, texture edit, and imported file in one ZIP.',{text:new Date(CB.D.lastBackup).toLocaleString(window.BenchI18n.language())});
  }
  function removeProject(identifier) {
    var project = CB.find(identifier); if (!project) return;
    CB.D.projects = CB.D.projects.filter(function (p) { return p.id !== identifier; });
    project.deleted = Date.now(); (CB.D.trash || (CB.D.trash = [])).unshift(project);
    CB.save(); CB.renderAll(); CB.toast('Moved “' + project.name + '” to Trash. Restore it in Settings.');
  }
  async function emptyTrash() {
    if (!(CB.D.trash || []).length) return;
    if (!await AppDialog.open({title: 'Empty Trash?', html: '<p>Permanently delete ' + CB.D.trash.length + ' projects and their unused imported files. Download a workspace backup first if you need a copy.</p>', accept: 'Delete permanently', danger: true})) return;
    var old = CB.D.trash; CB.D.trash = [];
    if (!await CB.save()) { CB.D.trash = old; CB.renderAll(); return; }
    try { await LocalStore.cleanFiles(CB.D.projects); } catch (error) { CB.toast('Projects deleted; unused files could not be cleaned up: ' + error.message); }
    CB.renderAll();
  }
  async function importSkin(file) {
    try {
      var image = await window.Ed.readPNG(file);
      image = window.BenchToolsCore.normalizeSkin(image);
      var now = Date.now(), p = {id: id(), name: file.name.replace(/\.png$/i, '').slice(0, 40) || 'Imported skin', type: 'skin', size: 16, pal: CB.D.set.pal, edits: {skin: TextureCodec.encode(image)}, created: now, edited: now};
      var full=document.createElement('canvas');full.width=full.height=64;full.getContext('2d').putImageData(image,0,0);
      var face=document.createElement('canvas');face.width=face.height=16;face.getContext('2d').imageSmoothingEnabled=false;face.getContext('2d').drawImage(full,8,8,8,8,0,0,16,16);p.thumb=face.toDataURL();
      CB.D.projects.unshift(p); CB.bump(); await CB.save(); CB.renderAll(); await window.Ed.open(p); CB.toast('Skin imported.');
    } catch (error) { CB.toast(error.message); }
  }
  document.addEventListener('click', function (event) {
    if (event.target.closest('#backupWorkspace')) exportBackup();
    if (event.target.closest('#restoreWorkspace')) { var picker = document.getElementById('workspaceImport'); picker.value = ''; picker.click(); }
    if (event.target.closest('#emptyTrash')) emptyTrash();
    if (event.target.closest('#workspaceTaskClose')) document.getElementById('workspaceTask').hidden = true;
    var button = event.target.closest('[data-restore]');
    if (button) { var p = (CB.D.trash || []).find(function (project) { return project.id === button.dataset.restore; }); if (p) { delete p.deleted; CB.D.trash = CB.D.trash.filter(function (project) { return project !== p; }); CB.D.projects.unshift(p); CB.save(); CB.renderAll(); CB.toast('Restored “' + p.name + '”.'); } }
  });
  document.getElementById('workspaceImport').addEventListener('change', function () { if (this.files[0]) importBackup(this.files[0]); });
  document.addEventListener('cb-render', renderTrash); CB.ready.then(renderTrash, function () {});
  window.Workspace = {buildBackup: buildBackup, inspectBackup: inspectBackup, restoreBackup: restoreBackup, exportBackup: exportBackup, importBackup: importBackup, removeProject: removeProject, renderTrash: renderTrash, importSkin: importSkin};
})();
