'use strict';
importScripts('vendor/cubiomes.js');
var ready = CubeonSeedEngine({locateFile: function (file) { return new URL('vendor/' + file, self.location.href).href; }});
self.onmessage = async function (event) {
  try {
    var engine = await ready, options = event.data, seed = BigInt.asUintN(64, BigInt(options.seed));
    if (!engine._cb_init(options.version, Number(seed & 0xffffffffn), Number(seed >> 32n), options.dimension, options.large ? 1 : 0)) throw new Error('Unsupported seed generator version.');
    var pointer = engine._cb_map(options.x, options.z, options.span, options.resolution, options.y);
    if (!pointer) throw new Error('The map extent is outside the generator’s limits.');
    var ids = new Int32Array(engine.HEAP32.subarray(pointer >>> 2, (pointer >>> 2) + options.resolution * options.resolution));
    var palette = {}, names = {};
    new Set(ids).forEach(function (id) { palette[id] = engine._cb_biome_color(id); names[id] = engine.UTF8ToString(engine._cb_biome_name(id)); });
    var markers = [];
    if (options.structures) {
      var at = engine._cb_markers(options.x, options.z, options.span) >>> 2, count = engine._cb_count();
      for (var i = 0; i < count; i++) markers.push({type: engine.HEAP32[at + i * 3], x: engine.HEAP32[at + i * 3 + 1], z: engine.HEAP32[at + i * 3 + 2]});
    }
    self.postMessage({ids: ids, palette: palette, names: names, markers: markers, options: options}, [ids.buffer]);
  } catch (error) { self.postMessage({error: error.message}); }
};
