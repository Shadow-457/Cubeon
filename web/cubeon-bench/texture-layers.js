(function () {
  'use strict';
  var codec = window.TextureCodec, MAX_PIXELS = 1048576;
  function clone(image) { return new ImageData(new Uint8ClampedArray(image.data), image.width, image.height); }
  function valid(record) {
    if (!record || !Array.isArray(record.items) || !record.items.length || record.items.length > 12 || typeof record.active !== 'string') throw new Error('The saved paint layers are invalid.');
    var ids = new Set(), width, height;
    record.items.forEach(function (layer) {
      if (!layer || typeof layer.id !== 'string' || !/^[a-z0-9_-]{1,64}$/i.test(layer.id) || ids.has(layer.id) || typeof layer.name !== 'string' || layer.name.length > 60 || !Number.isFinite(layer.opacity) || layer.opacity < 0 || layer.opacity > 1 || typeof layer.visible !== 'boolean') throw new Error('A saved paint layer is invalid.');
      if (!layer.pixels || !Number.isInteger(layer.pixels.w) || !Number.isInteger(layer.pixels.h) || layer.pixels.w * layer.pixels.h > MAX_PIXELS || typeof layer.pixels.pixels !== 'string' || layer.pixels.pixels.length > MAX_PIXELS * 12) throw new Error('The saved layer dimensions or pixels are invalid.');
      ids.add(layer.id); var image = codec.decode(layer.pixels);
      if (image.width * image.height > MAX_PIXELS || width && (width !== image.width || height !== image.height)) throw new Error('Paint layers need matching dimensions and at most one million pixels each.');
      width = image.width; height = image.height;
    });
    if (!ids.has(record.active) || width * height * record.items.length > 4194304) throw new Error('The active layer or layer memory budget is invalid.');
    return record;
  }
  function dictionary(records) { var result = Object.create(null); Object.keys(records || {}).forEach(function (id) { if (id.includes('..') || id === '__proto__' || !/^[a-z0-9_:/.-]+$/i.test(id)) throw new Error('Invalid layered texture identifier.'); result[id] = valid(records[id]); }); return result; }
  function sync(doc) { if (doc.layers) { var layer = doc.layers.find(function (layer) { return layer.id === doc.activeLayer; }); if (layer) layer.image = doc.data; } }
  function checkSize(doc, width, height) { if (doc.layers && (width * height > MAX_PIXELS || width * height * doc.layers.length > 4194304)) throw new Error('This texture exceeds the layer memory budget. Flatten layers before resizing it.'); }
  function snapshot(doc) { if (!doc.layers) return null; sync(doc); return {active: doc.activeLayer, items: doc.layers.map(function (layer) { return Object.assign({}, layer, {image: clone(layer.image)}); })}; }
  function restore(doc, saved) { doc.layers = saved ? saved.items : null; doc.activeLayer = saved ? saved.active : null; if (saved) doc.data = doc.layers.find(function (layer) { return layer.id === saved.active; }).image; }
  function bytes(doc) { if (!doc.layers) return doc.data.data.byteLength; sync(doc); return doc.layers.reduce(function (sum, layer) { return sum + layer.image.data.byteLength; }, 0); }
  function attach(doc, record) {
    if (!record) { doc.layers = null; doc.activeLayer = null; return; }
    valid(record); doc.layers = record.items.map(function (layer) { return {id: layer.id, name: layer.name, visible: layer.visible, opacity: layer.opacity, image: codec.decode(layer.pixels)}; }); doc.activeLayer = record.active;
    doc.data = doc.layers.find(function (layer) { return layer.id === record.active; }).image; align(doc, doc.w, doc.h);
  }
  function ensure(doc) { if (doc.layers) return; if (doc.w * doc.h > MAX_PIXELS) throw new Error('Layered painting supports textures with up to one million pixels.'); doc.layers = [{id: 'base', name: 'Base', visible: true, opacity: 1, image: doc.data}]; doc.activeLayer = 'base'; }
  function serialize(doc) { if (!doc.layers) return null; sync(doc); return {active: doc.activeLayer, items: doc.layers.map(function (layer) { return {id: layer.id, name: layer.name, visible: layer.visible, opacity: layer.opacity, pixels: codec.encode(layer.image)}; })}; }
  function select(doc, id) { sync(doc); var layer = doc.layers && doc.layers.find(function (layer) { return layer.id === id; }); if (!layer) throw new Error('This paint layer is missing.'); doc.activeLayer = id; doc.data = layer.image; }
  function add(doc, duplicate) {
    ensure(doc); sync(doc); if (doc.layers.length >= 12 || (doc.layers.length + 1) * doc.w * doc.h > 4194304) throw new Error('This texture has reached the layer memory limit. Flatten or remove a layer before adding another.');
    var id = 'layer_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7), current = doc.layers.find(function (layer) { return layer.id === doc.activeLayer; });
    var layer = {id: id, name: duplicate ? (current.name.slice(0, 55) + ' copy') : 'Layer ' + (doc.layers.length + 1), visible: true, opacity: 1, image: duplicate ? clone(doc.data) : new ImageData(doc.w, doc.h)};
    doc.layers.splice(doc.layers.indexOf(current) + 1, 0, layer); doc.activeLayer = id; doc.data = layer.image;
  }
  function remove(doc, id) { if (!doc.layers || doc.layers.length === 1) throw new Error('Keep at least one layer, or flatten the texture.'); sync(doc); var index = doc.layers.findIndex(function (layer) { return layer.id === id; }); if (index < 0) throw new Error('This layer is missing.'); doc.layers.splice(index, 1); if (doc.activeLayer === id) select(doc, doc.layers[Math.max(0, index - 1)].id); }
  function move(doc, direction) { sync(doc); var from = doc.layers.findIndex(function (layer) { return layer.id === doc.activeLayer; }), to = Math.max(0, Math.min(doc.layers.length - 1, from + direction)); if (from !== to) doc.layers.splice(to, 0, doc.layers.splice(from, 1)[0]); }
  function compose(doc) {
    if (!doc.layers) return doc.data; sync(doc); var result = new ImageData(doc.data.width, doc.data.height), pixels = result.data;
    doc.layers.forEach(function (layer) {
      if (!layer.visible || !layer.opacity) return; var source = layer.image.data;
      for (var i = 0; i < pixels.length; i += 4) {
        var alpha = source[i + 3] / 255 * layer.opacity; if (!alpha) continue;
        var oldAlpha = pixels[i + 3] / 255, nextAlpha = alpha + oldAlpha * (1 - alpha);
        for (var channel = 0; channel < 3; channel++) pixels[i + channel] = (source[i + channel] * alpha + pixels[i + channel] * oldAlpha * (1 - alpha)) / nextAlpha;
        pixels[i + 3] = nextAlpha * 255;
      }
    }); return result;
  }
  function flatten(doc) { var image = compose(doc); doc.layers = null; doc.activeLayer = null; doc.data = image; }
  function align(doc, width, height) {
    if (!doc.layers) return;
    checkSize(doc, width, height);
    sync(doc); doc.layers.forEach(function (layer) {
      if (layer.image.width === width && layer.image.height === height) return;
      var old = layer.image, image = new ImageData(width, height);
      for (var y = 0; y < height; y++) for (var x = 0; x < width; x++) { var i = (Math.floor(y / height * old.height) * old.width + Math.floor(x / width * old.width)) * 4; image.data.set(old.data.subarray(i, i + 4), (y * width + x) * 4); }
      layer.image = image;
    }); doc.data = doc.layers.find(function (layer) { return layer.id === doc.activeLayer; }).image;
  }
  function mapInactive(doc, operation) { if (!doc.layers) return; sync(doc); doc.layers.forEach(function (layer) { if (layer.id !== doc.activeLayer) { var result = operation(Object.assign({}, doc, {data: layer.image, w: layer.image.width, h: layer.image.height, layers: null})); if (result && result.data) layer.image = result.data; } }); }
  function bind(read, change, selectLayer) {
    var root = document.getElementById('layerList'); if (!root) return;
    root.onclick = function (event) { var select = event.target.closest('[data-layer-select]'), visible = event.target.closest('[data-layer-visible]'), removeButton = event.target.closest('[data-layer-remove]'); if (select) selectLayer(select.dataset.layerSelect); if (visible) change(function (doc) { var layer = doc.layers.find(function (layer) { return layer.id === visible.dataset.layerVisible; }); layer.visible = !layer.visible; }); if (removeButton) change(function (doc) { remove(doc, removeButton.dataset.layerRemove); }); };
    root.onchange = function (event) { var input = event.target.closest('[data-layer-opacity]'); if (input) change(function (doc) { var layer = doc.layers.find(function (layer) { return layer.id === input.dataset.layerOpacity; }); layer.opacity = Math.max(0, Math.min(100, Number(input.value))) / 100; }); };
    document.getElementById('layerAdd').onclick = function () { change(function (doc) { add(doc, false); }); }; document.getElementById('layerDuplicate').onclick = function () { change(function (doc) { add(doc, true); }); };
    document.getElementById('layerUp').onclick = function () { change(function (doc) { ensure(doc); move(doc, 1); }); }; document.getElementById('layerDown').onclick = function () { change(function (doc) { ensure(doc); move(doc, -1); }); };
    document.getElementById('layerFlatten').onclick = function () { change(flatten); };
    document.getElementById('layerRename').onclick = async function () { var doc = read(); if (!doc) return; var active = doc.activeLayer, layer = doc.layers && doc.layers.find(function (layer) { return layer.id === active; }); var name = await window.AppDialog.open({title: 'Rename paint layer', accept: 'Rename', html: '<label class="tool-field"><span>Layer name</span><input id="layerName" maxlength="60" value="' + window.CB.esc(layer ? layer.name : 'Base') + '"></label>', read: function (root) { return root.querySelector('input').value.trim().slice(0, 60); }}); if (name && read() === doc && doc.activeLayer === active) change(function () { ensure(doc); doc.layers.find(function (layer) { return layer.id === doc.activeLayer; }).name = name; }); };
  }
  function render(doc) {
    var root = document.getElementById('layerList'); if (!root) return;
    if (!doc) { root.innerHTML = ''; return; }
    var layers = doc.layers || [{id: 'base', name: 'Base', visible: true, opacity: 1}], active = doc.activeLayer || 'base';
    root.innerHTML = layers.slice().reverse().map(function (layer) { return '<div class="tool-layer" aria-current="' + (layer.id === active) + '"><button type="button" data-layer-visible="' + layer.id + '" aria-label="' + (layer.visible ? 'Hide' : 'Show') + ' layer"' + (!doc.layers ? ' disabled' : '') + '>' + (layer.visible ? '●' : '○') + '</button><button type="button" data-layer-select="' + layer.id + '" translate="no"' + (!doc.layers ? ' disabled' : '') + '>' + window.CB.esc(layer.name) + '</button><input type="number" data-layer-opacity="' + layer.id + '" value="' + Math.round(layer.opacity * 100) + '" min="0" max="100" aria-label="Layer opacity"' + (!doc.layers ? ' disabled' : '') + '><button type="button" data-layer-remove="' + layer.id + '" aria-label="Remove layer"' + (layers.length < 2 ? ' disabled' : '') + '>×</button></div>'; }).join('');
  }
  window.TextureLayers = {valid: valid, dictionary: dictionary, attach: attach, serialize: serialize, ensure: ensure, select: select, add: add, remove: remove, move: move, compose: compose, flatten: flatten, align: align, mapInactive: mapInactive, checkSize: checkSize, snapshot: snapshot, restore: restore, bytes: bytes, bind: bind, render: render};
})();
