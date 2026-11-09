(function () {
  'use strict';
  var utf8 = new TextDecoder(), encoder = new TextEncoder();
  var MAX = 134217728;
  function inflate(bytes, kind) {
    if (kind === 'raw') return bytes;
    var parts = [], length = 0, Type = kind === 'gzip' ? window.fflate.Gunzip : window.fflate.Unzlib;
    var stream = new Type(function (chunk) { length += chunk.length; if (length > MAX) throw new Error('The decompressed NBT exceeds 128 MB.'); parts.push(chunk); });
    for (var offset = 0; offset < bytes.length; offset += 16384) stream.push(bytes.subarray(offset, offset + 16384), offset + 16384 >= bytes.length);
    var result = new Uint8Array(length), at = 0;
    parts.forEach(function (part) { result.set(part, at); at += part.length; });
    return result;
  }
  function readNBT(input, options) {
    options = options || {};
    var original = input, compression = input[0] === 31 && input[1] === 139 ? 'gzip' : input[0] === 120 ? 'zlib' : 'raw';
    var bytes = inflate(input, compression), header = null, little = !!options.little;
    if (bytes.length >= 9 && bytes[8] === 10 && new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(4, true) === bytes.length - 8) {
      header = bytes.slice(0, 8); bytes = bytes.subarray(8); little = true;
    }
    if (bytes.length > MAX) throw new Error('NBT files are limited to 128 MB.');
    var view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), offset = 0, count = 0;
    function need(n) { if (n < 0 || offset + n > bytes.length) throw new Error('The NBT data is truncated or has an invalid length.'); }
    function number(type) {
      var sizes = {1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}, size = sizes[type]; need(size);
      var value = type === 1 ? view.getInt8(offset) : type === 2 ? view.getInt16(offset, little) : type === 3 ? view.getInt32(offset, little) : type === 4 ? view.getBigInt64(offset, little) : type === 5 ? view.getFloat32(offset, little) : view.getFloat64(offset, little);
      offset += size; return value;
    }
    function string() { need(2); var length = view.getUint16(offset, little); offset += 2; need(length); var raw = bytes.slice(offset, offset + length); offset += length; return {text: utf8.decode(raw), raw: raw}; }
    function length() { var n = number(3); if (n < 0 || n > 16777216) throw new Error('An NBT list or array is too large.'); return n; }
    function payload(type, depth) {
      if (++count > 2000000 || depth > 64) throw new Error('The NBT nesting or tag count exceeds this tool’s limit.');
      var node = {type: type};
      if (type >= 1 && type <= 6) node.value = number(type);
      else if (type === 7) { var n = length(); need(n); node.value = bytes.slice(offset, offset + n); offset += n; }
      else if (type === 8) { var text = string(); node.value = text.text; node.originalString = text.text; node.rawString = text.raw; }
      else if (type === 9) { need(1); node.listType = bytes[offset++]; var n = length(); if (node.listType > 12 || n && node.listType === 0) throw new Error('An NBT list has an invalid element type.'); node.value = []; for (var i = 0; i < n; i++) node.value.push(payload(node.listType, depth + 1)); }
      else if (type === 10) {
        node.value = Object.create(null);
        while (true) { need(1); var childType = bytes[offset++]; if (!childType) break; if (childType > 12) throw new Error('Unknown NBT tag type.'); var name = string(); if (Object.prototype.hasOwnProperty.call(node.value, name.text)) throw new Error('The NBT compound contains duplicate names.'); var child = payload(childType, depth + 1); child.name = name.text; child.rawName = name.raw; node.value[name.text] = child; }
      } else if (type === 11 || type === 12) { var n = length(); need(n * (type === 11 ? 4 : 8)); node.value = []; for (var i = 0; i < n; i++) node.value.push(number(type === 11 ? 3 : 4)); }
      else throw new Error('Unknown NBT tag type.');
      return node;
    }
    need(1); var type = bytes[offset++];
    if (type !== 10) throw new Error('Expected a named NBT compound. Bedrock LevelDB files are not standalone NBT.');
    var name = string(), root = payload(type, 0); root.name = name.text; root.rawName = name.raw;
    if (offset !== bytes.length) throw new Error('Unexpected data follows the NBT compound.');
    return {format: 'cubeon-nbt', root: root, compression: compression, littleEndian: little, header: header, original: original};
  }
  function writeNBT(document) {
    var little = !!document.littleEndian, parts = [], total = 0, count = 0;
    function add(part) { total += part.length; if (total > MAX) throw new Error('NBT output exceeds 128 MB.'); parts.push(part); }
    function num(type, value) {
      var sizes = {1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}, bytes = new Uint8Array(sizes[type]), view = new DataView(bytes.buffer);
      if (type === 1) view.setInt8(0, Number(value)); else if (type === 2) view.setInt16(0, Number(value), little); else if (type === 3) view.setInt32(0, Number(value), little); else if (type === 4) view.setBigInt64(0, BigInt(value), little); else if (type === 5) view.setFloat32(0, Number(value), little); else view.setFloat64(0, Number(value), little);
      add(bytes);
    }
    function str(value, raw) { var bytes = raw ? new Uint8Array(raw) : encoder.encode(value); if (bytes.length > 65535) throw new Error('An NBT string exceeds 65,535 bytes.'); var size = new Uint8Array(2); new DataView(size.buffer).setUint16(0, bytes.length, little); add(size); add(bytes); }
    function payload(node, depth) {
      if (!node || ++count > 2000000 || depth > 64) throw new Error('Invalid or excessively nested NBT.');
      var type = node.type, value = node.value;
      if (type >= 1 && type <= 6) num(type, value);
      else if (type === 7) { var array = Array.isArray(value) || value instanceof Uint8Array ? value : Object.values(value); num(3, array.length); add(new Uint8Array(array)); }
      else if (type === 8) str(String(value), value === node.originalString ? node.rawString : null);
      else if (type === 9) { add(new Uint8Array([node.listType])); num(3, value.length); value.forEach(function (child) { if (child.type !== node.listType) throw new Error('NBT list types must match.'); payload(child, depth + 1); }); }
      else if (type === 10) { Object.keys(value).forEach(function (name) { var child = value[name]; if (child.type < 1 || child.type > 12) throw new Error('Invalid NBT tag type.'); add(new Uint8Array([child.type])); str(name, child.name === name ? child.rawName : null); payload(child, depth + 1); }); add(new Uint8Array([0])); }
      else if (type === 11 || type === 12) { num(3, value.length); value.forEach(function (n) { num(type === 11 ? 3 : 4, n); }); }
      else throw new Error('Invalid NBT tag type.');
    }
    add(new Uint8Array([10])); str(document.root.name || '', document.root.rawName); payload(document.root, 0);
    var bytes = new Uint8Array(total), at = 0; parts.forEach(function (part) { bytes.set(part, at); at += part.length; });
    if (document.header) { var withHeader = new Uint8Array(bytes.length + 8); withHeader.set(new Uint8Array(Array.isArray(document.header) ? document.header : Object.values(document.header))); new DataView(withHeader.buffer).setUint32(4, bytes.length, true); withHeader.set(bytes, 8); bytes = withHeader; }
    return document.compression === 'gzip' ? window.fflate.gzipSync(bytes) : document.compression === 'zlib' ? window.fflate.zlibSync(bytes) : bytes;
  }
  function tag(node, name) { return node && node.type === 10 ? node.value[name] : null; }
  function value(node, name, fallback) { var child = tag(node, name); return child ? child.value : fallback; }
  function plain(node) {
    if (!node) return null;
    if (node.type === 10) { var result = Object.create(null); Object.keys(node.value).forEach(function (key) { result[key] = plain(node.value[key]); }); return result; }
    if (node.type === 9) return node.value.map(plain);
    return typeof node.value === 'bigint' ? node.value.toString() : node.value;
  }
  function regionChunks(bytes) {
    if (bytes.length < 8192) throw new Error('The region header is truncated.');
    var view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), chunks = [], occupied = new Set([0, 1]), errors = [];
    for (var i = 0; i < 1024; i++) {
      var descriptor = view.getUint32(i * 4), sector = descriptor >>> 8, count = descriptor & 255;
      if (!descriptor) continue;
      if (sector < 2 || !count || (sector + count) * 4096 > bytes.length) { errors.push({slot: i, message: 'Chunk sectors are outside the region file.'}); continue; }
      var offset = sector * 4096, length = view.getUint32(offset);
      if (length < 1 || length + 4 > count * 4096) { errors.push({slot: i, message: 'Chunk length exceeds its allocated sectors.'}); continue; }
      var overlap = false;
      for (var s = sector; s < sector + count; s++) { if (occupied.has(s)) overlap = true; occupied.add(s); }
      if (overlap) { errors.push({slot: i, message: 'Chunk sectors overlap another chunk.'}); continue; }
      chunks.push({slot: i, timestamp: view.getUint32(4096 + i * 4), raw: bytes.slice(offset, offset + count * 4096), compression: bytes[offset + 4], data: bytes.subarray(offset + 5, offset + 4 + length)});
    }
    return {chunks: chunks, errors: errors};
  }
  function buildRegion(chunks) {
    var sectors = 2 + chunks.reduce(function (sum, chunk) { return sum + chunk.raw.length / 4096; }, 0), bytes = new Uint8Array(sectors * 4096), view = new DataView(bytes.buffer), at = 2;
    chunks.forEach(function (chunk) { var count = chunk.raw.length / 4096; if (!Number.isInteger(count) || count > 255) throw new Error('Invalid region sector count.'); view.setUint32(chunk.slot * 4, at * 256 + count); view.setUint32(4096 + chunk.slot * 4, chunk.timestamp); bytes.set(chunk.raw, at * 4096); at += count; });
    return bytes;
  }
  function regionPath(path) { var match = /(^|\/)(region|entities|poi)\/r\.(-?\d+)\.(-?\d+)\.mca$/.exec(path); return match && {kind: match[2], x: Number(match[3]), z: Number(match[4]), prefix: path.slice(0, match.index + match[1].length)}; }
  function inventory(node) { return (value(node, 'Inventory', null) || value(node, 'Items', null) || value(node, 'inventory', [])).map(function (item) { return {id: value(item, 'id', 'unknown'), count: value(item, 'count', value(item, 'Count', 1)), slot: value(item, 'Slot', null)}; }); }
  async function scanWorld(source, progress) {
    progress = progress || function () {};
    var files = window.BenchToolsCore.rootFiles(source), report = {name: 'Minecraft world', edition: 'java', seed: null, spawn: null, markers: [], chunks: 0, regions: 0, issues: [], stats: {}, metadata: null};
    if (!files['level.dat']) throw new Error('Choose a world ZIP or .mcworld containing level.dat.');
    try {
      var level = readNBT(files['level.dat']); report.edition = level.littleEndian ? 'bedrock' : 'java';
      var data = tag(level.root, 'Data') || level.root;
      report.name = value(data, 'LevelName', 'Minecraft world');
      var worldgen = tag(data, 'WorldGenSettings');
      var seed = worldgen ? value(worldgen, 'seed', null) : value(data, 'RandomSeed', null);
      if (seed != null) report.seed = String(seed);
      report.spawn = [value(data, 'SpawnX', 0), value(data, 'SpawnY', 64), value(data, 'SpawnZ', 0)];
      report.metadata = plain(data);
      var player = tag(data, 'Player'); if (player) addMarker(player, 'Local player', 'level.dat', 'player');
    } catch (error) { report.issues.push({path: 'level.dat', message: error.message}); }
    function addMarker(node, fallback, path, type) {
      if (report.markers.length >= 15000) return;
      var pos = value(node, 'Pos', null), position = pos ? pos.map(function (n) { return Number(n.value); }) : [value(node, 'x', null), value(node, 'y', null), value(node, 'z', null)];
      if (!position || position.length !== 3 || position.some(function (n) { return !Number.isFinite(n); })) return;
      var id = value(node, 'id', fallback), custom = value(node, 'CustomName', '');
      try { var parsed = custom && JSON.parse(custom); if (parsed) custom = typeof parsed === 'string' ? parsed : parsed.text || custom; } catch (_) {}
      var items = inventory(node), item = tag(node, 'Item'); if (item) items.push({id: value(item, 'id', 'unknown'), count: value(item, 'count', value(item, 'Count', 1))});
      report.markers.push({name: custom || id, id: id, type: type || 'entity', pos: position, dimension: path.includes('/DIM-1/') || path.startsWith('DIM-1/') ? 'nether' : path.includes('/DIM1/') || path.startsWith('DIM1/') ? 'end' : String(value(node, 'Dimension', 'overworld')), owner: String(value(node, 'Owner', value(node, 'OwnerUUID', ''))), items: items, path: path});
    }
    var paths = Object.keys(files).filter(function (path) { return regionPath(path) || /(^|\/)(playerdata|players\/data)\/[^/]+\.dat$/.test(path) || /(^|\/)stats\/[^/]+\.json$/.test(path); });
    for (var index = 0; index < paths.length; index++) {
      var path = paths[index], region = regionPath(path);
      try {
        if (region) {
          var decoded = regionChunks(files[path]); report.regions++;
          decoded.errors.forEach(function (error) { report.issues.push({path: path, slot: error.slot, message: error.message}); });
          for (var j = 0; j < decoded.chunks.length; j++) {
            var chunk = decoded.chunks[j], compression = chunk.compression & 127;
            if (region.kind === 'region') report.chunks++;
            if (region.kind === 'poi') continue;
            try {
              var bytes = chunk.data;
              if (chunk.compression & 128) { var external = path.slice(0, path.lastIndexOf('/') + 1) + 'c.' + (region.x * 32 + chunk.slot % 32) + '.' + (region.z * 32 + Math.floor(chunk.slot / 32)) + '.mcc'; if (!files[external]) throw new Error('An external chunk file is missing.'); bytes = files[external]; }
              if (![1, 2, 3].includes(compression)) throw new Error('This chunk compression is not supported; the chunk is preserved.');
              var nbt = readNBT(inflate(bytes, compression === 1 ? 'gzip' : compression === 2 ? 'zlib' : 'raw')), node = tag(nbt.root, 'Level') || nbt.root;
              ['Entities', 'entities', 'block_entities', 'TileEntities'].forEach(function (key) { var list = tag(node, key); if (list && list.type === 9) list.value.forEach(function (entity) { addMarker(entity, 'Block entity', path, key === 'block_entities' || key === 'TileEntities' ? 'container' : 'entity'); }); });
            } catch (error) { report.issues.push({path: path, slot: chunk.slot, message: error.message}); }
            if (j % 32 === 0) await new Promise(function (resolve) { setTimeout(resolve, 0); });
          }
        } else if (path.endsWith('.dat')) addMarker(readNBT(files[path]).root, path.split('/').pop().slice(0, -4), path, 'player');
        else {
          var stats = window.BenchToolsCore.parse(files[path], path).stats || {};
          Object.keys(stats).forEach(function (category) { report.stats[category] = report.stats[category] || {}; Object.keys(stats[category]).forEach(function (name) { report.stats[category][name] = (report.stats[category][name] || 0) + Number(stats[category][name]); }); });
        }
      } catch (error) { report.issues.push({path: path, message: error.message}); }
      progress((index + 1) / Math.max(1, paths.length), 'Reading world files ' + (index + 1) + ' / ' + paths.length);
      await new Promise(function (resolve) { setTimeout(resolve, 0); });
    }
    if (files['db/CURRENT']) { report.edition = 'bedrock'; report.issues.push({path: 'db/', message: 'Bedrock LevelDB entity and chunk records are preserved. This scanner reads Java regions, player NBT and Bedrock level metadata.'}); }
    return report;
  }
  function repairWorld(source) {
    var files = window.BenchToolsCore.rootFiles(source), repairs = [];
    if (!files['level.dat']) throw new Error('The world is missing level.dat.');
    try { readNBT(files['level.dat']); }
    catch (original) {
      if (!files['level.dat_old']) throw new Error('level.dat is invalid and no level.dat_old backup exists. ' + original.message);
      readNBT(files['level.dat_old']); files['.cubeon/original-level.dat'] = files['level.dat']; files['level.dat'] = files['level.dat_old'];
      repairs.push('Restored valid level.dat_old metadata. The damaged metadata is retained under .cubeon/original-level.dat.');
    }
    if (!repairs.length) repairs.push('The world metadata parses correctly. No speculative changes were made.');
    files['.cubeon/world-repair.json'] = window.BenchToolsCore.json({repairs: repairs, note: 'Original region, player and database files are retained. This is a new copy of the world.'});
    return {files: files, repairs: repairs};
  }
  function pruneWorld(source, bounds) {
    var files = window.BenchToolsCore.rootFiles(source), level = readNBT(files['level.dat']);
    if (level.littleEndian || files['db/CURRENT']) throw new Error('Chunk refresh supports Java .mca worlds. Bedrock LevelDB is preserved and cannot be pruned by this tool.');
    var b = [bounds.x1, bounds.z1, bounds.x2, bounds.z2].map(Number);
    if (b.some(function (n) { return !Number.isFinite(n) || Math.abs(n) > 30000000; }) || b[0] > b[2] || b[1] > b[3]) throw new Error('Enter an ordered rectangle inside Minecraft’s world bounds.');
    var minX = Math.floor(b[0] / 16), minZ = Math.floor(b[1] / 16), maxX = Math.floor(b[2] / 16), maxZ = Math.floor(b[3] / 16), kept = 0, removed = 0;
    Object.keys(files).forEach(function (path) {
      var region = regionPath(path); if (!region || region.prefix) return;
      var decoded = regionChunks(files[path]); if (decoded.errors.length) throw new Error(path + ' has invalid chunk sectors. Diagnose this world before refreshing it.');
      var chunks = decoded.chunks.filter(function (chunk) {
        var x = region.x * 32 + chunk.slot % 32, z = region.z * 32 + Math.floor(chunk.slot / 32), keep = x >= minX && x <= maxX && z >= minZ && z <= maxZ;
        if (region.kind === 'region') { if (keep) kept++; else removed++; } return keep;
      });
      if (chunks.length) files[path] = buildRegion(chunks); else delete files[path];
    });
    files['.cubeon/chunk-refresh.json'] = window.BenchToolsCore.json({preservedBlockRectangle: b, kept: kept, removed: removed, note: 'Only Overworld chunks outside the selected rectangle were removed in this copy, with matching entities and POI. Open the copy in your chosen newer Minecraft version to regenerate those areas. Builds outside the rectangle are absent from this copy. Nether and End are retained.'});
    return {files: files, kept: kept, removed: removed};
  }
  function rescueBedrock(source) {
    var files = window.BenchToolsCore.rootFiles(source), document = readNBT(files['level.dat']);
    if (!document.littleEndian || !document.header) throw new Error('Choose a Bedrock world with a supported little-endian level.dat.');
    var data = document.root, changed = [];
    ['hasBeenLoadedInCreative', 'hasCommandsEnabled', 'commandsEnabled', 'cheatsEnabled', 'AchievementsDisabled', 'GameType', 'ForceGameType'].forEach(function (key) { var child = tag(data, key); if (child && [1, 2, 3].includes(child.type) && child.value !== 0) { child.value = 0; changed.push(key); } });
    if (!changed.length) throw new Error('No recognized Creative or cheats flags need changing. This world may already be eligible; platform/account restrictions are separate.');
    files['.cubeon/original-level.dat'] = files['level.dat']; files['level.dat'] = writeNBT(document);
    files['.cubeon/achievement-recovery.json'] = window.BenchToolsCore.json({changed: changed, note: 'Recognized world flags were reset in this new copy. Minecraft version, platform and account rules still determine achievement eligibility.'});
    return {files: files, changed: changed};
  }
  function attachBedrockPack(world, pack) {
    var files = window.BenchToolsCore.rootFiles(world), source = window.BenchToolsCore.rootFiles(pack);
    if (!files['level.dat'] || !readNBT(files['level.dat']).littleEndian) throw new Error('Choose a Bedrock .mcworld.');
    var manifest = window.BenchToolsCore.parse(source['manifest.json'], 'manifest.json');
    if (!manifest.modules.some(function (module) { return module.type === 'resources'; })) throw new Error('Choose a Bedrock resource pack.');
    var folder = 'resource_packs/cubeon_' + manifest.header.uuid + '/';
    Object.keys(source).forEach(function (path) { if (!path.startsWith('.cubeon/')) files[folder + path] = source[path]; });
    var references = files['world_resource_packs.json'] ? window.BenchToolsCore.parse(files['world_resource_packs.json']) : [];
    references = references.filter(function (ref) { return ref.pack_id !== manifest.header.uuid; }); references.push({pack_id: manifest.header.uuid, version: manifest.header.version});
    files['world_resource_packs.json'] = window.BenchToolsCore.json(references);
    return files;
  }
  function nbtJSON(document) {
    var value = {format: document.format, root: document.root, compression: document.compression, littleEndian: document.littleEndian, header: document.header && Array.from(document.header)};
    return encoder.encode(JSON.stringify(value, function (_, item) { return typeof item === 'bigint' ? item.toString() : item instanceof Uint8Array ? Array.from(item) : item; }, 2));
  }
  function node(type, value) { return {type: type, value: value}; }
  function list(type, values) { return {type: 9, listType: type, value: values.map(function (value) { return node(type, value); })}; }
  function compound(value) { return node(10, value); }
  function structureToSchematic(document) {
    var root = document.root, size = plain(tag(root, 'size')), palette = tag(root, 'palette'), blocks = tag(root, 'blocks');
    if (!size || size.length !== 3 || !palette || !blocks || size.some(function (n) { return !Number.isInteger(n) || n < 1 || n > 32767; }) || size[0] * size[1] * size[2] > 262144) throw new Error('Choose a Java structure NBT of at most 262,144 blocks.');
    if (value(root, 'entities', []).length) throw new Error('This structure has entities. Use lossless NBT JSON, or remove entities before converting to a Sponge v2 block schematic.');
    var entries = Object.create(null), indices = new Uint32Array(size[0] * size[1] * size[2]), air;
    palette.value.forEach(function (block, index) {
      var name = value(block, 'Name', ''), properties = plain(tag(block, 'Properties'));
      if (!/^[-a-z0-9_]+:[-a-z0-9_/.]+$/.test(name)) throw new Error('The palette has an invalid block identifier.');
      if (properties && Object.keys(properties).length) name += '[' + Object.keys(properties).sort().map(function (key) { return key + '=' + properties[key]; }).join(',') + ']';
      entries[name] = node(3, index); if (name === 'minecraft:air') air = index;
    });
    if (air == null) { air = palette.value.length; entries['minecraft:air'] = node(3, air); } indices.fill(air);
    var blockEntities = [];
    blocks.value.forEach(function (block) {
      var pos = plain(tag(block, 'pos')), state = value(block, 'state', -1);
      if (!pos || pos.length !== 3 || pos.some(function (n, k) { return !Number.isInteger(n) || n < 0 || n >= size[k]; }) || state < 0 || state >= palette.value.length) throw new Error('The structure has an invalid block position or palette index.');
      indices[pos[0] + pos[2] * size[0] + pos[1] * size[0] * size[2]] = state;
      var entity = tag(block, 'nbt'); if (entity) { var data = Object.assign(Object.create(null), entity.value); if (data.id) { data.Id = data.id; delete data.id; } data.Pos = node(11, pos); blockEntities.push(compound(data)); }
    });
    var data = [];
    indices.forEach(function (index) { do { var byte = index & 127; index >>>= 7; data.push(byte | (index ? 128 : 0)); } while (index); });
    return {format: 'cubeon-nbt', compression: 'gzip', littleEndian: false, root: Object.assign(compound({Version: node(3, 2), DataVersion: tag(root, 'DataVersion') || node(3, 0), Width: node(2, size[0]), Height: node(2, size[1]), Length: node(2, size[2]), Offset: node(11, [0, 0, 0]), PaletteMax: node(3, Object.keys(entries).length), Palette: compound(entries), BlockData: node(7, new Uint8Array(data)), BlockEntities: {type: 9, listType: 10, value: blockEntities}}), {name: 'Schematic'})};
  }
  function schematicToStructure(document) {
    var root = tag(document.root, 'Schematic') || document.root;
    if (value(root, 'Version', 0) !== 2) throw new Error('Choose a Sponge v2 .schem. Other NBT can be converted losslessly to typed JSON.');
    var size = [value(root, 'Width'), value(root, 'Height'), value(root, 'Length')], total = size[0] * size[1] * size[2], source = tag(root, 'Palette'), encoded = value(root, 'BlockData');
    if (!source || !encoded || !Number.isInteger(total) || total < 1 || total > 262144) throw new Error('Choose a schematic of at most 262,144 blocks.');
    var palette = [], mapping = {};
    Object.keys(source.value).sort(function (a, b) { return source.value[a].value - source.value[b].value; }).forEach(function (name) {
      var match = /^([^\[]+)(?:\[(.+)\])?$/.exec(name); if (!match) throw new Error('Invalid schematic block state.');
      var data = {Name: node(8, match[1])};
      if (match[2]) { var properties = Object.create(null); match[2].split(',').forEach(function (part) { var i = part.indexOf('='); if (i < 1) throw new Error('Invalid schematic block property.'); properties[part.slice(0, i)] = node(8, part.slice(i + 1)); }); data.Properties = compound(properties); }
      mapping[source.value[name].value] = palette.length; palette.push(compound(data));
    });
    var entities = new Map(); (value(root, 'BlockEntities', [])).forEach(function (entity) { var pos = value(entity, 'Pos'); if (!pos) throw new Error('A block entity has no position.'); entities.set(pos.join(','), entity); });
    var blocks = [], offset = 0;
    for (var i = 0; i < total; i++) {
      var index = 0, shift = 0, byte;
      do { if (offset >= encoded.length || shift > 28) throw new Error('The schematic block data is truncated.'); byte = encoded[offset++]; index |= (byte & 127) << shift; shift += 7; } while (byte & 128);
      if (mapping[index] == null) throw new Error('The schematic references an unknown palette entry.');
      var pos = [i % size[0], Math.floor(i / (size[0] * size[2])), Math.floor(i / size[0]) % size[2]], block = {pos: list(3, pos), state: node(3, mapping[index])};
      if (entities.has(pos.join(','))) { var data = Object.assign(Object.create(null), entities.get(pos.join(',')).value); if (data.Id) { data.id = data.Id; delete data.Id; } delete data.Pos; block.nbt = compound(data); }
      blocks.push(compound(block));
    }
    if (offset !== encoded.length) throw new Error('Unexpected schematic block data.');
    return {format: 'cubeon-nbt', compression: 'gzip', littleEndian: false, root: Object.assign(compound({DataVersion: tag(root, 'DataVersion') || node(3, 0), size: list(3, size), palette: {type: 9, listType: 10, value: palette}, blocks: {type: 9, listType: 10, value: blocks}, entities: {type: 9, listType: 10, value: []}}), {name: ''})};
  }
  window.WorldTools = {readNBT: readNBT, writeNBT: writeNBT, tag: tag, value: value, plain: plain, regionChunks: regionChunks, buildRegion: buildRegion, scanWorld: scanWorld,
    repairWorld: repairWorld, pruneWorld: pruneWorld, rescueBedrock: rescueBedrock, attachBedrockPack: attachBedrockPack, nbtJSON: nbtJSON, structureToSchematic: structureToSchematic, schematicToStructure: schematicToStructure};
})();
