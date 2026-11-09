(function () {
  'use strict';
  var CB = window.CB, C = window.BenchToolsCore, A = window.BenchArchive, handlers = {}, current = null, generation = 0, cleanups = [], query = '', category = 'All';
  var tools = [
    ['pack', 'Pack studio', 'Paint blocks and items, animate frames and export your pack.', 'Pack assets', 'pack'],
    ['skin', 'Skin studio', 'Edit your character on the canvas and in 3D.', 'Artwork', 'user'],
    ['avatar', 'Player portraits', 'Make a head, bust or full-body profile picture.', 'Artwork', 'user'],
    ['totem', 'Pocket totems', 'Turn a Minecraft skin into your own totem texture.', 'Artwork', 'flame'],
    ['seed', 'Seed explorer', 'Map Java biomes and structures, or find slime chunks.', 'Worlds', 'grid'],
    ['merge', 'Pack mixer', 'Combine two or three packs and resolve texture conflicts.', 'Pack assets', 'copy'],
    ['thumbnail', 'Thumbnail studio', 'Pose your character and export a 1280×720 scene.', 'Artwork', 'grid'],
    ['music', 'Music discs', 'Put an audio clip on a Minecraft disc.', 'Pack assets', 'item'],
    ['item-size', 'Held item settings', 'Change a tool’s in-hand size and rotation.', 'Pack assets', 'item'],
    ['heads', 'Player heads', 'Generate head commands for your Minecraft version.', 'Utilities', 'user'],
    ['anvil', 'Enchantment planner', 'Find a low-cost Survival order for your enchanted books.', 'Utilities', 'item'],
    ['text', 'Text studio', 'Create gradients for MOTDs, chat, signs and item names.', 'Utilities', 'pen'],
    ['cape', 'Cape canvas', 'Design a cape PNG and an elytra resource pack.', 'Artwork', 'pal'],
    ['zombie', 'Zombie wardrobe', 'Use your skin as the zombie texture in a pack.', 'Artwork', 'user'],
    ['skins', 'Player lookup', 'Look up a public profile and open its skin in Bench.', 'Artwork', 'search'],
    ['capes', 'Cape shelf', 'Preview your own cape files and original Bench patterns.', 'Artwork', 'proj'],
    ['wardrobe', 'Outfit workshop', 'Try new shirt and trouser colors without redrawing a skin.', 'Artwork', 'pal'],
    ['names', 'Name check', 'Check whether a public Minecraft profile uses a name.', 'Utilities', 'search'],
    ['battle', 'Skin picks', 'Compare two skins and keep your favorites on this device.', 'Artwork', 'copy'],
    ['daily', 'Daily skin quiz', 'Guess one of Minecraft’s nine default skins each day.', 'Artwork', 'user'],
    ['wrapped', 'World postcard', 'Turn your world’s saved statistics into a shareable image.', 'Worlds', 'grid'],
    ['voice', 'Mob voices', 'Record or import a sound and replace a mob’s voice.', 'Pack assets', 'user'],
    ['subpacks', 'Bedrock options', 'Bundle several resource packs as selectable subpacks.', 'Pack assets', 'pack'],
    ['skin-pack', 'Bedrock skin bundle', 'Package a collection of PNG skins into one .mcpack.', 'Artwork', 'pack'],
    ['world-finder', 'World finder', 'Find saved pets, players, containers and dropped items.', 'Worlds', 'search'],
    ['doctor', 'Pack checkup', 'Inspect manifests, images, JSON, dependencies and references.', 'Pack assets', 'set'],
    ['converter', 'Format workbench', 'Convert pack editions, compatibility and structure formats.', 'Utilities', 'rot'],
    ['console', 'Console pack kit', 'Attach a Bedrock resource pack to a world for Realm transfer.', 'Worlds', 'pack'],
    ['world-doctor', 'World checkup', 'Inspect a world and recover a valid metadata backup.', 'Worlds', 'set'],
    ['world-refresh', 'Refresh world edges', 'Preserve a build area and regenerate outer Java chunks.', 'Worlds', 'grid'],
    ['world-rescue', 'Bedrock world recovery', 'Reset recognized Creative and cheats flags in a world copy.', 'Worlds', 'undo'],
    ['collection', 'Bench collection', 'Collect, favorite and exchange portable packs and skins.', 'Utilities', 'proj'],
    ['guides', 'Bench field guide', 'Install packs and understand editions, shaders and local saves.', 'Utilities', 'open'],
    ['sky', 'Sky & panorama', 'Build a six-face menu panorama or an OptiFine sky.', 'Pack assets', 'sun'],
    ['title', 'Title screen', 'Make a wordmark, splash messages and a loading background.', 'Pack assets', 'pen'],
    ['gui', 'Interface colors', 'Recolor containers, buttons and inventory screens.', 'Pack assets', 'pal'],
    ['font', 'Font atlas', 'Build a custom bitmap font for Minecraft Java.', 'Pack assets', 'pen'],
    ['testing', 'Pack test bench', 'Inspect textures, animated frames, 3D blocks and sounds.', 'Pack assets', 'cube'],
    ['pvp', 'PvP loadout mixer', 'Choose swords, crystals and totems from different packs.', 'Pack assets', 'item'],
    ['hud', 'Crosshair & HUD', 'Design a crosshair and recolor hearts, hotbar and boss bars.', 'Pack assets', 'plus'],
    ['glint', 'Enchantment colors', 'Make colored, rainbow or invisible enchantment glint.', 'Pack assets', 'pal'],
    ['model', 'Model workshop', 'Preview and export Minecraft Java JSON block models.', 'Pack assets', 'cube'],
    ['layers', 'Layered painting', 'Add, reorder and blend paint layers in the texture editor.', 'Artwork', 'copy']
  ];
  function $(selector) { return document.querySelector(selector); }
  function dispose() { generation++; cleanups.splice(0).forEach(function (fn) { try { fn(); } catch (_) {} }); }
  function cleanup(fn) { cleanups.push(fn); }
  function state(message, kind) { var el = $('#toolOutput'); if (el) { el.textContent = message; el.dataset.state = kind || 'ready'; } }
  function field(label, input, note) { return '<label class="tool-field"><span>' + CB.esc(label) + '</span>' + input + (note ? '<small>' + CB.esc(note) + '</small>' : '') + '</label>'; }
  function input(id, value, type, attributes) { return '<input id="' + id + '" type="' + (type || 'text') + '" value="' + CB.esc(value == null ? '' : value) + '" ' + (attributes || '') + '>'; }
  function select(id, options, selected) { return '<select id="' + id + '">' + options.map(function (option) { var value = Array.isArray(option) ? option[0] : option, label = Array.isArray(option) ? option[1] : option; return '<option value="' + CB.esc(value) + '"' + (String(value) === String(selected) ? ' selected' : '') + '>' + CB.esc(label) + '</option>'; }).join('') + '</select>'; }
  function file(id, accept, multiple) { return '<input id="' + id + '" type="file" accept="' + accept + '"' + (multiple ? ' multiple' : '') + '>'; }
  function check(id, label, on) { return '<label class="tool-check"><input type="checkbox" id="' + id + '"' + (on ? ' checked' : '') + '>' + CB.esc(label) + '</label>'; }
  function row(a, b) { return '<div class="tool-row">' + a + b + '</div>'; }
  function value(id) { return document.getElementById(id).value; }
  function selectedFile(id) { return document.getElementById(id).files[0]; }
  function edition() { return row(field('Pack name', input('toolName', 'Cubeon creation', 'text', 'maxlength="40"')), field('Export edition', select('toolEdition', [['java', 'Java ZIP'], ['bedrock', 'Bedrock .mcpack']], 'java'))) + field('Java compatibility', select('toolVersion', window.ResourcePacks.versions.map(function (version) { return [version.id, version.label]; }), window.ResourcePacks.defaultVersion)); }
  function buttons(items) { return '<div class="tool-actions">' + items.map(function (item, i) { return '<button type="button" id="' + item[0] + '" class="gb' + (i === 0 ? ' primary-action' : '') + '">' + CB.esc(item[1]) + '</button>'; }).join('') + '</div>'; }
  function mount(id, controls, note, actions) {
    dispose(); current = id;
    var tool = tools.find(function (item) { return item[0] === id; }), root = $('#v-tools');
    root.innerHTML = '<div class="toolbox"><button type="button" class="tool-back" id="toolBack">' + CB.ic('back') + 'Toolbox</button><div class="toolbox-heading"><div><p class="kicker">' + CB.esc(tool[3]) + '</p><h3>' + CB.esc(tool[1]) + '</h3><p>' + CB.esc(tool[2]) + '</p></div><span class="toolbox-label">Made on your bench</span></div>' +
      '<div class="tool-studio"><div class="tool-stage-column"><div class="tool-stage" id="toolPreview"><span class="mu">Preparing preview…</span></div><div class="tool-stage-label"><span id="toolPreviewLabel">Preview</span><span>Files stay on this device</span></div><div id="toolResults" class="tool-results"></div></div><div class="tool-panel"><div class="tool-fields">' + controls + (note ? '<p class="tool-note">' + note + '</p>' : '') + '</div>' + buttons(actions || []) + '<p class="tool-output" id="toolOutput" role="status" aria-live="polite">Ready when you are.</p></div></div></div>';
    $('#toolBack').onclick = hub; if (window.BenchI18n) window.BenchI18n.translate(root);
    return generation;
  }
  function on(id, fn) {
    var button = document.getElementById(id), token = generation;
    button.onclick = async function () {
      if (button.disabled) return;
      button.disabled = true; button.setAttribute('aria-busy', 'true'); state('Working locally…', 'working');
      try { await fn(); } catch (error) { if (token === generation) state(error.message, 'error'); }
      finally { button.disabled = false; button.removeAttribute('aria-busy'); }
    };
  }
  function watch(ids, fn) {
    var timer, token = generation; cleanup(function () { clearTimeout(timer); });
    ids.forEach(function (id) { var el = document.getElementById(id); el.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(function () { if (token === generation) Promise.resolve(fn()).catch(function (error) { state(error.message, 'error'); }); }, 100); }); });
  }
  function preview() { return $('#toolPreview'); }
  function results(html) { $('#toolResults').innerHTML = html; if (window.BenchI18n) window.BenchI18n.translate($('#toolResults')); }
  async function imageBytes(image) { return new Uint8Array(await (await window.TextureCodec.png(image)).arrayBuffer()); }
  async function downloadImage(image, name) { A.download(await window.TextureCodec.png(image), name + '.png'); state('PNG downloaded.', 'success'); }
  function pack(files, name) { var result = C.copyFiles(files); result['pack.mcmeta'] = C.json(C.javaMetadata(name || value('toolName'), $('#toolVersion') ? value('toolVersion') : null)); return result; }
  async function exportPack(files, name, target) {
    name = name || ($('#toolName') ? value('toolName') : 'Cubeon creation'); target = target || ($('#toolEdition') ? value('toolEdition') : 'java');
    var source = files['pack.mcmeta'] || files['manifest.json'] ? files : pack(files, name), report;
    if ((source['manifest.json'] ? 'bedrock' : 'java') !== target) { var converted = C.convertPack(source, target, {name: name, version: $('#toolVersion') ? value('toolVersion') : null}); source = converted.files; report = converted.report; }
    A.download(await A.write(source), name + (target === 'bedrock' ? '.mcpack' : '.zip'));
    state('Pack downloaded.' + (report && report.warnings.length ? '\n' + report.warnings.join('\n') : ''), 'success');
  }
  async function savePack(files, name) {
    var source = files['pack.mcmeta'] || files['manifest.json'] ? files : pack(files, name), edition = $('#toolEdition') ? value('toolEdition') : source['manifest.json'] ? 'bedrock' : 'java';
    if ((source['manifest.json'] ? 'bedrock' : 'java') !== edition) source = C.convertPack(source, edition, {name: name || 'Cubeon creation', version: $('#toolVersion') ? value('toolVersion') : null}).files;
    return window.ResourcePacks.importFile(new File([await A.write(source)], (name || 'Cubeon creation') + (edition === 'bedrock' ? '.mcpack' : '.zip'), {type: 'application/zip'}));
  }
  function diagnostics(report) { return '<p class="tool-note">' + report.files + ' files · ' + report.textures + ' images · ' + (report.bytes / 1048576).toFixed(1) + ' MB · ' + (report.edition === 'java' ? 'Java' : 'Bedrock') + '</p>' + (report.issues.length ? report.issues.map(function (issue) { return '<div class="tool-issue" data-level="' + issue.level + '"><b>' + CB.esc(issue.message) + '</b><code translate="no">' + CB.esc(issue.path) + '</code></div>'; }).join('') : '<p class="tool-output" data-state="success">No structural problems found. Test the exported pack in your target Minecraft version.</p>'); }
  function hub() {
    dispose(); current = null;
    $('#v-tools').innerHTML = '<div class="toolbox"><div class="toolbox-heading"><div><p class="kicker">Cubeon Bench</p><h3>A tool for every idea.</h3><p>Create a character, customize a pack, or explore your world. Everything comes back to your bench.</p></div><span class="toolbox-label">' + tools.length + ' tools · local files</span></div><div class="toolbox-toolbar"><label class="toolbox-search">' + CB.ic('search') + '<input type="search" id="toolSearch" placeholder="Find a tool…" aria-label="Search Toolbox" autocomplete="off" value="' + CB.esc(query) + '"></label><div class="toolbox-filters" id="toolFilters">' + ['All', 'Artwork', 'Pack assets', 'Worlds', 'Utilities'].map(function (name) { return '<button type="button" data-tool-filter="' + CB.esc(name) + '" aria-pressed="' + (category === name) + '">' + name + '</button>'; }).join('') + '</div></div><div class="toolbox-grid" id="toolGrid"></div></div>';
    function render() {
      var found = tools.filter(function (tool) { return (category === 'All' || tool[3] === category) && tool.slice(1, 4).join(' ').toLowerCase().includes(query.toLowerCase()); });
      $('#toolGrid').innerHTML = found.map(function (tool) { return '<button type="button" class="tool-card" data-bench-tool="' + tool[0] + '"><span class="tool-card-icon">' + CB.ic(tool[4]) + '</span><span><h4>' + CB.esc(tool[1]) + '</h4><p>' + CB.esc(tool[2]) + '</p><small>' + CB.esc(tool[3]) + '</small></span><span class="tool-card-arrow" aria-hidden="true">↗</span></button>'; }).join('') || '<p class="toolbox-empty">No matching tools. Try “skin”, “world”, or “pack”.</p>';
      if (window.BenchI18n) window.BenchI18n.translate($('#toolGrid'));
    }
    $('#toolSearch').oninput = function () { query = this.value; render(); };
    $('#toolFilters').onclick = function (event) { var button = event.target.closest('[data-tool-filter]'); if (!button) return; category = button.dataset.toolFilter; $('#toolFilters').querySelectorAll('button').forEach(function (el) { el.setAttribute('aria-pressed', el === button); }); render(); };
    render(); if (window.BenchI18n) window.BenchI18n.translate($('#v-tools'));
  }
  async function open(id) {
    if ($('#ed').classList.contains('show')) window.Ed.close();
    CB.go('tools');
    try { if (handlers[id]) await handlers[id](); else if (id === 'pack' || id === 'skin' || id === 'layers') CB.newProject({type: id === 'skin' ? 'skin' : 'pack'}); }
    catch (error) { state(error.message, 'error'); CB.toast(error.message); }
  }
  document.addEventListener('click', function (event) { var tool = event.target.closest('[data-bench-tool]'); if (tool) open(tool.dataset.benchTool); var nav = event.target.closest('[data-go="tools"]'); if (nav) hub(); });
  document.addEventListener('cb-render', function () { if ($('#v-tools').classList.contains('on')) { if (!current) hub(); } else if (current) { dispose(); current = null; } });
  handlers.guides = function () {
    mount('guides', '', '', []); preview().style.display = 'none'; $('#v-tools .tool-studio').style.gridTemplateColumns = '1fr'; $('#v-tools .tool-panel').hidden = true;
    results('<div class="toolbox-grid"><article class="tool-guide"><h4>Java resource packs</h4><ol><li>Export a ZIP for the version you play.</li><li>Open Minecraft → Options → Resource Packs → Open Pack Folder.</li><li>Place the ZIP there, then enable it and press Done.</li></ol><p>A pack needs <code>pack.mcmeta</code> at its root. Texture files are under <code>assets/&lt;namespace&gt;/textures/</code>. Use Pack checkup when a pack fails to load.</p></article><article class="tool-guide"><h4>Bedrock & consoles</h4><ol><li>Download a <code>.mcpack</code> and open it with Minecraft.</li><li>Enable it under the world’s Resource Packs.</li><li>For consoles, use Console pack kit with a Bedrock world, import it on a supported phone/PC and upload that world to your Realm.</li></ol><p>A Realm and your Microsoft account are managed in Minecraft. Console platforms restrict direct file imports.</p></article><article class="tool-guide"><h4>Skins, capes & shader extras</h4><p>Skin studio exports standard 64×64 PNGs. Java supports Classic and Slim models; select the matching model when changing your skin.</p><p>A custom cape PNG needs a compatible cape service or client. An elytra texture is a normal resource-pack asset. Surface maps require a LabPBR shader, and custom sky/loading backgrounds require OptiFine-compatible support. A menu panorama works in vanilla Java.</p></article><article class="tool-guide"><h4>Keep your work portable</h4><p>Projects, edits, recordings and world files stay in this browser. Settings → Backups exports the whole workspace. Pack and skin downloads can be exchanged and imported through Bench collection.</p><p>Conversions include a report for resources that cannot run in the target edition. World recovery tools generate new copies. Keep the original world until you have opened and checked the copy in Minecraft.</p></article></div>');
  };
  handlers.collection = function () {
    mount('collection', '', '', [['toolImport', 'Import pack or skin'], ['toolBackup', 'Back up collection']]); preview().style.display = 'none'; $('#v-tools .tool-studio').style.gridTemplateColumns = '1fr';
    results('<div class="tool-collection">' + (CB.D.projects.length ? CB.D.projects.map(function (project) { return '<div class="tool-collection-row"><span><b translate="no" dir="auto">' + CB.esc(project.name) + '</b><small>' + (project.type === 'skin' ? 'Skin PNG' : 'Resource pack') + ' · saved in Bench</small></span><div class="tool-actions" style="margin:0"><button type="button" class="gb" data-collection-open="' + project.id + '">Open</button><button type="button" class="gb" data-collection-share="' + project.id + '">Download to share</button><button type="button" class="gb" data-collection-favorite="' + project.id + '">' + (project.favorite ? '★ Favorite' : '☆ Favorite') + '</button></div></div>'; }).join('') : '<p class="tool-note">Import a shared pack or create your first project. Your collection is saved on this device; publishing a community catalogue needs a hosted service.</p>') + '</div>');
    on('toolImport', function () { $('#packImport').value = ''; $('#packImport').click(); }); on('toolBackup', function () { return window.Workspace.exportBackup(); });
    $('#toolResults').onclick = function (event) { var open = event.target.closest('[data-collection-open]'), share = event.target.closest('[data-collection-share]'), favorite = event.target.closest('[data-collection-favorite]'); if (open) window.Ed.open(CB.find(open.dataset.collectionOpen)); if (share) window.ResourcePacks.exportProject(CB.find(share.dataset.collectionShare)); if (favorite) { var p = CB.find(favorite.dataset.collectionFavorite); p.favorite = !p.favorite; CB.save(); handlers.collection(); } };
  };
  handlers.layers = async function () {
    var project = CB.D.projects.slice().sort(function (a, b) { return b.edited - a.edited; })[0];
    if (!project) return CB.newProject({type: 'pack'});
    await window.Ed.open(project); document.getElementById('layerOptions').open = true;
    if (innerWidth <= 900) { document.getElementById('ed').dataset.toolSection = 'tools'; document.getElementById('ed').classList.add('r-open'); }
  };
  window.Toolbox = {register: function (id, fn) { handlers[id] = fn; }, tools: tools, open: open, hub: hub, suspend: function () { dispose(); current = null; }, mount: mount, cleanup: cleanup, current: function (token) { return token === generation; }, token: function () { return generation; },
    $: $, field: field, input: input, select: select, file: file, check: check, row: row, value: value, selectedFile: selectedFile, edition: edition, buttons: buttons, on: on, watch: watch, state: state, preview: preview, results: results,
    imageBytes: imageBytes, downloadImage: downloadImage, pack: pack, exportPack: exportPack, savePack: savePack, diagnostics: diagnostics};
  CB.ready.then(function () { if (!$('#v-tools').children.length) hub(); });
})();
