(function () {
  'use strict';

  var entries = window.MINECRAFT_TEXTURES || [], images = new Map(), localReady;
  var aliases = {
    grass_block: 'grass_block_top', dirt_path: 'dirt_path_top', podzol: 'podzol_top',
    mycelium: 'mycelium_top', magma_block: 'magma', melon: 'melon_side',
    pumpkin: 'pumpkin_side', crafting_table: 'crafting_table_top', furnace: 'furnace_front',
    hay_bale: 'hay_block_side', cactus: 'cactus_side', honey_block: 'honey_block_side'
  };

  function resolve(id, lookup) {
    var byId = lookup || vanilla.byId;
    if (!id) return null;
    id = String(id).replace(/^textures\//, '').replace(/\.png$/, '');
    if (byId[id]) return byId[id];
    var name = id.toLowerCase().replace(/[^a-z0-9]+/g, '_');
    return byId['block/' + (aliases[name] || name)] || byId['item/' + name] || null;
  }

  function localSources() {
    if (!localReady) localReady = new Promise(function (ok, fail) {
      var script = document.createElement('script');
      script.src = 'textures-local.js';
      script.onload = ok;
      script.onerror = function () { fail(new Error('Could not load the local Minecraft textures.')); };
      document.head.appendChild(script);
    });
    return localReady;
  }

  function load(e) {
    e = typeof e === 'string' ? resolve(e) : e;
    if (!e) return Promise.reject(new Error('Texture not found.'));
    var key = e.url || e.src;
    if (!images.has(key)) images.set(key, (!e.url && location.protocol === 'file:' ? localSources() : Promise.resolve()).then(function () {
      return new Promise(function (ok, fail) {
        var img = new Image();
        img.onload = function () { ok(img); };
        img.onerror = function () { fail(new Error('Could not load ' + e.src)); };
        var sourceId = e.src.replace(/^textures\//, '').replace(/\.png$/, '');
        img.src = e.url || (location.protocol === 'file:' ? window.MINECRAFT_TEXTURE_SOURCES[sourceId] : e.src);
      });
    }));
    return images.get(key);
  }

  async function bytes(e) {
    e = typeof e === 'string' ? resolve(e) : e;
    if (!e) throw new Error('Texture not found.');
    if (e.url || location.protocol !== 'file:') {
      var response = await fetch(e.url || e.src);
      if (!response.ok) throw new Error('Could not read ' + e.src);
      return new Uint8Array(await response.arrayBuffer());
    }
    await localSources();
    var encoded = window.MINECRAFT_TEXTURE_SOURCES[e.id], raw = atob(encoded.split(',')[1]);
    return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); });
  }

  function release(imported) {
    imported.forEach(function (e) { if (e.url) { images.delete(e.url); URL.revokeObjectURL(e.url); } });
  }

  function frame(e, time, width, height) {
    width = width || e.w; height = height || e.h;
    var a = e.animation;
    if (!a || width / height !== e.w / e.h) return {x: 0, y: 0, w: width, h: height, index: 0};
    var fw = a.width || (a.height ? e.w : Math.min(e.w, e.h));
    var fh = a.height || (a.width ? e.h : Math.min(e.w, e.h));
    var columns = Math.max(1, Math.floor(e.w / fw)), count = columns * Math.floor(e.h / fh);
    var sequence = a.frames && a.frames.length ? a.frames : Array.from({length: count}, function (_, i) { return i; });
    var total = sequence.reduce(function (sum, f) { return sum + ((typeof f === 'object' ? f.time : a.frametime) || a.frametime || 1); }, 0);
    var tick = Math.max(0, time || 0) / 50 % Math.max(1, total), index = 0;
    for (var i = 0; i < sequence.length; i++) {
      var f = sequence[i], duration = (typeof f === 'object' ? f.time : a.frametime) || a.frametime || 1;
      index = typeof f === 'object' ? f.index : f;
      if (tick < duration) break;
      tick -= duration;
    }
    index = Math.max(0, Math.min(count - 1, index));
    var result = {x: (index % columns) * fw * width / e.w, y: Math.floor(index / columns) * fh * height / e.h,
      w: fw * width / e.w, h: fh * height / e.h, index: index, step: i, mix: a.interpolate ? tick / duration : 0};
    if (a.interpolate) {
      var next = sequence[(i + 1) % sequence.length], nextIndex = typeof next === 'object' ? next.index : next;
      nextIndex = Math.max(0, Math.min(count - 1, nextIndex));
      result.next = {x: (nextIndex % columns) * fw * width / e.w, y: Math.floor(nextIndex / columns) * fh * height / e.h, w: result.w, h: result.h};
    }
    return result;
  }

  function draw(cv, e, source) {
    e = typeof e === 'string' ? resolve(e) : e;
    if (!e) return Promise.resolve();
    cv.width = cv.height = 96;
    cv.dataset.texture = e.id;
    cv.dataset.textureSource = e.url || e.src;
    function paint(img) {
      if (cv.dataset.texture !== e.id || cv.dataset.textureSource !== (e.url || e.src)) return;
      var f = frame(e, 0, img.width, img.height), ctx = cv.getContext('2d');
      var scale = Math.min(96 / f.w, 96 / f.h);
      ctx.clearRect(0, 0, 96, 96); ctx.imageSmoothingEnabled = false;
      ctx.drawImage(img, f.x, f.y, f.w, f.h, (96 - f.w * scale) / 2, (96 - f.h * scale) / 2, f.w * scale, f.h * scale);
    }
    if (source) { paint(source); return Promise.resolve(); }
    return load(e).then(paint).catch(function (err) { cv.title = err.message; });
  }

  function matches(e, query) {
    query = query.trim().toLowerCase();
    return !query || (e.n + ' ' + e.id + ' ' + e.src).toLowerCase().replace(/_/g, ' ').includes(query.replace(/_/g, ' '));
  }

  function within(e, folder) {
    return !folder || e.folder === folder || e.folder.indexOf(folder + '/') === 0;
  }

  function escape(s) {
    return String(s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; });
  }

  function options(catalog) {
    var entries = catalog.entries, roots = catalog.roots, folders = catalog.folders;
    return '<option value="">All textures (' + entries.length.toLocaleString() + ')</option>' + roots.map(function (f) {
      return '<option value="' + escape(f) + '">' + escape(f) + '/ (' + folders[f].toLocaleString() + ')</option>';
    }).join('');
  }

  function navigation(folder, catalog) {
    var folders = catalog.folders;
    var parts = folder ? folder.split('/') : [];
    var crumbs = '<div class="folder-crumbs"><button type="button" data-folder="">textures</button>';
    parts.forEach(function (part, i) {
      crumbs += '<span>/</span><button type="button" data-folder="' + escape(parts.slice(0, i + 1).join('/')) + '">' + escape(part) + '</button>';
    });
    crumbs += '<span>/</span></div>';
    var children = Object.keys(folders).filter(function (f) {
      return f !== folder && (f.lastIndexOf('/') < 0 ? '' : f.slice(0, f.lastIndexOf('/'))) === folder;
    }).sort();
    return crumbs + '<div class="folder-children">' + children.map(function (f) {
      return '<button type="button" class="folder-button" data-folder="' + escape(f) + '"><span>' + escape(f.split('/').pop()) + '/</span><small>' + folders[f].toLocaleString() + '</small></button>';
    }).join('') + '</div>';
  }

  function blockModel(e, catalog) {
    var byId = (catalog || vanilla).byId, prefix = e.namespace && e.namespace !== 'minecraft' ? e.namespace + ':block/' : 'block/';
    var name = (e.textureId || e.id).slice(6), root = name, special;
    var known = {
      grass_block: {top: 'grass_block_top', side: 'grass_block_side', bottom: 'dirt', overlay: 'grass_block_side_overlay', tint: '#91bd59'},
      dirt_path: {top: 'dirt_path_top', side: 'dirt_path_side', bottom: 'dirt', height: 15 / 16},
      podzol: {top: 'podzol_top', side: 'podzol_side', bottom: 'dirt'},
      mycelium: {top: 'mycelium_top', side: 'mycelium_side', bottom: 'dirt'},
      crafting_table: {top: 'crafting_table_top', side: 'crafting_table_side', front: 'crafting_table_front', bottom: 'oak_planks'},
      bookshelf: {top: 'oak_planks', side: 'bookshelf', bottom: 'oak_planks'},
      furnace: {top: 'furnace_top', side: 'furnace_side', front: name.endsWith('_on') ? 'furnace_front_on' : 'furnace_front'},
      blast_furnace: {top: 'blast_furnace_top', side: 'blast_furnace_side', front: name.endsWith('_on') ? 'blast_furnace_front_on' : 'blast_furnace_front'},
      smoker: {top: 'smoker_top', side: 'smoker_side', front: name.endsWith('_on') ? 'smoker_front_on' : 'smoker_front', bottom: 'smoker_bottom'},
      pumpkin: {top: 'pumpkin_top', side: 'pumpkin_side'},
      carved_pumpkin: {top: 'pumpkin_top', side: 'pumpkin_side', front: 'carved_pumpkin'},
      jack_o_lantern: {top: 'pumpkin_top', side: 'pumpkin_side', front: 'jack_o_lantern'},
      beehive: {top: 'beehive_end', side: 'beehive_side', front: name.includes('honey') ? 'beehive_front_honey' : 'beehive_front'},
      bee_nest: {top: 'bee_nest_top', side: 'bee_nest_side', front: name.includes('honey') ? 'bee_nest_front_honey' : 'bee_nest_front', bottom: 'bee_nest_bottom'},
      barrel: {top: name.endsWith('_open') ? 'barrel_top_open' : 'barrel_top', side: 'barrel_side', bottom: 'barrel_bottom'},
      enchanting_table: {top: 'enchanting_table_top', side: 'enchanting_table_side', bottom: 'enchanting_table_bottom', height: 12 / 16},
      cactus: {top: 'cactus_top', side: 'cactus_side', bottom: 'cactus_bottom', width: 14 / 16}
    };
    Object.keys(known).sort(function (a, b) { return b.length - a.length; }).some(function (k) {
      if (name === k || name.indexOf(k + '_') === 0) { root = k; special = known[k]; return true; }
      return false;
    });
    if (!special) {
      var stripped = name.replace(/_(top|bottom|side|front|back|end)$/, '');
      if (byId[prefix + stripped] || byId[prefix + stripped + '_side']) root = stripped;
      special = {};
    }
    function exists(n) { return n && byId[prefix + n] ? prefix + n : null; }
    var side = exists(special.side) || exists(root + '_side') || exists(root) || e.id;
    var top = exists(special.top) || exists(root + '_top') || exists(root + '_end') || side;
    var bottom = exists(special.bottom) || exists(root + '_bottom') || top;
    function material(id, tint, overlay) { return {id: id, tint: tint || null, overlay: overlay || null}; }
    var leafTint = /^(oak|jungle|acacia|dark_oak|mangrove)_leaves$/.test(name) ? '#77ab2f' : name === 'spruce_leaves' ? '#619961' : name === 'birch_leaves' ? '#80a755' : null;
    var waterTint = /^water_(still|flow)$/.test(name) ? '#3f76e4' : null;
    var tint = leafTint || waterTint;
    return {
      width: special.width || 1, height: special.height || 1,
      faces: {
        front: material(exists(special.front) || exists(root + '_front') || side, tint, exists(special.overlay)),
        back: material(exists(root + '_back') || side, tint, exists(special.overlay)),
        left: material(side, tint, exists(special.overlay)), right: material(side, tint, exists(special.overlay)),
        top: material(top, special.tint || tint), bottom: material(bottom, tint)
      }
    };
  }

  function catalog(source) {
    var byId = Object.create(null), folders = Object.create(null);
    source.forEach(function (e) {
      byId[e.id] = e; e.cat = e.cat || e.folder.split('/')[0];
      var parts = e.folder.split('/');
      for (var i = 1; i <= parts.length; i++) {
        var path = parts.slice(0, i).join('/'); folders[path] = (folders[path] || 0) + 1;
      }
    });
    var result = {entries: source, byId: byId, folders: folders,
      roots: Object.keys(folders).filter(function (f) { return f.indexOf('/') < 0; }).sort()};
    result.resolve = function (id) { return resolve(id, byId); };
    result.options = function () { return options(result); };
    result.navigation = function (folder) { return navigation(folder, result); };
    return result;
  }
  var vanilla = catalog(entries);
  window.MinecraftTextures = Object.assign(vanilla, {catalog: catalog, load: load, bytes: bytes, release: release,
    frame: frame, draw: draw, matches: matches, within: within, blockModel: blockModel});
})();
