(function () {
  'use strict';
  var T = window.Toolbox, C = window.BenchToolsCore, M = window.ToolboxMedia, CB = window.CB;
  var defaults = ['steve', 'alex', 'ari', 'efe', 'kai', 'makena', 'noor', 'sunny', 'zuri'];
  function skinFields() {
    var options = [['default:steve', 'Minecraft Steve']].concat(CB.D.projects.filter(function (p) { return p.type === 'skin'; }).map(function (p) { return [p.id, p.name]; }));
    defaults.slice(1).forEach(function (name) { options.push(['default:' + name, 'Minecraft ' + name[0].toUpperCase() + name.slice(1)]); });
    return T.field('Start from a skin', T.select('toolSkin', options)) + T.field('Or choose a skin PNG', T.file('toolSkinFile', '.png,image/png'), '64×64 or legacy 64×32') +
      T.row(T.field('Public player name', T.input('toolPlayer', '', 'text', 'maxlength="16" autocomplete="off"')), '<div class="tool-field"><span>Online lookup</span><button type="button" class="gb" id="toolLookup">Load player skin</button></div>');
  }
  async function defaultSkin(name) { return M.vanilla('entity/player/' + (name === 'alex' ? 'slim' : 'wide') + '/' + name); }
  async function skinSource() {
    var file = T.selectedFile('toolSkinFile'); if (file) return C.normalizeSkin(await M.readImage(file));
    var selected = T.value('toolSkin'); return selected.startsWith('default:') ? defaultSkin(selected.slice(8)) : M.projectSkin(CB.find(selected));
  }
  async function artwork(id) {
    var portrait = id === 'avatar' || id === 'thumbnail', generated, skin, scene, lookupSkin = null;
    var controls = skinFields();
    if (portrait) controls += T.row(T.field('Framing', T.select('toolFraming', [['head', 'Head'], ['bust', 'Bust'], ['body', 'Full body']], id === 'thumbnail' ? 'body' : 'head')), T.field('Pose', T.select('toolPose', [['stand', 'Standing'], ['wave', 'Wave'], ['walk', 'Walking']])));
    if (id === 'avatar') controls += T.field('Image size', T.select('toolImageSize', [256, 512, 1024, 2048], 1024));
    if (id === 'thumbnail') controls += T.field('Thumbnail title', T.input('toolTitle', 'My next adventure', 'text', 'maxlength="60"')) + T.field('Background image', T.file('toolBackdrop', 'image/png,image/jpeg,image/webp'));
    if (portrait) controls += T.row(T.field('Background color', T.input('toolBackground', '#dce9c8', 'color')), T.check('toolTransparent', 'Transparent background', id === 'avatar'));
    if (id === 'wardrobe') controls += T.row(T.field('Shirt', T.input('toolShirt', '#628b38', 'color')), T.field('Trousers', T.input('toolTrousers', '#344052', 'color'))) + T.field('Style', T.select('toolStyle', [['shirt', 'Plain shirt'], ['jacket', 'Jacket']]));
    controls += T.check('toolHat', 'Include outer skin layer', true) + T.check('toolSlim', 'Slim arms', false);
    if (id === 'totem' || id === 'zombie') controls += T.edition();
    var actions = portrait ? [['toolDownload', 'Download PNG'], ['toolProfile', 'Use as profile picture']] : [['toolDownload', 'Download PNG'], ['toolSave', 'Open in editor']];
    if (id === 'totem' || id === 'zombie') actions.push(['toolExport', 'Download resource pack']);
    var token = T.mount(id, controls, portrait ? 'Drag the preview to set the angle. PNGs can have a transparent background.' : id === 'totem' ? 'Your totem is a normal resource-pack texture; Minecraft supplies its behavior.' : id === 'zombie' ? 'This pack changes zombie artwork. It does not change your player skin or mob behavior.' : 'Your original skin is kept. Open the generated skin in Bench to make further edits.', actions);
    if (id !== 'totem') { scene = new M.Scene(T.preview()); T.cleanup(function () { scene.dispose(); }); await scene.init(); }
    async function redraw() {
      var next = lookupSkin || await skinSource(); if (!T.current(token)) return;
      skin = next; generated = id === 'totem' ? C.totem(skin, T.$('#toolHat').checked) : id === 'wardrobe' ? C.wardrobe(skin, T.value('toolShirt'), T.value('toolTrousers'), T.value('toolStyle')) : skin;
      if (id === 'totem') M.paintPreview(T.preview(), generated);
      else scene.skin(generated, {mode: portrait ? T.value('toolFraming') : 'body', pose: portrait ? T.value('toolPose') : 'stand', hat: T.$('#toolHat').checked, slim: T.$('#toolSlim').checked});
      T.$('#toolPreviewLabel').textContent = id === 'totem' ? '16×16 totem texture' : 'Drag to turn the model';
    }
    T.watch(['toolSkin', 'toolSkinFile'], function () { lookupSkin = null; return redraw(); });
    T.watch(['toolHat', 'toolSlim'].concat(portrait ? ['toolFraming', 'toolPose'] : id === 'wardrobe' ? ['toolShirt', 'toolTrousers', 'toolStyle'] : []), redraw);
    T.on('toolLookup', async function () {
      var profile = await M.lookup(T.value('toolPlayer')); if (!T.current(token)) return;
      if (profile.available || !profile.skin) throw new Error('No downloadable skin was found for that public profile. Choose a skin PNG instead.');
      lookupSkin = profile.skin; T.$('#toolSlim').checked = profile.slim; await redraw(); T.state('Loaded ' + profile.name + ' · ' + profile.uuid, 'success');
    });
    async function files() { if (!generated) throw new Error('Choose a skin first.'); var output = {}; output['assets/minecraft/textures/' + (id === 'totem' ? 'item/totem_of_undying.png' : 'entity/zombie/zombie.png')] = await T.imageBytes(generated); return T.pack(output); }
    T.on('toolDownload', async function () {
      if (!generated) throw new Error('Choose a skin first.');
      if (!portrait) return T.downloadImage(generated, 'Cubeon ' + id);
      var size = id === 'thumbnail' ? [1280, 720] : [Number(T.value('toolImageSize')), Number(T.value('toolImageSize'))];
      var options = {background: T.$('#toolTransparent').checked ? 'transparent' : T.value('toolBackground'), title: id === 'thumbnail' ? T.value('toolTitle') : ''};
      if (id === 'thumbnail' && T.selectedFile('toolBackdrop')) options.image = await M.readImage(T.selectedFile('toolBackdrop'));
      window.BenchArchive.download(await scene.export(size[0], size[1], options), 'Cubeon ' + id + '.png'); T.state('PNG downloaded.', 'success');
    });
    if (portrait) T.on('toolProfile', async function () { var blob = await scene.export(256, 256, {background: T.$('#toolTransparent').checked ? 'transparent' : T.value('toolBackground')}), reader = new FileReader(); reader.readAsDataURL(blob); await new Promise(function (resolve, reject) { reader.onload = resolve; reader.onerror = reject; }); CB.D.profile.picture = reader.result; await CB.save(); CB.renderAll(); T.state('Profile picture saved in Bench.', 'success'); });
    else T.on('toolSave', async function () { if (!generated) throw new Error('Choose a skin first.'); if (id === 'totem' || id === 'zombie') return T.savePack(await files(), T.value('toolName')); return window.Workspace.importSkin(new File([await window.TextureCodec.png(generated)], 'Cubeon ' + id + '.png', {type: 'image/png'})); });
    if (id === 'totem' || id === 'zombie') T.on('toolExport', async function () { return T.exportPack(await files()); });
    await redraw();
  }
  ['avatar', 'totem', 'thumbnail', 'wardrobe', 'zombie', 'skins'].forEach(function (id) { T.register(id, function () { return artwork(id); }); });
  function capePattern(primary, secondary, pattern) {
    var result = C.image(64, 32), a = C.rgb(primary), b = C.rgb(secondary);
    for (var y = 0; y < 16; y++) for (var x = 0; x < 10; x++) {
      var use = pattern === 'diagonal' ? (x + y) % 7 < 3 : pattern === 'checker' ? (Math.floor(x / 3) + Math.floor(y / 3)) % 2 : x === 0 || x === 9 || y === 0 || y === 15 || x >= 3 && x <= 6 && y >= 5 && y <= 10;
      var color = (use ? b : a).concat(255); result.data.set(color, ((y + 1) * 64 + x + 1) * 4); result.data.set(color, ((y + 1) * 64 + 12 + x) * 4);
    }
    for (var y = 1; y <= 16; y++) { result.data.set(a.concat(255), (y * 64) * 4); result.data.set(a.concat(255), (y * 64 + 11) * 4); }
    for (var x = 1; x <= 20; x++) result.data.set(a.concat(255), x * 4);
    return result;
  }
  async function cape(id) {
    var generated, scene, token = T.mount(id, T.row(T.field('Cloth', T.input('toolCloth', '#344d28', 'color')), T.field('Accent', T.input('toolAccent', '#a4d168', 'color'))) + T.field('Pattern', T.select('toolPattern', [['cube', 'Bench emblem'], ['diagonal', 'Diagonal'], ['checker', 'Checker']])) + T.field('Or preview a cape PNG', T.file('toolCapeFile', '.png,image/png'), 'Standard 64×32 cape layout') + T.edition(),
      'Custom cape PNGs need a compatible cape client or service to be worn. The elytra pack replaces the vanilla wing texture.', [['toolDownload', 'Download cape PNG'], ['toolExport', 'Download elytra pack'], ['toolSave', 'Open elytra in Bench']]);
    scene = new M.Scene(T.preview()); T.cleanup(function () { scene.dispose(); }); await scene.init();
    async function redraw() {
      var file = T.selectedFile('toolCapeFile'), next = file ? await M.readImage(file) : capePattern(T.value('toolCloth'), T.value('toolAccent'), T.value('toolPattern'));
      if (!T.current(token)) return; if (next.width !== 64 || next.height !== 32) throw new Error('Capes need a 64×32 Minecraft cape layout.'); generated = next; scene.cape(generated); T.$('#toolPreviewLabel').textContent = '64×32 cape layout';
    }
    T.watch(['toolCloth', 'toolAccent', 'toolPattern', 'toolCapeFile'], redraw);
    async function files() { var bytes = await T.imageBytes(generated); return T.pack({'assets/minecraft/textures/entity/elytra.png': bytes, 'assets/minecraft/textures/entity/equipment/wings/elytra.png': bytes}); }
    T.on('toolDownload', function () { return T.downloadImage(generated, 'Cubeon cape'); }); T.on('toolExport', async function () { return T.exportPack(await files()); }); T.on('toolSave', async function () { return T.savePack(await files(), T.value('toolName')); }); await redraw();
  }
  T.register('cape', function () { return cape('cape'); }); T.register('capes', function () { return cape('capes'); });
  T.register('names', function () {
    T.mount('names', T.field('Minecraft username', T.input('toolUsername', '', 'text', 'maxlength="16" autocomplete="off"')), 'This sends only the entered name to a public Minecraft profile lookup. A missing profile does not guarantee that Mojang permits registration of that name.', [['toolCheck', 'Check public profile']]);
    T.preview().innerHTML = CB.ic('user');
    T.on('toolCheck', async function () { var profile = await M.lookup(T.value('toolUsername')); T.results('<pre translate="no">' + CB.esc(profile.available ? 'No public profile found for ' + profile.name : profile.name + '\n' + profile.uuid) + '</pre>'); T.state(profile.available ? 'No public profile uses this name. Registration may still be restricted by Mojang.' : 'This name is used by a public Minecraft profile.', 'success'); });
  });
  T.register('heads', function () {
    var profile = null;
    T.mount('heads', T.field('Player name', T.input('toolUsername', 'Steve', 'text', 'maxlength="16"')) + T.field('Command format', T.select('toolCommandVersion', [['modern', 'Java 1.20.5 and newer'], ['legacy', 'Java 1.13–1.20.4']])), 'The name-based command lets Minecraft resolve the profile. Public lookup can also supply an embedded texture property.', [['toolCommand', 'Generate command'], ['toolCopy', 'Copy command'], ['toolProfileLookup', 'Look up profile']]);
    T.preview().innerHTML = CB.ic('user');
    function render() { var name = T.value('toolUsername'), command = C.headCommand(name, T.value('toolCommandVersion'), profile && profile.name.toLowerCase() === name.toLowerCase() && T.value('toolCommandVersion') === 'modern' ? profile.textureValue : null); T.results('<pre id="toolCommandText" translate="no" tabindex="0">' + CB.esc(command) + '</pre>'); T.state('Command generated for the selected Java version.', 'success'); return command; }
    T.on('toolCommand', render); T.on('toolCopy', async function () { await navigator.clipboard.writeText(render()); T.state('Command copied.', 'success'); });
    T.on('toolProfileLookup', async function () { profile = await M.lookup(T.value('toolUsername')); if (profile.available) throw new Error('No public profile was found.'); render(); T.state('Resolved ' + profile.name + ' · ' + profile.uuid, 'success'); }); render();
  });
  T.register('text', function () {
    T.mount('text', T.field('Your text', '<textarea id="toolText" maxlength="1000">Welcome to our world</textarea>') + T.row(T.field('Start color', T.input('toolColorStart', '#628b38', 'color')), T.field('End color', T.input('toolColorEnd', '#e9b15c', 'color'))) + T.check('toolBold', 'Bold', true) + T.check('toolItalic', 'Italic', false), 'Java JSON text supports the full gradient. Legacy MOTDs and Bedrock use Minecraft’s nearest 16 colors.', [['toolCopyJSON', 'Copy JSON text'], ['toolCopyMOTD', 'Copy MOTD'], ['toolDownloadText', 'Download text formats']]);
    var parts;
    function render() { parts = C.textComponents(T.value('toolText'), T.value('toolColorStart'), T.value('toolColorEnd'), T.$('#toolBold').checked, T.$('#toolItalic').checked); T.preview().innerHTML = '<div style="padding:30px;font-size:26px;line-height:1.5;overflow-wrap:anywhere" translate="no">' + parts.map(function (part) { return '<span style="color:' + part.color + ';font-weight:' + (part.bold ? 800 : 500) + ';font-style:' + (part.italic ? 'italic' : 'normal') + '">' + CB.esc(part.text) + '</span>'; }).join('') + '</div>'; T.results('<pre translate="no">' + CB.esc(JSON.stringify(parts)) + '</pre>'); }
    T.watch(['toolText', 'toolColorStart', 'toolColorEnd', 'toolBold', 'toolItalic'], render); T.on('toolCopyJSON', async function () { render(); await navigator.clipboard.writeText(JSON.stringify(parts)); T.state('JSON text copied.', 'success'); }); T.on('toolCopyMOTD', async function () { render(); await navigator.clipboard.writeText(C.legacyText(parts)); T.state('Legacy colored text copied.', 'success'); });
    T.on('toolDownloadText', function () { render(); window.BenchArchive.download(new Blob([JSON.stringify({json: parts, legacy: C.legacyText(parts), serverProperties: 'motd=' + C.legacyText(parts).replace(/§/g, '\\u00a7')}, null, 2)], {type: 'application/json'}), 'Cubeon text.json'); T.state('Text formats downloaded.', 'success'); }); render();
  });
  async function picks(id) {
    var day = new Date().toLocaleDateString('sv'), index = CB.hash(day) % defaults.length, left, right, scenes = [];
    T.mount(id, '', id === 'daily' ? 'A daily quiz using Minecraft’s nine bundled default skins. Your result stays on this device.' : 'Your comparisons and favorites stay in this workspace. These votes are not submitted to a community service.', []);
    T.preview().style.display = 'none'; T.$('#v-tools .tool-panel').hidden = true; T.$('#v-tools .tool-studio').style.gridTemplateColumns = '1fr';
    if (id === 'daily') {
      T.results('<div class="tool-stage" id="quizPreview" style="height:420px"></div><div class="tool-skin-options" id="quizChoices" style="margin-top:16px">' + defaults.map(function (name) { return '<button type="button" data-guess="' + name + '">' + name[0].toUpperCase() + name.slice(1) + '</button>'; }).join('') + '</div><p class="tool-output" id="quizStatus" role="status">Today’s default skin · ' + day + '</p>');
      var scene = new M.Scene(T.$('#quizPreview')); T.cleanup(function () { scene.dispose(); }); await scene.init(); scene.skin(await defaultSkin(defaults[index]), {mode: 'body', slim: defaults[index] === 'alex'});
      T.$('#quizChoices').onclick = function (event) { var button = event.target.closest('[data-guess]'); if (!button) return; var win = button.dataset.guess === defaults[index]; T.$('#quizStatus').textContent = win ? 'Correct! Today’s skin is ' + defaults[index] + '.' : 'That is ' + button.dataset.guess + '. Try another skin.'; if (win) { CB.D.set.skinQuiz = {day: day, correct: true}; CB.save(); } };
    } else {
      T.results('<div class="tool-compare"><div><div class="tool-stage" id="pickLeft"></div><button type="button" class="gb" id="voteLeft">Pick this skin</button></div><div><div class="tool-stage" id="pickRight"></div><button type="button" class="gb" id="voteRight">Pick this skin</button></div></div><p class="tool-output" id="pickStatus" role="status">Choose your favorite.</p>');
      scenes = [new M.Scene(T.$('#pickLeft')), new M.Scene(T.$('#pickRight'))]; T.cleanup(function () { scenes.forEach(function (scene) { scene.dispose(); }); }); await Promise.all(scenes.map(function (scene) { return scene.init(); }));
      var token = T.token();
      async function round() { left = Math.floor(Math.random() * defaults.length); do { right = Math.floor(Math.random() * defaults.length); } while (right === left); var images = await Promise.all([defaultSkin(defaults[left]), defaultSkin(defaults[right])]); if (!T.current(token)) return; scenes.forEach(function (scene, i) { scene.skin(images[i], {mode: 'body', slim: defaults[i ? right : left] === 'alex'}); }); }
      function vote(name) { CB.D.set.skinVotes = CB.D.set.skinVotes || {}; CB.D.set.skinVotes[name] = (CB.D.set.skinVotes[name] || 0) + 1; CB.save(); T.$('#pickStatus').textContent = 'Picked ' + name + ' · ' + CB.D.set.skinVotes[name] + ' local picks.'; round(); }
      T.$('#voteLeft').onclick = function () { vote(defaults[left]); }; T.$('#voteRight').onclick = function () { vote(defaults[right]); }; await round();
    }
  }
  T.register('battle', function () { return picks('battle'); }); T.register('daily', function () { return picks('daily'); });
})();
