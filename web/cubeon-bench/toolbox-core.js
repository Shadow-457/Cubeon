(function () {
  'use strict';
  // File-producing tools share one implementation with the workspace and tests.
  var encoder = new TextEncoder(), decoder = new TextDecoder();
  function json(value) { return encoder.encode(JSON.stringify(value, null, 2) + '\n'); }
  function parse(bytes, name) {
    try { return JSON.parse(decoder.decode(bytes)); }
    catch (_) { throw new Error((name || 'This file') + ' contains invalid JSON.'); }
  }
  function copyFiles(files) { return Object.assign(Object.create(null), files); }
  function clamp(value, min, max) { return Math.max(min, Math.min(max, Number(value) || 0)); }
  function uuid() { return crypto.randomUUID(); }
  function slug(name) { return String(name).toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_|_$/g, '').slice(0, 60) || 'cubeon'; }
  function rootFiles(files) {
    var names = Object.keys(files).filter(function (path) { return !path.startsWith('__MACOSX/') && !path.endsWith('/'); });
    var roots = names.filter(function (path) { return !path.includes('.cubeon/') && /(^|\/)(pack\.mcmeta|manifest\.json|level\.dat)$/.test(path); });
    var root = roots.find(function (path) { return !path.includes('/'); });
    if (!root && roots.length === 1) root = roots[0];
    if (!root) return copyFiles(files);
    var prefix = root.slice(0, root.lastIndexOf('/') + 1), result = Object.create(null);
    names.forEach(function (path) { if (path.startsWith(prefix)) result[path.slice(prefix.length)] = files[path]; });
    return result;
  }
  async function readPack(input) {
    var bytes = input instanceof Uint8Array ? input : new Uint8Array(await input.arrayBuffer());
    return rootFiles(await window.BenchArchive.read(bytes));
  }
  function javaMetadata(name, version, description) {
    var RP = window.ResourcePacks;
    return RP.metadata({name: name, description: description || name, minecraftVersion: version || RP.defaultVersion});
  }
  function bedrockManifest(name, description, moduleType) {
    return {format_version: 2, header: {name: name, description: description || 'Made in Cubeon Bench', uuid: uuid(), version: [1, 0, 0], min_engine_version: [1, 21, 0]},
      modules: [{type: moduleType || 'resources', uuid: uuid(), version: [1, 0, 0]}], metadata: {authors: ['Cubeon Bench']}};
  }
  function textureId(path) {
    var match = /^assets\/([a-z0-9_.-]+)\/textures\/(.+)\.png$/.exec(path);
    return match ? (match[1] === 'minecraft' ? '' : match[1] + ':') + match[2] : null;
  }
  function pngSize(bytes) {
    if (!bytes || bytes.length < 33 || ![137, 80, 78, 71, 13, 10, 26, 10].every(function (byte, i) { return bytes[i] === byte; })) throw new Error('Invalid PNG image.');
    var view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), w = view.getUint32(16), h = view.getUint32(20);
    if (!w || !h || w * h > 16777216) throw new Error('Images must contain at most 16 million pixels.');
    return {w: w, h: h};
  }

  // These are edition contracts, not guesses based on file extensions. Unknown
  // resources are carried in the conversion archive and listed in its report.
  var blockNames = {grass_block_top: 'grass_top', grass_block_side: 'grass_side', grass_block_side_overlay: 'grass_side_carried', dirt_path_top: 'grass_path_top', dirt_path_side: 'grass_path_side',
    oak_planks: 'planks_oak', spruce_planks: 'planks_spruce', birch_planks: 'planks_birch', jungle_planks: 'planks_jungle', acacia_planks: 'planks_acacia', dark_oak_planks: 'planks_big_oak',
    oak_log: 'log_oak', oak_log_top: 'log_oak_top', spruce_log: 'log_spruce', spruce_log_top: 'log_spruce_top', birch_log: 'log_birch', birch_log_top: 'log_birch_top',
    jungle_log: 'log_jungle', jungle_log_top: 'log_jungle_top', acacia_log: 'log_acacia', acacia_log_top: 'log_acacia_top', dark_oak_log: 'log_big_oak', dark_oak_log_top: 'log_big_oak_top',
    oak_leaves: 'leaves_oak', spruce_leaves: 'leaves_spruce', birch_leaves: 'leaves_birch', jungle_leaves: 'leaves_jungle', acacia_leaves: 'leaves_acacia', dark_oak_leaves: 'leaves_big_oak',
    stone_bricks: 'stonebrick', cracked_stone_bricks: 'stonebrick_cracked', mossy_stone_bricks: 'stonebrick_mossy', chiseled_stone_bricks: 'stonebrick_carved',
    bricks: 'brick', cobweb: 'web', short_grass: 'tallgrass', redstone_torch: 'redstone_torch_on', redstone_torch_off: 'redstone_torch_off',
    melon_side: 'melon_side', melon_top: 'melon_top', carved_pumpkin: 'pumpkin_face_off', jack_o_lantern: 'pumpkin_face_on',
    nether_bricks: 'nether_brick', end_stone_bricks: 'end_bricks', quartz_block_side: 'quartz_block_side', snow: 'snow',
    light_gray_wool: 'wool_colored_silver', water_still: 'water_still', water_flow: 'water_flow', lava_still: 'lava_still', lava_flow: 'lava_flow'};
  var itemNames = {totem_of_undying: 'totem', wooden_sword: 'wood_sword', wooden_pickaxe: 'wood_pickaxe', wooden_axe: 'wood_axe', wooden_shovel: 'wood_shovel', wooden_hoe: 'wood_hoe',
    golden_sword: 'gold_sword', golden_pickaxe: 'gold_pickaxe', golden_axe: 'gold_axe', golden_shovel: 'gold_shovel', golden_hoe: 'gold_hoe', golden_helmet: 'gold_helmet',
    golden_chestplate: 'gold_chestplate', golden_leggings: 'gold_leggings', golden_boots: 'gold_boots', leather_horse_armor: 'leather_horse_armor',
    fire_charge: 'fireball', gunpowder: 'gunpowder', slime_ball: 'slimeball', glistering_melon_slice: 'melon_speckled', melon_slice: 'melon',
    popped_chorus_fruit: 'chorus_fruit_popped', experience_bottle: 'experience_bottle', turtle_scute: 'turtle_shell_piece'};
  var colors = ['white', 'orange', 'magenta', 'light_blue', 'yellow', 'lime', 'pink', 'gray', 'light_gray', 'cyan', 'purple', 'blue', 'brown', 'green', 'red', 'black'];
  colors.forEach(function (color) {
    var old = color === 'light_gray' ? 'silver' : color;
    blockNames[color + '_wool'] = 'wool_colored_' + old;
    blockNames[color + '_terracotta'] = 'hardened_clay_stained_' + old;
    blockNames[color + '_stained_glass'] = 'glass_' + old;
    blockNames[color + '_concrete'] = 'concrete_' + old;
    blockNames[color + '_concrete_powder'] = 'concrete_powder_' + old;
  });
  function bedrockPath(path) {
    var preserved = /^assets\/cubeon_bedrock\/textures\/(.+)\.png$/.exec(path);
    if (preserved) return 'textures/' + preserved[1] + '.png';
    var match = /^assets\/minecraft\/textures\/(block|item)\/([a-z0-9_]+)\.png$/.exec(path);
    if (match) {
      var names = match[1] === 'block' ? blockNames : itemNames, mapped = names[match[2]], candidate = 'textures/' + (match[1] === 'block' ? 'blocks' : 'items') + '/' + (mapped || match[2]);
      return window.BedrockTexturePaths && window.BedrockTexturePaths.includes(candidate) ? candidate + '.png' : null;
    }
    if (path === 'assets/minecraft/textures/entity/zombie/zombie.png') return 'textures/entity/zombie/zombie.png';
    if (path === 'assets/minecraft/textures/misc/enchanted_glint_item.png') return 'textures/misc/enchanted_item_glint.png';
    if (path === 'assets/minecraft/textures/entity/elytra.png' || path === 'assets/minecraft/textures/entity/equipment/wings/elytra.png') return 'textures/entity/elytra.png';
    if (path === 'pack.png') return 'pack_icon.png';
    return null;
  }
  function javaPath(path, editable) {
    var match = /^textures\/(blocks|items)\/([^/]+)\.png$/.exec(path);
    if (match) {
      var names = match[1] === 'blocks' ? blockNames : itemNames, name = Object.keys(names).find(function (key) { return names[key] === match[2]; }) || match[2];
      var id = (match[1] === 'blocks' ? 'block/' : 'item/') + name;
      if (window.MinecraftTextures.resolve(id)) return 'assets/minecraft/textures/' + id + '.png';
    }
    if (path === 'textures/entity/zombie/zombie.png') return 'assets/minecraft/textures/entity/zombie/zombie.png';
    if (path === 'textures/misc/enchanted_item_glint.png') return 'assets/minecraft/textures/misc/enchanted_glint_item.png';
    if (path === 'textures/entity/elytra.png') return 'assets/minecraft/textures/entity/elytra.png';
    if (path === 'pack_icon.png') return 'pack.png';
    if (editable && /^textures\/[a-z0-9_./-]+\.png$/.test(path)) return 'assets/cubeon_bedrock/textures/' + path.slice(9);
    return null;
  }
  function convertPack(source, edition, options) {
    options = options || {};
    if (!['java', 'bedrock'].includes(edition)) throw new Error('Choose Java or Bedrock as the export edition.');
    var input = rootFiles(source), files = Object.create(null), report = {edition: edition, converted: [], editable: [], retained: [], restored: [], warnings: []};
    var originalEdition = input['manifest.json'] ? 'bedrock' : input['pack.mcmeta'] ? 'java' : null;
    if (!originalEdition) throw new Error('Choose a Java pack with pack.mcmeta or a Bedrock resource pack with manifest.json.');
    if (originalEdition === 'bedrock') {
      var manifest = parse(input['manifest.json'], 'manifest.json');
      if (!manifest.modules || !manifest.modules.some(function (module) { return module.type === 'resources'; })) throw new Error('This converter handles resource packs. Behavior-pack scripts and world databases need their own edition-specific tools.');
    }
    var sourceMeta = parse(input[originalEdition === 'java' ? 'pack.mcmeta' : 'manifest.json']);
    var name = options.name || (sourceMeta.header && sourceMeta.header.name) || 'Cubeon pack', description = options.description == null ? name : options.description;
    if (originalEdition === edition) {
      files = copyFiles(input);
      if (edition === 'java') files['pack.mcmeta'] = json(Object.assign({}, sourceMeta, javaMetadata(name, options.version, description)));
      return {files: files, report: report};
    }
    // Keep each source edition once. Returning to an edition first restores its
    // retained baseline, then overlays the current edited textures.
    var restorePrefix = '.cubeon/source/' + edition + '/', sourcePrefix = '.cubeon/source/' + originalEdition + '/';
    Object.keys(input).filter(function (path) { return path.startsWith('.cubeon/'); }).forEach(function (path) {
      files[path] = input[path];
      if (path.startsWith(restorePrefix)) {
        var restored = path.slice(restorePrefix.length);
        if (!restored.startsWith('.cubeon/') && window.BenchArchive.safePath(restored)) { files[restored] = input[path]; report.restored.push(restored); }
      }
    });
    var mappedTextures = new Set();
    Object.keys(input).forEach(function (path) {
      if (path.startsWith('.cubeon/')) return;
      files[sourcePrefix + path] = input[path];
      if (path === 'pack.mcmeta' || path === 'manifest.json') return;
      var mapped = edition === 'bedrock' ? bedrockPath(path) : javaPath(path);
      if (mapped) { files[mapped] = input[path]; report.converted.push({from: path, to: mapped}); if (/\.png$/.test(mapped)) mappedTextures.add(mapped); }
      else {
        report.retained.push(path);
        var proxy = edition === 'java' && javaPath(path, true);
        if (proxy) { files[proxy] = input[path]; mappedTextures.add(proxy); report.editable.push({from: path, to: proxy}); }
      }
    });
    if (edition === 'bedrock') {
      var flipbooks = files['textures/flipbook_textures.json'] ? parse(files['textures/flipbook_textures.json'], 'flipbook_textures.json') : [];
      if (!Array.isArray(flipbooks)) throw new Error('Bedrock flipbook_textures.json must be an array.');
      flipbooks = flipbooks.filter(function (animation) { return !mappedTextures.has(animation.flipbook_texture + '.png'); });
      Object.keys(input).filter(function (path) { return path.endsWith('.png.mcmeta'); }).forEach(function (path) {
        var target = bedrockPath(path.slice(0, -7));
        if (!target) return;
        try {
          var animation = parse(input[path], path).animation;
          if (!animation) return;
          var size = pngSize(input[path.slice(0, -7)]), frame = animation.height || animation.width || Math.min(size.w, size.h);
          if (size.w !== frame || size.h % frame || animation.frames && animation.frames.some(function (entry) { return typeof entry === 'object' && entry.time !== (animation.frametime || 1); })) {
            report.warnings.push(path + ': Bedrock cannot use this frame layout or per-frame timing. The original metadata is retained.'); return;
          }
          flipbooks.push({flipbook_texture: target.slice(0, -4), atlas_tile: target.split('/').pop().slice(0, -4), ticks_per_frame: animation.frametime || 1,
            frames: animation.frames ? animation.frames.map(function (entry) { return typeof entry === 'object' ? entry.index : entry; }) : Array.from({length: size.h / frame}, function (_, i) { return i; }), blend_frames: !!animation.interpolate});
        } catch (error) { report.warnings.push(error.message); }
      });
      if (flipbooks.length) files['textures/flipbook_textures.json'] = json(flipbooks); else delete files['textures/flipbook_textures.json'];
      var restoredManifest = files['manifest.json'] ? parse(files['manifest.json'], 'manifest.json') : bedrockManifest(name, description);
      restoredManifest.header.name = name; restoredManifest.header.description = description;
      files['manifest.json'] = json(restoredManifest);
    } else {
      var restoredMeta = files['pack.mcmeta'] ? parse(files['pack.mcmeta'], 'pack.mcmeta') : {};
      files['pack.mcmeta'] = json(Object.assign({}, restoredMeta, javaMetadata(name, options.version, description)));
      mappedTextures.forEach(function (path) {
        if (!files[path + '.mcmeta']) return;
        var meta = parse(files[path + '.mcmeta'], path + '.mcmeta'); delete meta.animation;
        if (Object.keys(meta).length) files[path + '.mcmeta'] = json(meta); else delete files[path + '.mcmeta'];
      });
      if (input['textures/flipbook_textures.json']) {
        var sourceAnimations = parse(input['textures/flipbook_textures.json'], 'flipbook_textures.json');
        if (!Array.isArray(sourceAnimations)) throw new Error('Bedrock flipbook_textures.json must be an array.');
        sourceAnimations.forEach(function (animation) {
          var target = javaPath(animation.flipbook_texture + '.png', true);
          if (target && files[target]) {
            var extra = files[target + '.mcmeta'] ? parse(files[target + '.mcmeta']) : {};
            extra.animation = {frametime: animation.ticks_per_frame || 1, frames: animation.frames, interpolate: !!animation.blend_frames};
            files[target + '.mcmeta'] = json(extra);
          }
        });
      }
    }
    if (report.retained.length) report.warnings.push(report.retained.length + ' edition-specific files are preserved under .cubeon/source. They do not run in the target edition.');
    if (report.editable.length) report.warnings.push(report.editable.length + ' Bedrock images remain editable in Bench and export back to their original paths. They do not replace Java textures.');
    if (!report.converted.some(function (entry) { return entry.to.startsWith('textures/') || entry.to.startsWith('assets/'); })) report.warnings.push('No standard texture replacements translate to this edition. Source resources are retained; inspect the report before using the pack.');
    files['.cubeon/conversion.json'] = json(report);
    return {files: files, report: report};
  }
  function diagnose(source) {
    var files = rootFiles(source), issues = [], paths = Object.keys(files), metadata, edition = files['manifest.json'] ? 'bedrock' : 'java';
    function issue(level, path, message) { issues.push({level: level, path: path, message: message}); }
    paths.forEach(function (path) {
      if (/\.(json|mcmeta)$/.test(path)) {
        try { parse(files[path], path); } catch (error) { issue('error', path, error.message); }
      }
      if (/\.png$/i.test(path)) {
        try { pngSize(files[path]); } catch (error) { issue('error', path, error.message); }
      }
      if (/\.png\.mcmeta$/.test(path) && !files[path.slice(0, -7)]) issue('warning', path, 'Animation metadata has no matching texture.');
    });
    if (edition === 'java') {
      if (!files['pack.mcmeta']) issue('error', 'pack.mcmeta', 'The pack metadata is missing.');
      else try {
        metadata = parse(files['pack.mcmeta'], 'pack.mcmeta');
        if (!metadata.pack || metadata.pack.description == null) issue('error', 'pack.mcmeta', 'Add a pack description.');
        if (!metadata.pack || !Number.isFinite(metadata.pack.pack_format) && metadata.pack.min_format == null) issue('error', 'pack.mcmeta', 'Minecraft compatibility is missing.');
        if (metadata.pack && (metadata.pack.min_format == null) !== (metadata.pack.max_format == null)) issue('error', 'pack.mcmeta', 'Both min_format and max_format are required.');
      } catch (_) {}
      paths.filter(function (path) { return /assets\/[^/]+\/models\/.+\.json$/.test(path); }).forEach(function (path) {
        try {
          var model = parse(files[path], path), namespace = path.split('/')[1];
          Object.values(model.textures || {}).forEach(function (ref) {
            if (typeof ref !== 'string' || ref.startsWith('#')) return;
            var parts = ref.includes(':') ? ref.split(':') : [namespace, ref], texture = 'assets/' + parts[0] + '/textures/' + parts[1] + '.png';
            if (!files[texture] && !(parts[0] === 'minecraft' && window.MinecraftTextures.resolve(parts[1]))) issue('warning', path, 'Missing texture reference: ' + ref);
          });
        } catch (_) {}
      });
    } else try {
      metadata = parse(files['manifest.json'], 'manifest.json');
      var header = metadata.header || {}, modules = metadata.modules || [], ids = [header.uuid].concat(modules.map(function (module) { return module.uuid; }));
      if (metadata.format_version !== 2) issue('warning', 'manifest.json', 'Use manifest format_version 2 for current Bedrock.');
      if (!header.name || !Array.isArray(header.version)) issue('error', 'manifest.json', 'The manifest needs a name and a numeric version array.');
      if (!modules.length) issue('error', 'manifest.json', 'The manifest has no modules.');
      if (ids.some(function (id) { return !/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(id || ''); })) issue('error', 'manifest.json', 'Every header and module needs a valid UUID.');
      if (new Set(ids).size !== ids.length) issue('error', 'manifest.json', 'Header and module UUIDs must be different.');
      if (modules.some(function (module) { return module.type === 'script'; })) issue('warning', 'manifest.json', 'Script modules may require Beta APIs or a matching Minecraft script dependency. Check the dependencies and world settings.');
      (metadata.dependencies || []).forEach(function (dependency) { if (dependency.uuid) issue('info', 'manifest.json', 'Install the companion pack ' + dependency.uuid + ' at version ' + JSON.stringify(dependency.version) + '.'); });
    } catch (_) {}
    return {edition: edition, files: paths.length, textures: paths.filter(function (path) { return /\.png$/i.test(path); }).length, bytes: paths.reduce(function (sum, path) { return sum + files[path].length; }, 0), issues: issues, metadata: metadata};
  }
  function repairPack(source, options) {
    var files = rootFiles(source), before = diagnose(files), repairs = [];
    if (before.edition === 'java') {
      var previous;
      try { previous = parse(files['pack.mcmeta']); } catch (_) {}
      files['pack.mcmeta'] = json(Object.assign({}, previous || {}, javaMetadata(options.name, options.version, options.description)));
      repairs.push('Placed valid Java metadata at the pack root for ' + (options.version || window.ResourcePacks.defaultVersion) + '.');
    } else {
      var manifest = parse(files['manifest.json'], 'manifest.json');
      manifest.format_version = 2; manifest.header = manifest.header || {};
      manifest.header.name = manifest.header.name || options.name; manifest.header.description = manifest.header.description || options.description || options.name;
      manifest.header.version = manifest.header.version || [1, 0, 0];
      var used = new Set();
      [manifest.header].concat(manifest.modules || []).forEach(function (part) {
        if (!/^[\da-f-]{36}$/i.test(part.uuid || '') || used.has(part.uuid)) { part.uuid = uuid(); repairs.push('Assigned a distinct UUID to a manifest component.'); }
        used.add(part.uuid); part.version = part.version || [1, 0, 0];
      });
      files['manifest.json'] = json(manifest);
    }
    files['.cubeon/repair-report.json'] = json({repairs: repairs, remaining: diagnose(files).issues});
    return {files: files, repairs: repairs, report: diagnose(files)};
  }
  function conflictGroups(packs) {
    var owners = new Map();
    packs.forEach(function (pack, index) { Object.keys(pack.files).forEach(function (path) { if (!owners.has(path)) owners.set(path, []); owners.get(path).push(index); }); });
    return Array.from(owners).filter(function (pair) { return pair[1].length > 1 && !pair[0].startsWith('.cubeon/') && !['pack.mcmeta', 'manifest.json', 'pack.png', 'pack_icon.png'].includes(pair[0]); });
  }
  function mergePacks(packs, options) {
    if (packs.length < 2 || packs.length > 3) throw new Error('Choose two or three packs.');
    var edition = packs[0].files['manifest.json'] ? 'bedrock' : 'java', files = Object.create(null), owners = {}, surfaces = {};
    packs.forEach(function (pack, index) {
      if ((pack.files['manifest.json'] ? 'bedrock' : 'java') !== edition) throw new Error('Convert the packs to the same edition before merging.');
      Object.keys(pack.files).forEach(function (path) {
        if (!path.startsWith('.cubeon/')) { files[path] = pack.files[path]; owners[path] = index; }
      });
    });
    Object.keys(options.winners || {}).forEach(function (path) {
      var index = Number(options.winners[path]);
      if (!packs[index] || !packs[index].files[path]) throw new Error('A selected conflict source is missing.');
      files[path] = packs[index].files[path]; owners[path] = index;
    });
    // Texture families follow the selected color texture, including animation
    // and LabPBR data. A stale shader map from a losing pack must not survive.
    Object.keys(files).filter(function (path) { return textureId(path) && !/_[ns]\.png$/.test(path); }).forEach(function (path) {
      var owner = owners[path], source = packs[owner].files, base = path.slice(0, -4);
      [path + '.mcmeta', base + '_n.png', base + '_n.png.mcmeta', base + '_s.png', base + '_s.png.mcmeta'].forEach(function (other) {
        if (source[other]) files[other] = source[other]; else delete files[other];
      });
      try {
        var extra = source['.cubeon/project.json'] && parse(source['.cubeon/project.json']);
        var surface = extra && extra.surfaces && extra.surfaces[textureId(path)];
        if (surface) { surfaces[textureId(path)] = surface; if (surface.heightFile && source[surface.heightFile]) files[surface.heightFile] = source[surface.heightFile]; }
      } catch (_) {}
    });
    if (edition === 'java') files['pack.mcmeta'] = json(javaMetadata(options.name, options.version, options.description));
    else files['manifest.json'] = json(bedrockManifest(options.name, options.description));
    files['.cubeon/project.json'] = json({schema: 1, name: options.name, minecraftVersion: options.version, surfaces: surfaces});
    files['.cubeon/merge-report.json'] = json({sources: packs.map(function (pack) { return pack.name; }), conflicts: conflictGroups(packs).length, winners: options.winners || {}});
    return {files: files, edition: edition, conflicts: conflictGroups(packs)};
  }
  function subpacks(packs, name) {
    if (packs.length < 2 || packs.length > 8) throw new Error('Choose between two and eight Bedrock resource packs.');
    var files = Object.create(null), manifest = bedrockManifest(name), options = [];
    packs.forEach(function (pack, i) {
      var source = rootFiles(pack.files), original = parse(source['manifest.json'], 'manifest.json');
      if (!original.modules.some(function (module) { return module.type === 'resources'; })) throw new Error('Subpacks require Bedrock resource packs.');
      var folder = 'option_' + (i + 1);
      options.push({folder_name: folder, name: pack.name, memory_tier: i});
      Object.keys(source).forEach(function (path) {
        if (!['manifest.json', 'pack_icon.png'].includes(path) && !path.startsWith('.cubeon/')) files['subpacks/' + folder + '/' + path] = source[path];
      });
      if (i === 0 && source['pack_icon.png']) files['pack_icon.png'] = source['pack_icon.png'];
    });
    manifest.subpacks = options; files['manifest.json'] = json(manifest);
    return files;
  }
  function image(w, h) { return new ImageData(w, h); }
  function cloneImage(source) { return new ImageData(new Uint8ClampedArray(source.data), source.width, source.height); }
  function rgb(hex) { return [1, 3, 5].map(function (i) { return parseInt(hex.slice(i, i + 2), 16); }); }
  function blit(target, source, crop, dest, overlay) {
    for (var y = 0; y < dest[3]; y++) for (var x = 0; x < dest[2]; x++) {
      var sx = Math.min(source.width - 1, crop[0] + Math.floor(x / dest[2] * crop[2])), sy = Math.min(source.height - 1, crop[1] + Math.floor(y / dest[3] * crop[3]));
      var tx = dest[0] + x, ty = dest[1] + y;
      if (tx < 0 || ty < 0 || tx >= target.width || ty >= target.height) continue;
      var si = (sy * source.width + sx) * 4, ti = (ty * target.width + tx) * 4;
      if (overlay && !source.data[si + 3]) continue;
      target.data.set(source.data.subarray(si, si + 4), ti);
    }
    return target;
  }
  function normalizeSkin(source) {
    if (source.width !== 64 || ![32, 64].includes(source.height)) throw new Error('Choose a 64×64 or legacy 64×32 Minecraft skin.');
    if (source.height === 64) return cloneImage(source);
    var result = image(64, 64); blit(result, source, [0, 0, 64, 32], [0, 0, 64, 32]);
    // Legacy left limbs mirror the corresponding right-limb faces.
    [[0, 16, 16, 48], [40, 16, 32, 48]].forEach(function (part) {
      [[4, 0, 4, 4, 4, 0], [8, 0, 4, 4, 8, 0], [0, 4, 4, 12, 8, 4], [4, 4, 4, 12, 4, 4], [8, 4, 4, 12, 0, 4], [12, 4, 4, 12, 12, 4]].forEach(function (face) {
        for (var y = 0; y < face[3]; y++) for (var x = 0; x < face[2]; x++) {
          var si = ((part[1] + face[1] + y) * 64 + part[0] + face[0] + face[2] - x - 1) * 4;
          var ti = ((part[3] + face[5] + y) * 64 + part[2] + face[4] + x) * 4;
          result.data.set(source.data.subarray(si, si + 4), ti);
        }
      });
    });
    return result;
  }
  function totem(source, hat) {
    var skin = normalizeSkin(source), result = image(16, 16);
    blit(result, skin, [8, 8, 8, 8], [4, 0, 8, 8]);
    if (hat !== false) blit(result, skin, [40, 8, 8, 8], [4, 0, 8, 8], true);
    blit(result, skin, [20, 20, 8, 12], [5, 8, 6, 5]);
    blit(result, skin, [44, 20, 4, 12], [2, 8, 3, 5]);
    blit(result, skin, [36, 52, 4, 12], [11, 8, 3, 5]);
    blit(result, skin, [4, 20, 4, 12], [5, 13, 3, 3]);
    blit(result, skin, [20, 52, 4, 12], [8, 13, 3, 3]);
    return result;
  }
  function wardrobe(source, shirt, trousers, style) {
    var result = normalizeSkin(source);
    function fill(rect, color) {
      var c = rgb(color);
      for (var y = rect[1]; y < rect[1] + rect[3]; y++) for (var x = rect[0]; x < rect[0] + rect[2]; x++) {
        var i = (y * 64 + x) * 4, shade = ((x + y) % 7 === 0 ? .84 : 1);
        for (var k = 0; k < 3; k++) result.data[i + k] = Math.round(c[k] * shade);
        result.data[i + 3] = 255;
      }
    }
    [[16, 16, 24, 16], [40, 16, 16, 11], [32, 48, 16, 11]].forEach(function (rect) { fill(rect, shirt); });
    [[0, 16, 16, 16], [16, 48, 16, 16]].forEach(function (rect) { fill(rect, trousers); });
    if (style === 'jacket') { fill([23, 20, 2, 12], '#26342b'); fill([23, 20, 2, 2], '#ebefe5'); }
    return result;
  }
  function crosshair(color, style, thickness, gap) {
    var result = image(15, 15), c = rgb(color).concat(255), t = Math.round(clamp(thickness, 1, 4)), g = Math.round(clamp(gap, 0, 4));
    for (var y = 0; y < 15; y++) for (var x = 0; x < 15; x++) {
      var dx = Math.abs(x - 7), dy = Math.abs(y - 7), on = style === 'dot' ? dx < t && dy < t : style === 'ring' ? Math.abs(Math.sqrt(dx * dx + dy * dy) - 5) < t / 2 :
        (dx < t / 2 && dy > g && dy < 7 || dy < t / 2 && dx > g && dx < 7);
      if (on) result.data.set(c, (y * 15 + x) * 4);
    }
    return result;
  }
  function recolor(source, color, strength) {
    var result = cloneImage(source), c = rgb(color), amount = clamp(strength == null ? 1 : strength, 0, 1);
    for (var i = 0; i < result.data.length; i += 4) {
      var lum = (source.data[i] * .2126 + source.data[i + 1] * .7152 + source.data[i + 2] * .0722) / 255;
      for (var k = 0; k < 3; k++) result.data[i + k] = Math.round(source.data[i + k] * (1 - amount) + c[k] * lum * amount);
    }
    return result;
  }
  function glint(color, rainbow, off) {
    var result = image(64, 64), c = rgb(color);
    for (var y = 0; y < 64; y++) for (var x = 0; x < 64; x++) {
      var stripe = (x + y * 2) % 32, i = (y * 64 + x) * 4, amount = stripe < 5 ? .95 : stripe < 13 ? .25 : .04;
      var hue = x / 64, palette = rainbow ? [Math.sin(hue * Math.PI * 2) * 127 + 128, Math.sin((hue + 1 / 3) * Math.PI * 2) * 127 + 128, Math.sin((hue + 2 / 3) * Math.PI * 2) * 127 + 128] : c;
      result.data.set([palette[0] * amount, palette[1] * amount, palette[2] * amount, off ? 0 : 255], i);
    }
    return result;
  }
  function itemModel(item, scale, rotation) {
    if (!/^[a-z0-9_]+$/.test(item)) throw new Error('Choose a valid item identifier.');
    scale = clamp(scale, .1, 4); rotation = clamp(rotation, -180, 180);
    var model = {parent: 'minecraft:item/handheld', textures: {layer0: 'minecraft:item/' + item}, display: {}};
    ['thirdperson_righthand', 'thirdperson_lefthand'].forEach(function (hand) { model.display[hand] = {rotation: [0, -90, 55 + rotation], translation: [0, 4, .5], scale: [.85 * scale, .85 * scale, .85 * scale]}; });
    ['firstperson_righthand', 'firstperson_lefthand'].forEach(function (hand) { model.display[hand] = {rotation: [0, -90, 25 + rotation], translation: [1.13, 3.2, 1.13], scale: [.68 * scale, .68 * scale, .68 * scale]}; });
    return model;
  }
  function headCommand(name, version, textureValue) {
    if (!/^[a-zA-Z0-9_]{1,16}$/.test(name)) throw new Error('Enter a Minecraft name with 1–16 letters, numbers or underscores.');
    if (textureValue) {
      if (!/^[a-zA-Z0-9+/=]+$/.test(textureValue)) throw new Error('The texture property is invalid.');
      return '/give @s minecraft:player_head[minecraft:profile={properties:[{name:"textures",value:"' + textureValue + '"}]}] 1';
    }
    return version === 'legacy' ? '/give @s minecraft:player_head{SkullOwner:"' + name + '"} 1' : '/give @s minecraft:player_head[minecraft:profile={name:"' + name + '"}] 1';
  }
  function textComponents(text, start, end, bold, italic) {
    var a = rgb(start), b = rgb(end), chars = Array.from(String(text));
    if (chars.length > 1000) throw new Error('Text is limited to 1,000 characters.');
    return chars.map(function (char, i) {
      var t = chars.length > 1 ? i / (chars.length - 1) : 0;
      var color = '#' + a.map(function (channel, k) { return Math.round(channel + (b[k] - channel) * t).toString(16).padStart(2, '0'); }).join('');
      return {text: char, color: color, bold: !!bold, italic: !!italic};
    });
  }
  function legacyText(components) {
    var palette = ['000000', '0000aa', '00aa00', '00aaaa', 'aa0000', 'aa00aa', 'ffaa00', 'aaaaaa', '555555', '5555ff', '55ff55', '55ffff', 'ff5555', 'ff55ff', 'ffff55', 'ffffff'];
    return components.map(function (part) {
      var color = rgb(part.color), best = 0, distance = Infinity;
      palette.forEach(function (hex, index) { var c = rgb('#' + hex), d = c.reduce(function (sum, channel, k) { return sum + Math.pow(channel - color[k], 2); }, 0); if (d < distance) { distance = d; best = index; } });
      return '§' + best.toString(16) + (part.bold ? '§l' : '') + (part.italic ? '§o' : '') + part.text;
    }).join('');
  }

  var enchants = [
    ['sharpness', 5, 1, 'weapon'], ['smite', 5, 1, 'weapon'], ['bane_of_arthropods', 5, 1, 'weapon'], ['knockback', 2, 1, 'sword'], ['fire_aspect', 2, 2, 'sword'], ['looting', 3, 2, 'sword'], ['sweeping_edge', 3, 2, 'sword'],
    ['efficiency', 5, 1, 'tool'], ['silk_touch', 1, 4, 'tool'], ['fortune', 3, 2, 'tool'], ['unbreaking', 3, 1, 'all'], ['mending', 1, 2, 'all'],
    ['protection', 4, 1, 'armor'], ['fire_protection', 4, 1, 'armor'], ['blast_protection', 4, 2, 'armor'], ['projectile_protection', 4, 1, 'armor'], ['thorns', 3, 4, 'armor'],
    ['feather_falling', 4, 1, 'boots'], ['depth_strider', 3, 2, 'boots'], ['frost_walker', 2, 2, 'boots'], ['soul_speed', 3, 4, 'boots'], ['respiration', 3, 2, 'helmet'], ['aqua_affinity', 1, 2, 'helmet'],
    ['power', 5, 1, 'bow'], ['punch', 2, 2, 'bow'], ['flame', 1, 2, 'bow'], ['infinity', 1, 4, 'bow'], ['quick_charge', 3, 1, 'crossbow'], ['piercing', 4, 1, 'crossbow'], ['multishot', 1, 2, 'crossbow'],
    ['loyalty', 3, 1, 'trident'], ['impaling', 5, 2, 'trident'], ['riptide', 3, 2, 'trident'], ['channeling', 1, 4, 'trident'], ['density', 5, 1, 'mace'], ['breach', 4, 2, 'mace'], ['wind_burst', 3, 2, 'mace']
  ];
  function anvilPlan(entries, prior) {
    if (!entries.length || entries.length > 10) throw new Error('Choose between one and ten enchanted books.');
    var ids = new Set(), conflictSets = [['sharpness', 'smite', 'bane_of_arthropods', 'density', 'breach'], ['silk_touch', 'fortune'], ['mending', 'infinity'], ['protection', 'fire_protection', 'blast_protection', 'projectile_protection'], ['depth_strider', 'frost_walker'], ['riptide', 'loyalty'], ['riptide', 'channeling'], ['multishot', 'piercing']];
    var books = entries.map(function (entry) {
      var info = enchants.find(function (row) { return row[0] === entry.id; });
      if (!info || !Number.isInteger(entry.level) || entry.level < 1 || entry.level > info[1] || ids.has(entry.id)) throw new Error('Choose distinct enchantments at their valid levels.');
      ids.add(entry.id); return {label: entry.id.replace(/_/g, ' ') + ' ' + entry.level, value: entry.level * info[2], penalty: 0, cost: 0, steps: [], item: false};
    });
    conflictSets.forEach(function (group) { if (group.filter(function (id) { return ids.has(id); }).length > 1) throw new Error('These enchantments conflict: ' + group.filter(function (id) { return ids.has(id); }).join(', ') + '.'); });
    var leaves = [{label: 'Your item', value: 0, penalty: Math.pow(2, Math.round(clamp(prior, 0, 5))) - 1, cost: 0, steps: [], item: true}].concat(books), table = new Map();
    leaves.forEach(function (leaf, i) { table.set(1 << i, [leaf]); });
    var full = (1 << leaves.length) - 1;
    for (var mask = 1; mask <= full; mask++) {
      if (table.has(mask)) continue;
      var states = new Map();
      for (var left = (mask - 1) & mask; left; left = (left - 1) & mask) {
        var right = mask ^ left;
        if (!right || left & 1 && right & 1 || right & 1) continue;
        (table.get(left) || []).forEach(function (a) { (table.get(right) || []).forEach(function (b) {
          var levelCost = a.penalty + b.penalty + b.value;
          if (levelCost >= 40) return;
          var penalty = Math.max(a.penalty, b.penalty) * 2 + 1, cost = a.cost + b.cost + levelCost;
          var key = penalty, old = states.get(key);
          if (!old || cost < old.cost) states.set(key, {label: a.item ? 'Your item' : '(' + a.label + ' + ' + b.label + ')', value: a.value + b.value, penalty: penalty, cost: cost, item: a.item,
            steps: a.steps.concat(b.steps, [{left: a.label, right: b.label, levels: levelCost, result: a.item ? 'Your item' : '(' + a.label + ' + ' + b.label + ')'}])});
        }); });
      }
      table.set(mask, Array.from(states.values()));
    }
    var result = (table.get(full) || []).sort(function (a, b) { return a.cost - b.cost; })[0];
    if (!result) throw new Error('No Survival anvil order fits below 40 levels. Use an item with fewer prior anvil uses or fewer books.');
    return result;
  }
  function seedValue(value) {
    var text = String(value).trim();
    if (!text) return 0n;
    if (/^-?\d+$/.test(text)) {
      var n = BigInt(text);
      if (n < -(1n << 63n) || n >= 1n << 63n) throw new Error('A numeric Java seed must fit in a signed 64-bit integer.');
      return n;
    }
    var hash = 0;
    for (var i = 0; i < text.length; i++) hash = Math.imul(hash, 31) + text.charCodeAt(i) | 0;
    return BigInt(hash);
  }
  function javaRandom(seed) {
    var state = (BigInt.asUintN(64, seed) ^ 0x5deece66dn) & ((1n << 48n) - 1n);
    return {next: function (bits) { state = (state * 0x5deece66dn + 11n) & ((1n << 48n) - 1n); return Number(state >> BigInt(48 - bits)); }, nextInt: function (bound) {
      if ((bound & -bound) === bound) return Number(BigInt(bound) * BigInt(this.next(31)) >> 31n);
      var bits, value; do { bits = this.next(31); value = bits % bound; } while ((bits - value + bound - 1 | 0) < 0); return value;
    }};
  }
  function slimeChunk(seed, x, z, edition) {
    if (!Number.isInteger(x) || !Number.isInteger(z) || Math.abs(x) > 1875000 || Math.abs(z) > 1875000) throw new Error('Chunk coordinates are outside Minecraft’s world bounds.');
    if (edition === 'bedrock') {
      var mt = new Uint32Array(624); mt[0] = (Math.imul(x, 0x1f1f1f1f) ^ z) >>> 0;
      for (var i = 1; i < 624; i++) mt[i] = (Math.imul(1812433253, mt[i - 1] ^ mt[i - 1] >>> 30) + i) >>> 0;
      var y = mt[0] & 0x80000000 | mt[1] & 0x7fffffff;
      var value = mt[397] ^ y >>> 1 ^ (y & 1 ? 0x9908b0df : 0);
      value ^= value >>> 11; value ^= value << 7 & 0x9d2c5680; value ^= value << 15 & 0xefc60000; value ^= value >>> 18;
      return (value >>> 0) % 10 === 0;
    }
    var mixed = seedValue(seed) + BigInt(Math.imul(Math.imul(x, x), 4987142)) + BigInt(Math.imul(x, 5947611)) + BigInt(Math.imul(z, z)) * 4392871n + BigInt(Math.imul(z, 389711));
    return javaRandom(BigInt.asIntN(64, mixed) ^ 987234911n).nextInt(10) === 0;
  }
  window.BenchToolsCore = {json: json, parse: parse, clamp: clamp, slug: slug, copyFiles: copyFiles, rootFiles: rootFiles, readPack: readPack, javaMetadata: javaMetadata, bedrockManifest: bedrockManifest,
    pngSize: pngSize, textureId: textureId, convertPack: convertPack, bedrockPath: bedrockPath, javaPath: javaPath, diagnose: diagnose, repairPack: repairPack, conflictGroups: conflictGroups,
    mergePacks: mergePacks, subpacks: subpacks, image: image, cloneImage: cloneImage, rgb: rgb, blit: blit, normalizeSkin: normalizeSkin, totem: totem, wardrobe: wardrobe,
    crosshair: crosshair, recolor: recolor, glint: glint, itemModel: itemModel, headCommand: headCommand, textComponents: textComponents, legacyText: legacyText, enchants: enchants, anvilPlan: anvilPlan,
    seedValue: seedValue, javaRandom: javaRandom, slimeChunk: slimeChunk};
})();
