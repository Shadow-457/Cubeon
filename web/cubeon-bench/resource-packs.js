(function () {
  'use strict';
  var MT = window.MinecraftTextures, codec = window.TextureCodec;
  var versions = [
    {id: '26.1', label: '26.1 – 26.1.2', format: 84},
    {id: '1.21.11', label: '1.21.11', format: 75},
    {id: '1.21.9', label: '1.21.9 – 1.21.10', format: 69},
    {id: '1.21.7', label: '1.21.7 – 1.21.8', format: 64},
    {id: '1.21.6', label: '1.21.6', format: 63},
    {id: '1.21.5', label: '1.21.5', format: 55},
    {id: '1.21.4', label: '1.21.4', format: 46},
    {id: '1.21.3', label: '1.21.2 – 1.21.3', format: 42},
    {id: '1.21.1', label: '1.21 – 1.21.1', format: 34},
    {id: '1.20.6', label: '1.20.5 – 1.20.6', format: 32}
  ];
  var busy = false, taskTimer = 0;
  function clone(value) { return structuredClone(value); }
  function json(bytes, path) {
    try { return JSON.parse(new TextDecoder().decode(bytes)); }
    catch (_) { throw new Error(path + ' contains invalid JSON.'); }
  }
  function encode(value) { return new TextEncoder().encode(JSON.stringify(value, null, 2) + '\n'); }
  function plainText(value) {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(plainText).join('');
    if (!value || typeof value !== 'object') return '';
    return (value.text || value.translate || '') + (value.extra ? plainText(value.extra) : '');
  }
  function dataURL(bytes, type) {
    var chunks = [];
    for (var i = 0; i < bytes.length; i += 32768) chunks.push(String.fromCharCode.apply(null, bytes.subarray(i, i + 32768)));
    return 'data:' + type + ';base64,' + btoa(chunks.join(''));
  }
  function fromDataURL(url) {
    var raw = atob(url.split(',')[1]);
    return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); });
  }
  function pngSize(bytes, path) {
    var signature = [137, 80, 78, 71, 13, 10, 26, 10];
    if (bytes.length < 24 || !signature.every(function (v, i) { return bytes[i] === v; })) throw new Error(path + ' is not a PNG image.');
    var view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), w = view.getUint32(16), h = view.getUint32(20);
    if (!w || !h || w * h > 67108864) throw new Error(path + ' exceeds this browser’s texture size limit.');
    return {w: w, h: h};
  }
  function unzip(bytes) {
    return window.BenchArchive.read(bytes);
  }
  function zip(files) {
    var input = Object.create(null);
    Object.keys(files).sort().forEach(function (path) {
      input[path] = [files[path], {level: /\.(png|jpg|jpeg|ogg|mp3|zip)$/i.test(path) ? 0 : 6}];
    });
    return new Promise(function (resolve, reject) {
      window.fflate.zip(input, {level: 6}, function (error, bytes) { error ? reject(error) : resolve(bytes); });
    });
  }
  async function inspectZip(input, report) {
    report = report || function () {};
    report(.05, 'Reading resource pack…');
    if (input.size > 268435456) throw new Error('Choose a ZIP smaller than 256 MB.');
    var bytes = input instanceof Uint8Array ? input : new Uint8Array(await input.arrayBuffer());
    report(.18, 'Opening ZIP…');
    var archive = await unzip(bytes), paths = Object.keys(archive), normalized = Object.create(null);
    paths.forEach(function (original) {
      var path = original.replace(/\\/g, '/');
      if (path.endsWith('/') || path.startsWith('__MACOSX/')) return;
      if (path.startsWith('/') || /^[A-Za-z]:/.test(path) || path.split('/').some(function (p) { return p === '..' || p === '.'; })) {
        throw new Error('The ZIP contains an invalid path: ' + path);
      }
      if (normalized[path]) throw new Error('The ZIP contains duplicate files: ' + path);
      normalized[path] = archive[original];
    });
    var roots = Object.keys(normalized).filter(function (path) { return path === 'pack.mcmeta' || path.endsWith('/pack.mcmeta'); });
    var root = roots.includes('pack.mcmeta') ? 'pack.mcmeta' : roots.length === 1 ? roots[0] : null;
    if (!root) throw new Error(roots.length ? 'This ZIP contains multiple packs. Import one resource pack at a time.' : 'This ZIP needs a pack.mcmeta file. Choose a Minecraft Java resource pack.');
    var prefix = root.slice(0, -'pack.mcmeta'.length), files = Object.create(null);
    Object.keys(normalized).forEach(function (path) { if (path.startsWith(prefix)) files[path.slice(prefix.length)] = normalized[path]; });
    var metadata = json(files['pack.mcmeta'], 'pack.mcmeta'), pack = metadata && metadata.pack;
    if (!pack || typeof pack !== 'object' || pack.description == null || (!Number.isFinite(pack.pack_format) && pack.min_format == null)) {
      throw new Error('pack.mcmeta needs a pack description and Minecraft compatibility information.');
    }
    if (pack.min_format != null && pack.max_format == null) throw new Error('pack.mcmeta needs both min_format and max_format.');
    report(.3, 'Checking textures and pack details…');
    var textures = [], names = Object.keys(files).sort();
    for (var i = 0; i < names.length; i++) {
      var path = names[i], match = /^assets\/([a-z0-9_.-]+)\/textures\/([a-z0-9_./-]+)\.png$/.exec(path);
      if (match) {
        var namespace = match[1], textureId = match[2], split = textureId.lastIndexOf('/');
        var folder = split < 0 ? '' : textureId.slice(0, split), dimensions = pngSize(files[path], path);
        var entry = {id: namespace === 'minecraft' ? textureId : namespace + ':' + textureId, textureId: textureId,
          namespace: namespace, path: path, src: path, n: textureId.slice(split + 1).replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); }),
          cat: textureId.split('/')[0], folder: namespace === 'minecraft' ? folder : 'assets/' + namespace + '/textures/' + folder,
          w: dimensions.w, h: dimensions.h};
        if (files[path + '.mcmeta']) {
          entry.mcmeta = json(files[path + '.mcmeta'], path + '.mcmeta');
          if (entry.mcmeta.animation) entry.animation = entry.mcmeta.animation;
        }
        textures.push(entry);
      }
      if (i % 150 === 0) { report(.3 + .42 * i / Math.max(1, names.length), 'Checking ' + textures.length.toLocaleString() + ' textures…'); await new Promise(function (ok) { setTimeout(ok, 0); }); }
    }
    var details = files['.cubeon/project.json'] ? json(files['.cubeon/project.json'], '.cubeon/project.json') : {};
    var icon = '';
    if (files['pack.png']) { pngSize(files['pack.png'], 'pack.png'); if (files['pack.png'].length <= 2097152) icon = dataURL(files['pack.png'], 'image/png'); }
    return {files: files, textures: textures, metadata: metadata, description: plainText(pack.description), details: details, icon: icon};
  }
  function metadata(project) {
    var result = clone(project.packMeta || {}), pack = result.pack || {}, selected = versions.find(function (v) { return v.id === project.minecraftVersion; });
    if (project.minecraftVersion !== 'imported' || !result.pack) {
      selected = selected || versions[0];
      delete pack.pack_format; delete pack.supported_formats; delete pack.min_format; delete pack.max_format;
      if (selected.format >= 65) { pack.min_format = [selected.format, 0]; pack.max_format = [selected.format, 0]; }
      else pack.pack_format = selected.format;
    }
    if (!project.packMeta || project.description !== project.originalDescription) pack.description = project.description || project.name;
    result.pack = pack;
    return result;
  }
  function pathFor(entry) { return entry.path || 'assets/minecraft/' + entry.src; }
  function textureMetadata(entry, width, height) {
    if (!entry.mcmeta) return null;
    var result = clone(entry.mcmeta), scale = width / entry.w;
    if (result.animation && scale === height / entry.h) {
      ['width', 'height'].forEach(function (key) { if (result.animation[key]) result.animation[key] = Math.round(result.animation[key] * scale); });
    }
    return result;
  }
  async function openCatalog(project) {
    if (!project.assetId) return {catalog: MT, release: function () {}};
    var files = await window.LocalStore.getFiles(project.assetId), imported = [];
    try {
      (project.textures || []).forEach(function (entry) {
        if (!files[entry.path]) throw new Error('The imported texture is missing: ' + entry.path);
        imported.push(Object.assign({}, entry, {url: URL.createObjectURL(new Blob([files[entry.path]], {type: 'image/png'}))}));
      });
      var merged = new Map(MT.entries.map(function (entry) { return [entry.id, entry]; }));
      imported.forEach(function (entry) { merged.set(entry.id, entry); });
      return {catalog: MT.catalog(Array.from(merged.values())), release: function () { MT.release(imported); }};
    } catch (error) { MT.release(imported); throw error; }
  }
  async function buildZip(project, report) {
    report = report || function () {};
    var p = clone(project), originals = p.assetId ? await window.LocalStore.getFiles(p.assetId) : {};
    var files = Object.assign(Object.create(null), originals), entries = new Map(MT.entries.map(function (e) { return [e.id, e]; }));
    (p.textures || []).forEach(function (e) { entries.set(e.id, e); });
    var edits = p.edits || {}, ids = Array.from(new Set(Object.keys(edits).concat(Object.keys(p.animations || {}))));
    if (!p.assetId && !ids.length) {
      var first = MT.resolve(p.texture || p.block || 'block/grass_block_top');
      if (first) ids.push(first.id);
    }
    for (var i = 0; i < ids.length; i++) {
      var id = ids[i], entry = entries.get(id) || MT.resolve(id);
      if (!entry) throw new Error('Cannot export an unknown texture: ' + id);
      var path = pathFor(entry), image;
      if (edits[id]) {
        image = codec.decode(edits[id], p);
        files[path] = new Uint8Array(await (await codec.png(image)).arrayBuffer());
      } else if ((p.size || 16) !== 16) {
        var source = await MT.load(entry), scale = p.size / 16, cv = document.createElement('canvas');
        cv.width = Math.round(source.width * scale); cv.height = Math.round(source.height * scale);
        var ctx = cv.getContext('2d'); ctx.imageSmoothingEnabled = false; ctx.drawImage(source, 0, 0, cv.width, cv.height);
        image = ctx.getImageData(0, 0, cv.width, cv.height);
        files[path] = new Uint8Array(await (await codec.png(image)).arrayBuffer());
      } else files[path] = await MT.bytes(entry);
      var override = window.TextureAnimation.hasOverride(p, id);
      var mcmeta = override ? window.TextureAnimation.effectiveEntry(entry, p.animations[id], image ? image.width : entry.w, image ? image.height : entry.h).mcmeta : textureMetadata(entry, image ? image.width : entry.w, image ? image.height : entry.h);
      if (override) {
        if (mcmeta && Object.keys(mcmeta).length) files[path + '.mcmeta'] = encode(mcmeta);
        else delete files[path + '.mcmeta'];
      } else if (mcmeta && (!files[path + '.mcmeta'] || image && (image.width !== entry.w || image.height !== entry.h))) files[path + '.mcmeta'] = encode(mcmeta);
      report(.1 + .63 * (i + 1) / Math.max(1, ids.length), 'Preparing textures ' + (i + 1) + ' / ' + ids.length + '…');
      if (i % 12 === 0) await new Promise(function (ok) { setTimeout(ok, 0); });
    }
    files['pack.mcmeta'] = encode(metadata(p));
    if (p.icon) files['pack.png'] = fromDataURL(p.icon);
    else if (p.iconRemoved) delete files['pack.png'];
    files['.cubeon/project.json'] = encode({schema: 1, name: p.name, author: p.author || '', packVersion: p.packVersion || '1.0.0',
      minecraftVersion: p.minecraftVersion || '26.1', palette: p.pal, texture: p.texture || '', edited: p.edited});
    report(.82, 'Building resource pack ZIP…');
    return new Blob([await zip(files)], {type: 'application/zip'});
  }
  function task(progress, message, state) {
    var host = document.getElementById('packTask'); if (!host) return;
    clearTimeout(taskTimer); host.hidden = false; host.dataset.state = state || 'working';
    document.getElementById('packTaskLabel').textContent = message;
    document.getElementById('packTaskProgress').value = progress;
    document.getElementById('packTaskClose').hidden = !state;
    if (state === 'done') taskTimer = setTimeout(function () { host.hidden = true; }, 2200);
  }
  function download(blob, filename) {
    var url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
  }
  function filename(name, extension) { return (name.replace(/[\\/:*?"<>|\x00-\x1f]/g, '').trim() || 'Minecraft pack') + extension; }
  async function importFile(file) {
    if (!file || busy) return null;
    busy = true;
    try {
      await window.CB.ready;
      if (window.LocalStore.mode() !== 'indexedDB') throw new Error('This browser cannot save imported packs here. Open the app through a local server to enable project storage.');
      var pack = await inspectZip(file, task), now = Date.now(), id = 'p' + now.toString(36) + Math.random().toString(36).slice(2, 8);
      var extra = pack.details || {}, pal = window.CB.PL[extra.palette] ? extra.palette : window.CB.D.set.pal;
      var p = {id: id, assetId: id, name: String(extra.name || file.name.replace(/\.zip$/i, '') || 'Imported pack').slice(0, 40),
        type: 'pack', size: 16, pal: pal, description: pack.description, originalDescription: pack.description,
        author: String(extra.author || '').slice(0, 80), packVersion: String(extra.packVersion || '1.0.0').slice(0, 30),
        minecraftVersion: 'imported', packMeta: pack.metadata, icon: pack.icon, hasIcon: !!pack.files['pack.png'], textures: pack.textures,
        texture: pack.textures.some(function (e) { return e.id === extra.texture; }) ? extra.texture : (pack.textures[0] || {}).id || 'block/grass_block_top',
        edits: {}, created: now, edited: now};
      task(.78, 'Saving imported files locally…');
      await window.LocalStore.putFiles(id, pack.files);
      window.CB.D.projects.unshift(p); window.CB.bump();
      var saved = window.CB.save(); await window.LocalStore.flush();
      if (!await saved) throw new Error('The pack could not be saved locally. Free some browser storage and export a ZIP backup.');
      window.CB.renderAll(); await window.Ed.open(p);
      task(1, 'Imported ' + pack.textures.length.toLocaleString() + ' textures · saved locally', 'done');
      window.CB.toast('Imported “' + p.name + '”.'); return p;
    } catch (error) {
      task(0, error.message, 'error'); window.CB.toast(error.message); throw error;
    } finally { busy = false; }
  }
  async function exportProject(project) {
    if (!project || busy) return;
    busy = true;
    var button = document.getElementById('edExport');
    if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
    try {
      if (window.Ed) window.Ed.prepareExport();
      var snapshot = clone(project);
      task(.03, 'Preparing your download…'); await window.LocalStore.flush();
      if (snapshot.type === 'skin') {
        var image = snapshot.edits && snapshot.edits.skin ? codec.decode(snapshot.edits.skin, snapshot) : null;
        if (!image) {
          var original = await MT.load('entity/player/wide/steve'), cv = document.createElement('canvas');
          cv.width = original.width; cv.height = original.height; cv.getContext('2d').drawImage(original, 0, 0);
          image = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height);
        }
        download(await codec.png(image), filename(snapshot.name, '.png'));
        task(1, 'Skin PNG ready', 'done');
      } else {
        download(await buildZip(snapshot, task), filename(snapshot.name, '.zip'));
        task(1, 'Minecraft resource pack ZIP ready', 'done');
      }
      window.CB.toast('Downloaded “' + snapshot.name + '”.');
    } catch (error) { task(0, error.message, 'error'); window.CB.toast(error.message); }
    finally { busy = false; if (button) { button.disabled = false; button.removeAttribute('aria-busy'); } }
  }
  window.ResourcePacks = {versions: versions, defaultVersion: '26.1', metadata: metadata, inspectZip: inspectZip,
    openCatalog: openCatalog, buildZip: buildZip, importFile: importFile, exportProject: exportProject};
})();
