(async function () {
  'use strict';
  const result = {passed: [], errors: [], snapshots: {}, viewport: [innerWidth, innerHeight]};
  const $ = selector => document.querySelector(selector), sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const assert = (value, message) => { if (!value) throw Error(message); };
  const click = selector => { assert($(selector), 'Missing ' + selector); $(selector).click(); };
  const input = (selector, value, event = 'input') => { $(selector).value = value; $(selector).dispatchEvent(new Event(event, {bubbles: true})); };
  window.addEventListener('error', event => { if (event.message) result.errors.push(event.message); });
  window.addEventListener('unhandledrejection', event => result.errors.push(String(event.reason)));
  async function until(test, message) { for (let i = 0; i < 1000; i++) { if (test()) return; await sleep(10); } throw Error(message); }
  function pass(message) { result.passed.push(message); console.log('PASS:', message); }
  function state() {
    const cv = $('#ec'), data = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
    let hash = 2166136261;
    for (let i = 0; i < data.length; i += 4) for (let c = 0; c < 4; c++) hash = Math.imul(hash ^ (c < 3 ? Math.round(data[i + c] * data[i + 3] / 255) : data[i + c]), 16777619);
    return {w: cv.width, h: cv.height, hash: hash >>> 0};
  }
  function pixel(x = 0, y = 0) { return [...$('#ec').getContext('2d').getImageData(x, y, 1, 1).data].join(','); }
  function paint(x = 0, y = 0) {
    const cv = $('#ec'), rect = cv.getBoundingClientRect(), options = {button: 0, pointerId: 41, bubbles: true,
      clientX: rect.left + (x + .5) * rect.width / cv.width, clientY: rect.top + (y + .5) * rect.height / cv.height};
    cv.dispatchEvent(new PointerEvent('pointerdown', options)); cv.dispatchEvent(new PointerEvent('pointerup', options));
  }
  async function texture(id, source) {
    input('#edQ', id); click('#edRes [data-id="' + id + '"]');
    await until(() => $('#edPath').textContent === source && $('#edArea').style.display !== 'none', 'Texture did not open: ' + id);
  }
  function fileInput(selector, file) { const transfer = new DataTransfer(); transfer.items.add(file); $(selector).files = transfer.files; $(selector).dispatchEvent(new Event('change', {bubbles: true})); }
  async function save() { const pending = window.CB.save(); await window.LocalStore.flush(); assert(await pending, 'Local save failed'); }
  function snapshot(name) {
    const copy = document.documentElement.cloneNode(true), originals = document.querySelectorAll('canvas');
    const base = document.createElement('base'); base.href = new URL('.', location.href).href; copy.querySelector('head').prepend(base);
    copy.querySelectorAll('canvas').forEach((canvas, i) => {
      if (originals[i].width && originals[i].height) { canvas.style.backgroundImage = 'url("' + originals[i].toDataURL() + '")'; canvas.style.backgroundSize = '100% 100%'; }
    });
    copy.querySelectorAll('input').forEach((node, i) => { const original = document.querySelectorAll('input')[i]; node.setAttribute('value', original.value); });
    copy.querySelectorAll('textarea').forEach((node, i) => { node.textContent = document.querySelectorAll('textarea')[i].value; });
    copy.querySelectorAll('select').forEach((node, i) => { const value = document.querySelectorAll('select')[i].value; for (const option of node.options) option.toggleAttribute('selected', option.value === value); });
    copy.querySelectorAll('script').forEach(script => script.remove());
    const style = document.createElement('style'); style.textContent = '*,*::before,*::after{animation:none!important;transition:none!important}'; copy.querySelector('head').append(style);
    result.snapshots[name] = '<!doctype html>\n' + copy.outerHTML;
  }
  const bytes = text => new TextEncoder().encode(text), parse = value => JSON.parse(new TextDecoder().decode(value));
  async function solidPNG(size, color) {
    const cv = document.createElement('canvas'); cv.width = cv.height = size;
    const ctx = cv.getContext('2d'); ctx.fillStyle = color; ctx.fillRect(0, 0, size, size);
    return new Uint8Array(await (await new Promise(resolve => cv.toBlob(resolve))).arrayBuffer());
  }
  async function firstPixelPNG(data) {
    const url = URL.createObjectURL(new Blob([data], {type: 'image/png'})), image = new Image(); image.src = url;
    try { await image.decode(); const cv = document.createElement('canvas'); cv.width = image.width; cv.height = image.height;
      const ctx = cv.getContext('2d'); ctx.drawImage(image, 0, 0); return {w: cv.width, h: cv.height, pixel: [...ctx.getImageData(0, 0, 1, 1).data].join(',')};
    } finally { URL.revokeObjectURL(url); }
  }
  try {
    await window.CB.ready;
    assert(window.LocalStore.mode() === 'indexedDB', 'IndexedDB was not available');
    if (window.CB_WORKFLOW_REOPEN) {
      const expected = JSON.parse(localStorage.getItem('cb-reopen-check')), large = window.CB.find(expected.largeId);
      assert(window.CB.D.profile.picture === expected.profilePicture && $('#avb img'), 'Custom profile picture did not survive browser restart');
      assert(large && large.description === 'A large local project', 'Large project metadata did not survive restart');
      await window.Ed.open(large); await texture('block/stone', 'textures/block/stone.png'); assert(JSON.stringify(state()) === JSON.stringify(expected.stone), 'Large texture did not survive browser restart');
      await texture('block/dirt', 'textures/block/dirt.png'); assert(JSON.stringify(state()) === JSON.stringify(expected.dirt), 'Second large texture did not survive restart');
      const imported = window.CB.find(expected.importedId); assert(imported && imported.minecraftVersion === 'imported', 'Imported compatibility did not survive restart');
      await window.Ed.open(imported); assert(pixel() === '0,0,255,255' && $('#ec').width === 32, 'Imported original pixels did not survive restart');
      const stored = await window.LocalStore.getFiles(imported.assetId);
      assert(stored['extras/reference.bin'].length === 6291456 && stored['extras/reference.bin'][6291455] === 93, 'Large imported archive file did not survive restart');
      assert(parse(stored['assets/demo/models/block/neon.json']).parent === 'minecraft:block/cube_all', 'Imported models did not survive restart');
      const blob = await window.ResourcePacks.buildZip(imported), archive = window.fflate.unzipSync(new Uint8Array(await blob.arrayBuffer()));
      assert(archive['extras/reference.bin'].length === 6291456 && parse(archive['pack.mcmeta']).pack.pack_format === 34, 'Restarted project cannot export its complete resource pack');
      pass('large edits, imported binary files, models, and playable ZIP export after a full browser restart');
    } else {
      assert(!$('#cubeonAuth') && !$('#google') && $('#guest').textContent.includes('Open my bench'), 'Local app should open without an unfinished sign-in flow');
      snapshot('local-welcome');
      await window.enterApp({name: 'Studio'}); await until(() => $('#app').classList.contains('on'), 'App did not open');
      assert(!$('#home-lib') && $('[data-go="library"]'), 'Texture browsing belongs in the Library view');
      window.CB.D.set.calm = true; window.CB.renderAll();
      click('[data-go="settings"]');
      const profileFile = new File([await solidPNG(48, '#4488bb')], 'profile.png', {type: 'image/png'});
      fileInput('#profilePicker', profileFile);
      await until(() => window.CB.D.profile.picture.startsWith('data:image/png') && !$('#uploadProfilePicture').disabled, 'Custom profile picture did not save');
      assert($('#avb img') && $('#usr img') && $('#setAv img') && !$('#removeProfilePicture').hidden, 'Custom profile picture is missing from the profile UI');
      click('#removeProfilePicture'); await save(); assert(!$('#avb img') && $('#removeProfilePicture').hidden, 'Removing the profile picture did not restore initials');
      fileInput('#profilePicker', profileFile); await until(() => window.CB.D.profile.picture && !$('#uploadProfilePicture').disabled, 'Profile picture did not reload');
      snapshot('custom-profile-picture');
      pass('local profile-picture upload/removal and working account-free welcome');
      click('[data-new]');
      assert(!$('#mpal') && !$('#spal'), 'Palette selection should be removed');
      input('#mn', 'Studio pack'); input('#mdescription', 'Studio colors\nA handmade resource pack.'); input('#mcreator', 'Studio maker'); input('#mpackversion', '2.3.4'); input('#mminecraft', '1.21.1', 'change');
      fileInput('#micon', new File([await solidPNG(32, '#22bb77')], 'icon.png', {type: 'image/png'}));
      await until(() => $('#miconPreview').style.backgroundImage.includes('data:image/png'), 'Pack icon did not load');
      snapshot('pack-details'); click('#mcreate');
      await until(() => $('#edName').textContent === 'Studio pack' && $('#edArea').style.display !== 'none', 'New pack did not open');
      const fresh = window.CB.D.projects[0];
      assert(fresh.description.includes('\n') && fresh.author === 'Studio maker' && fresh.packVersion === '2.3.4' && fresh.minecraftVersion === '1.21.1', 'New-project metadata was not saved');

      click('#edCol'); assert(!$('#colorChooser').hidden, 'Custom color chooser did not open');
      input('#colorR', 142); input('#colorG', 77); input('#colorB', 218);
      assert($('#edHex').value === '#8E4DDA', 'Exact RGB entry');
      input('#colorHex', '#000000'); input('#colorHue', 240);
      assert($('#edHex').value === '#000000' && $('#colorHue').value === '240', 'Hue resets when choosing black');
      const square = $('#colorSV'), rect = square.getBoundingClientRect();
      square.dispatchEvent(new PointerEvent('pointerdown', {button: 0, pointerId: 42, clientX: rect.right, clientY: rect.top}));
      square.dispatchEvent(new PointerEvent('pointerup', {pointerId: 42}));
      assert($('#edHex').value === '#0000FF', 'Saturation/brightness selection');
      square.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', shiftKey: true, bubbles: true}));
      assert($('#colorSV').getAttribute('aria-valuetext').includes('brightness 90%'), 'Color square keyboard adjustment');
      input('#colorHex', '#0000FF'); input('#colorAlpha', 25);
      assert($('#edAlpha').value === '25' && $('#edAlphaValue').value === '25%', 'Color opacity does not sync');
      snapshot('custom-color-chooser'); click('#colorDone'); const original = state(); paint();
      assert(pixel() === '0,0,255,64', 'Painting with custom color and opacity');
      click('#edUndo'); assert(JSON.stringify(state()) === JSON.stringify(original), 'Custom color undo'); click('#edRedo');
      assert($('#edRec [data-c="#0000ff"]'), 'Custom color was not added to recent colors');
      input('#edAlpha', 0); paint(1, 0); assert(pixel(1, 0).endsWith(',0'), 'Fully transparent color painting');
      click('#edCol'); document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); assert($('#colorChooser').hidden, 'Escape does not close color chooser');
      click('#edCol'); $('#edName').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})); assert($('#colorChooser').hidden, 'Outside click does not close color chooser');
      pass('custom HSV, exact RGB/HEX, opacity, keyboard controls, recent colors, painting, and undo');

      click('#edDetails'); input('#mdescription', 'Studio colors\nUpdated locally.'); click('#mcreate');
      await until(() => !$('#modal').classList.contains('show'), 'Pack details did not save'); assert(fresh.description === 'Studio colors\nUpdated locally.', 'Edited pack description');
      await save(); assert($('#edSave').textContent === 'Saved locally', 'Save badge should report real local persistence');
      click('#edExport'); await until(() => $('#packTask').dataset.state === 'done', 'Export button did not complete');
      const exported = window.fflate.unzipSync(new Uint8Array(await (await window.ResourcePacks.buildZip(fresh)).arrayBuffer())), meta = parse(exported['pack.mcmeta']);
      assert(meta.pack.pack_format === 34 && meta.pack.description === fresh.description && !meta.pack.min_format, 'Minecraft 1.21.1 export metadata');
      assert(exported['assets/minecraft/textures/block/grass_block_top.png'] && exported['pack.png'] && exported['.cubeon/project.json'], 'Resource pack root, texture path, or icon missing');
      assert(parse(exported['.cubeon/project.json']).author === 'Studio maker' && parse(exported['.cubeon/project.json']).packVersion === '2.3.4', 'Creator/version metadata missing from ZIP');
      const png = await firstPixelPNG(exported['assets/minecraft/textures/block/grass_block_top.png']); assert(png.w === 16 && png.h === 16 && png.pixel === '0,0,255,64', 'Exported PNG pixels or transparency changed');
      const modern = window.ResourcePacks.metadata(Object.assign({}, fresh, {minecraftVersion: '26.1'}));
      assert(JSON.stringify(modern.pack.min_format) === '[84,0]' && JSON.stringify(modern.pack.max_format) === '[84,0]' && !('pack_format' in modern.pack), 'Modern Minecraft compatibility metadata');
      pass('project descriptions, creator/version, pack icons, native download, correct ZIP paths, and modern/legacy compatibility');

      const water = window.MinecraftTextures.resolve('block/water_still'), payload = new Uint8Array(6291456); payload[0] = 17; payload[payload.length - 1] = 93;
      const importedMeta = {pack: {pack_format: 34, supported_formats: {min_inclusive: 34, max_inclusive: 34}, description: {text: 'Archive colors', color: 'gold', extra: [{text: '\nFrom ZIP'}]}}, custom: {keep: true}};
      const source = {'pack.mcmeta': bytes(JSON.stringify(importedMeta)), 'pack.png': await solidPNG(32, '#22bb77'),
        'assets/minecraft/textures/block/stone.png': await solidPNG(32, '#0000ff'), 'assets/minecraft/textures/block/stone.png.mcmeta': bytes('{"texture":{"blur":false}}'),
        'assets/minecraft/textures/block/water_still.png': await window.MinecraftTextures.bytes(water), 'assets/minecraft/textures/block/water_still.png.mcmeta': bytes(JSON.stringify(water.mcmeta)),
        'assets/demo/textures/block/neon.png': await solidPNG(16, '#00ffff'), 'assets/demo/models/block/neon.json': bytes('{"parent":"minecraft:block/cube_all","textures":{"all":"demo:block/neon"}}'),
        'assets/demo/font/custom.json': bytes('{"providers":[]}'), 'assets/demo/sounds.json': bytes('{}'), 'assets/demo/lang/en_us.json': bytes('{"block.demo.neon":"Neon"}'),
        'notes.txt': bytes('Author notes must survive'), 'extras/reference.bin': payload,
        '.cubeon/project.json': bytes('{"schema":1,"name":"Imported studio","author":"Archive maker","packVersion":"1.7.2","texture":"block/stone"}')};
      const wrapped = Object.fromEntries(Object.entries(source).map(([path, value]) => ['MyPack/' + path, value]));
      const archiveBytes = window.fflate.zipSync(wrapped, {level: 0});
      window.Ed.close(); fileInput('#packImport', new File([archiveBytes], 'wrapped.zip', {type: 'application/zip'}));
      await until(() => window.CB.D.projects[0].name === 'Imported studio' && $('#edPath').textContent === 'assets/minecraft/textures/block/stone.png' && $('#edArea').style.display !== 'none', 'Wrapped ZIP did not import');
      await until(() => $('#packTask').dataset.state === 'done', 'Import did not finish');
      const imported = window.CB.D.projects[0];
      assert($('#ec').width === 32 && $('#ec').height === 32 && pixel() === '0,0,255,255', 'Imported pack reuses vanilla pixels or rescales existing HD textures');
      assert(imported.description === 'Archive colors\nFrom ZIP' && imported.author === 'Archive maker' && imported.minecraftVersion === 'imported', 'Imported pack details');
      input('#edCat', 'assets', 'change'); assert($('#edCount').textContent === '1 texture', 'Custom namespace folder category');
      await texture('demo:block/neon', 'assets/demo/textures/block/neon.png'); assert(pixel() === '0,255,255,255', 'Custom namespace PNG');
      click('#edTabs [data-id="preview"]'); await until(() => document.querySelectorAll('#pvW .pv-face').length === 6, 'Custom namespace block preview');
      assert($('#pvW .pv-face-front').dataset.texture === 'assets/demo/textures/block/neon.png', 'Custom namespace block material');
      snapshot('imported-pack-preview');
      await texture('block/stone', 'assets/minecraft/textures/block/stone.png'); input('#edHex', '#AA2233'); paint();
      click('#edDetails'); assert($('#mminecraft').value === 'imported' && !$('#mpal'), 'Imported compatibility or palette option'); click('#mcreate'); await until(() => !$('#modal').classList.contains('show'), 'Imported details did not close');
      const roundTrip = window.fflate.unzipSync(new Uint8Array(await (await window.ResourcePacks.buildZip(imported)).arrayBuffer()));
      assert(JSON.stringify(parse(roundTrip['pack.mcmeta'])) === JSON.stringify(importedMeta), 'Rich imported descriptions, compatibility ranges, or extra metadata changed');
      for (const [path, originalBytes] of Object.entries(source)) {
        if (path === 'assets/minecraft/textures/block/stone.png' || path === '.cubeon/project.json' || path === 'pack.mcmeta') continue;
        const restored = roundTrip[path]; assert(restored && restored.length === originalBytes.length && restored.every((value, i) => value === originalBytes[i]), 'Imported file changed: ' + path);
      }
      assert(!Object.keys(roundTrip).some(path => path.startsWith('MyPack/')), 'Wrapper folder was not flattened');
      assert((await firstPixelPNG(roundTrip['assets/minecraft/textures/block/stone.png'])).pixel === '170,34,51,255', 'Imported texture edits missing from export');
      const secondMeta = {pack: {min_format: [91, 4], max_format: [91, 9], description: 'Future format'}};
      const secondArchive = window.fflate.zipSync({'pack.mcmeta': bytes(JSON.stringify(secondMeta)), 'assets/minecraft/textures/block/stone.png': await solidPNG(16, '#ff0000')}, {level: 0});
      const second = await window.ResourcePacks.importFile(new File([secondArchive], 'Second.zip', {type: 'application/zip'}));
      assert(pixel() === '255,0,0,255' && $('#ec').width === 16, 'Cross-project texture cache collision');
      assert(JSON.stringify(window.ResourcePacks.metadata(second)) === JSON.stringify(secondMeta), 'Unknown imported Minecraft compatibility was not retained');
      await window.Ed.open(imported); click('[data-a="reset"]'); await until(() => pixel() === '0,0,255,255', 'Reset uses another pack’s original texture');
      let invalid = false; try { await window.ResourcePacks.inspectZip(window.fflate.zipSync({'assets/minecraft/textures/block/stone.png': source['assets/minecraft/textures/block/stone.png']})); } catch (error) { invalid = error.message.includes('pack.mcmeta'); }
      assert(invalid, 'ZIP without Minecraft metadata was accepted');
      pass('ZIP import, wrapper flattening, original HD pixels, namespaces, previews, cache isolation, metadata, animation files, models, fonts, and binary preservation');

      const images = [new ImageData(512, 512), new ImageData(512, 512)]; let seed = 1234567;
      for (const image of images) for (let i = 0; i < image.data.length; i += 4) { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; image.data[i] = seed >>> 24; image.data[i + 1] = seed >>> 16 & 255; image.data[i + 2] = seed >>> 8 & 255; image.data[i + 3] = 255; }
      const now = Date.now(), large = {id: 'large-local-check', name: 'Large local project', type: 'pack', size: 16, pal: 'meadow', texture: 'block/stone',
        description: 'A large local project', author: 'Local studio', minecraftVersion: '26.1', created: now, edited: now,
        edits: {'block/stone': window.TextureCodec.encode(images[0]), 'block/dirt': window.TextureCodec.encode(images[1])}};
      assert(large.edits['block/stone'].pixels.length + large.edits['block/dirt'].pixels.length > 5242880, 'Large fixture does not exceed localStorage capacity');
      window.CB.D.projects.unshift(large); await window.Ed.open(large); const stone = state(); await texture('block/dirt', 'textures/block/dirt.png'); const dirt = state(); await save();
      const stored = (await window.LocalStore.loadState()).projects.find(project => project.id === large.id);
      assert(stored.edits['block/stone'].pixels === large.edits['block/stone'].pixels && stored.edits['block/dirt'].pixels === large.edits['block/dirt'].pixels, 'Large project did not persist exactly');
      assert(localStorage.getItem('cb-data').length < 262144 && !JSON.parse(localStorage.getItem('cb-data')).projects.find(project => project.id === large.id).edits, 'Large edits are still stored in localStorage');
      const nativeTransaction = IDBDatabase.prototype.transaction;
      try {
        IDBDatabase.prototype.transaction = function (stores, mode, ...rest) { if (mode === 'readwrite' && (stores === 'workspace' || Array.isArray(stores) && stores.includes('workspace'))) throw new DOMException('Injected disk capacity failure', 'QuotaExceededError'); return nativeTransaction.call(this, stores, mode, ...rest); };
        const pending = window.CB.save(); await window.LocalStore.flush(); assert(await pending === false && $('#edSave').textContent === 'Not saved', 'Storage failure falsely reports saved');
      } finally { IDBDatabase.prototype.transaction = nativeTransaction; }
      await save(); assert($('#edSave').textContent === 'Saved locally', 'Local save did not recover');
      localStorage.setItem('cb-reopen-check', JSON.stringify({largeId: large.id, importedId: imported.id, stone, dirt, profilePicture: window.CB.D.profile.picture}));
      pass('projects above 5 MB in IndexedDB, small startup metadata, truthful save failures, and recovery');
      window.Ed.close(); click('[data-go="projects"]');
      assert(window.Motion.reduced(), 'Reduce-motion setting was ignored');
      assert(getComputedStyle($('.nav-indicator')).transitionDuration.split(',').every(value => parseFloat(value) === 0), 'Reduced motion still animates navigation');
      window.CB.D.set.calm = false; window.CB.renderAll(); click('[data-go="library"]'); await sleep(30);
      assert($('#v-library').getAnimations({subtree: true}).length > 0, 'Coordinated view transitions did not run');
      window.CB.D.set.calm = true; window.CB.renderAll(); await sleep(450); await save();
      pass('coordinated navigation/view motion and the reduce-motion setting');
    }
    assert(!result.errors.length, 'JavaScript errors: ' + result.errors.join('; '));
  } catch (error) { result.failure = String(error) + '\n' + (error.stack || ''); }
  const link = document.createElement('a'); link.download = window.CB_WORKFLOW_REOPEN ? 'firefox-reopen.json' : 'firefox-results.json';
  link.href = URL.createObjectURL(new Blob([JSON.stringify(result)], {type: 'application/json'})); document.body.append(link); link.click();
  setTimeout(function () { window.close(); }, 700);
})();
