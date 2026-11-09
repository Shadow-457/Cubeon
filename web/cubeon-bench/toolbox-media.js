(function () {
  'use strict';
  var threePromise;
  function three() { return threePromise || (threePromise = import(new URL('vendor/three.module.min.js', document.baseURI).href)); }
  function canvas(source) {
    var cv = document.createElement('canvas'); cv.width = source.width; cv.height = source.height; cv.getContext('2d').putImageData(source, 0, 0); return cv;
  }
  async function readImage(file) {
    if (!file || file.size > 16777216) throw new Error('Choose an image smaller than 16 MB.');
    var bitmap = await createImageBitmap(file);
    try {
      if (bitmap.width * bitmap.height > 16777216) throw new Error('Images may contain at most 16 million pixels.');
      var cv = document.createElement('canvas'); cv.width = bitmap.width; cv.height = bitmap.height; cv.getContext('2d').drawImage(bitmap, 0, 0); return cv.getContext('2d').getImageData(0, 0, cv.width, cv.height);
    } finally { bitmap.close(); }
  }
  async function vanilla(id) {
    var source = await window.MinecraftTextures.load(id), cv = document.createElement('canvas'); cv.width = source.width; cv.height = source.height; cv.getContext('2d').drawImage(source, 0, 0); return cv.getContext('2d').getImageData(0, 0, cv.width, cv.height);
  }
  async function projectSkin(project) {
    return project && project.edits && project.edits.skin ? window.TextureCodec.decode(project.edits.skin, project) : vanilla('entity/player/wide/steve');
  }
  function fit(source, width, height, smooth) {
    var cv = document.createElement('canvas'); cv.width = width; cv.height = height;
    var ctx = cv.getContext('2d'); ctx.imageSmoothingEnabled = !!smooth; ctx.drawImage(canvas(source), 0, 0, width, height); return ctx.getImageData(0, 0, width, height);
  }
  function paintPreview(host, source) {
    var cv = host.querySelector('canvas.tool-pixels');
    if (!cv) { host.innerHTML = ''; cv = document.createElement('canvas'); cv.className = 'tool-pixels'; host.appendChild(cv); }
    cv.width = source.width; cv.height = source.height; cv.getContext('2d').putImageData(source, 0, 0); cv.setAttribute('aria-label', 'Generated artwork preview');
    return cv;
  }
  function Scene(host) { this.host = host; this.resources = []; this.disposed = false; this.yaw = -25; this.pitch = 8; this.mode = 'body'; this.pointer = null; }
  Scene.prototype.init = async function () {
    var T = this.T = await three(); if (this.disposed) return this;
    this.renderer = new T.WebGLRenderer({alpha: true, antialias: true, preserveDrawingBuffer: true});
    this.renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1)); this.renderer.outputColorSpace = T.SRGBColorSpace;
    this.renderer.domElement.className = 'tool-scene'; this.renderer.domElement.setAttribute('aria-label', 'Interactive 3D preview. Drag to turn the model.');
    this.host.replaceChildren(this.renderer.domElement); this.scene = new T.Scene(); this.group = new T.Group(); this.scene.add(this.group);
    this.camera = new T.PerspectiveCamera(35, 1, .1, 1000);
    this.scene.add(new T.HemisphereLight(0xffffff, 0x7b8b69, 2.1)); var light = new T.DirectionalLight(0xffffff, 2.5); light.position.set(-20, 45, 35); this.scene.add(light);
    var self = this, el = this.renderer.domElement;
    el.onpointerdown = function (event) { if (event.button) return; self.pointer = [event.clientX, event.clientY]; el.setPointerCapture(event.pointerId); };
    el.onpointermove = function (event) { if (!self.pointer) return; self.yaw += (event.clientX - self.pointer[0]) * .6; self.pitch = Math.max(-75, Math.min(75, self.pitch + (event.clientY - self.pointer[1]) * .4)); self.pointer = [event.clientX, event.clientY]; self.render(); };
    el.onpointerup = el.onpointercancel = function () { self.pointer = null; };
    this.observer = new ResizeObserver(function () { self.resize(); }); this.observer.observe(this.host); this.resize(); return this;
  };
  Scene.prototype.resize = function () { if (!this.renderer || this.disposed) return; var w = Math.max(100, this.host.clientWidth), h = Math.max(180, this.host.clientHeight); this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); this.render(); };
  Scene.prototype.texture = function (image, uv) {
    var T = this.T, source = canvas(image), cv = document.createElement('canvas');
    uv = uv || [0, 0, image.width, image.height]; cv.width = Math.max(1, uv[2]); cv.height = Math.max(1, uv[3]);
    cv.getContext('2d').drawImage(source, uv[0], uv[1], uv[2], uv[3], 0, 0, cv.width, cv.height);
    var texture = new T.CanvasTexture(cv); texture.magFilter = T.NearestFilter; texture.minFilter = T.NearestFilter; texture.colorSpace = T.SRGBColorSpace; this.resources.push(texture); return texture;
  };
  Scene.prototype.box = function (x, y, z, w, h, d, image, ox, oy, overlay) {
    var T = this.T, u = ox || 0, v = oy || 0;
    var faces = [[u + d + w, v + d, d, h], [u, v + d, d, h], [u + d, v, w, d], [u + d + w, v, w, d], [u + d, v + d, w, h], [u + 2 * d + w, v + d, w, h]];
    var self = this, materials = faces.map(function (uv) { var material = new T.MeshLambertMaterial({map: self.texture(image, uv), transparent: !!overlay, alphaTest: .05, side: T.DoubleSide}); self.resources.push(material); return material; });
    var geometry = new T.BoxGeometry(w + (overlay ? .4 : 0), h + (overlay ? .4 : 0), d + (overlay ? .4 : 0)), mesh = new T.Mesh(geometry, materials); this.resources.push(geometry); mesh.position.set(x, y, z); this.group.add(mesh); return mesh;
  };
  Scene.prototype.clear = function () { if (!this.group) return; this.group.clear(); this.resources.forEach(function (item) { item.dispose(); }); this.resources = []; };
  Scene.prototype.skin = function (source, options) {
    options = options || {}; this.clear(); var skin = window.BenchToolsCore.normalizeSkin(source), arm = options.slim ? 3 : 4, ax = 4 + arm / 2, self = this;
    this.mode = options.mode || 'body'; this.focus = this.mode === 'head' ? 28 : this.mode === 'bust' ? 24 : 17; this.distance = this.mode === 'head' ? 25 : this.mode === 'bust' ? 43 : 65;
    var parts = [[0, 28, 8, 8, 8, 0, 0, 32, 0], [0, 18, 8, 12, 4, 16, 16, 16, 32], [-ax, 18, arm, 12, 4, 40, 16, 40, 32], [ax, 18, arm, 12, 4, 32, 48, 48, 48], [-2, 6, 4, 12, 4, 0, 16, 0, 32], [2, 6, 4, 12, 4, 16, 48, 0, 48]];
    parts.forEach(function (part, index) {
      if (self.mode === 'head' && index || self.mode === 'bust' && index > 3) return;
      var mesh = self.box(part[0], part[1], 0, part[2], part[3], part[4], skin, part[5], part[6], false);
      var outer = options.hat !== false ? self.box(part[0], part[1], 0, part[2], part[3], part[4], skin, part[7], part[8], true) : null;
      var angle = options.pose === 'wave' && index === 3 ? -2.4 : options.pose === 'walk' && index > 1 ? (index % 2 ? .55 : -.55) : 0;
      if (angle) { var pivot = new self.T.Group(); pivot.position.set(part[0], part[1] + part[3] / 2, 0); self.group.add(pivot); [mesh, outer].filter(Boolean).forEach(function (item) { self.group.remove(item); pivot.add(item); item.position.set(0, -part[3] / 2, 0); }); if (options.pose === 'wave') pivot.rotation.z = angle; else pivot.rotation.x = angle; }
    });
    this.render();
  };
  Scene.prototype.cape = function (source) { this.clear(); this.mode = 'cape'; this.focus = 8; this.distance = 39; this.box(0, 8, 0, 10, 16, 1, source, 0, 0, false); this.render(); };
  Scene.prototype.block = function (source) {
    this.clear(); var T = this.T, texture = this.texture(source), geometry = new T.BoxGeometry(16, 16, 16), material = new T.MeshLambertMaterial({map: texture, transparent: true, alphaTest: .05}); this.resources.push(geometry, material); this.group.add(new T.Mesh(geometry, material)); this.focus = 0; this.distance = 45; this.mode = 'block'; this.render();
  };
  Scene.prototype.model = function (model, source) {
    this.clear(); var T = this.T, self = this, texture = this.texture(source), elements = model.elements;
    if (!elements && ['minecraft:block/cube_all', 'block/cube_all', 'minecraft:block/cube', 'block/cube'].includes(model.parent)) elements = [{from: [0, 0, 0], to: [16, 16, 16], faces: {east: {}, west: {}, up: {}, down: {}, south: {}, north: {}}}];
    if (!Array.isArray(elements) || elements.length > 128) throw new Error('Preview a model with up to 128 explicit elements, or the cube_all parent.');
    elements.forEach(function (element) {
      if (!Array.isArray(element.from) || !Array.isArray(element.to) || element.from.length !== 3 || element.to.length !== 3 || element.from.concat(element.to).some(function (n) { return !Number.isFinite(n) || n < -16 || n > 32; }) || element.to.some(function (n, i) { return n <= element.from[i]; })) throw new Error('Model elements need valid from/to coordinates between −16 and 32.');
      var dimensions = element.to.map(function (n, i) { return n - element.from[i]; }), geometry = new T.BoxGeometry(dimensions[0], dimensions[1], dimensions[2]); self.resources.push(geometry);
      var material = ['east', 'west', 'up', 'down', 'south', 'north'].map(function (name) {
        var face = (element.faces || {})[name], map = texture;
        if (face && face.uv) { var uv = face.uv; if (uv.length !== 4 || uv.some(function (n) { return !Number.isFinite(n); })) throw new Error('Invalid model UV coordinates.'); map = self.texture(source, [uv[0] / 16 * source.width, uv[1] / 16 * source.height, (uv[2] - uv[0]) / 16 * source.width, (uv[3] - uv[1]) / 16 * source.height]); }
        var result = new T.MeshLambertMaterial({map: map, transparent: true, opacity: face ? 1 : 0, alphaTest: .05}); self.resources.push(result); return result;
      });
      var mesh = new T.Mesh(geometry, material); mesh.position.set.apply(mesh.position, element.from.map(function (n, i) { return (n + element.to[i]) / 2 - 8; }));
      if (element.rotation) { var rotation = element.rotation; if (!['x', 'y', 'z'].includes(rotation.axis) || ![-45, -22.5, 0, 22.5, 45].includes(rotation.angle) || !rotation.origin || rotation.origin.length !== 3) throw new Error('Use Minecraft’s supported model rotation angles and an origin.'); var pivot = new T.Group(); pivot.position.set.apply(pivot.position, rotation.origin.map(function (n) { return n - 8; })); mesh.position.sub(pivot.position); pivot.add(mesh); pivot.rotation[rotation.axis] = rotation.angle * Math.PI / 180; self.group.add(pivot); } else self.group.add(mesh);
    });
    this.focus = 0; this.distance = 55; this.mode = 'model'; this.render();
  };
  Scene.prototype.render = function () {
    if (!this.renderer || this.disposed) return;
    var yaw = this.yaw * Math.PI / 180, pitch = this.pitch * Math.PI / 180, distance = this.distance || 65, focus = this.focus || 0;
    this.camera.position.set(Math.sin(yaw) * Math.cos(pitch) * distance, focus + Math.sin(pitch) * distance, Math.cos(yaw) * Math.cos(pitch) * distance); this.camera.lookAt(0, focus, 0); this.renderer.render(this.scene, this.camera);
  };
  Scene.prototype.export = function (width, height, options) {
    options = options || {}; var size = this.renderer.getSize(new this.T.Vector2()), ratio = this.renderer.getPixelRatio();
    this.renderer.setPixelRatio(1); this.renderer.setSize(width, height, false); this.camera.aspect = width / height; this.camera.updateProjectionMatrix(); this.render();
    var cv = document.createElement('canvas'); cv.width = width; cv.height = height; var ctx = cv.getContext('2d');
    if (options.background && options.background !== 'transparent') { ctx.fillStyle = options.background; ctx.fillRect(0, 0, width, height); }
    if (options.image) ctx.drawImage(canvas(options.image), 0, 0, width, height);
    ctx.drawImage(this.renderer.domElement, 0, 0);
    if (options.title) {
      ctx.font = '900 ' + Math.round(width / 11) + 'px Inter, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'bottom'; ctx.lineJoin = 'round'; ctx.lineWidth = width / 100;
      ctx.strokeStyle = '#162010'; ctx.fillStyle = '#f4f9ed'; ctx.strokeText(options.title, width / 2, height - height / 14, width * .94); ctx.fillText(options.title, width / 2, height - height / 14, width * .94);
    }
    this.renderer.setPixelRatio(ratio); this.renderer.setSize(size.x, size.y, false); this.camera.aspect = size.x / size.y; this.camera.updateProjectionMatrix(); this.render();
    return new Promise(function (resolve, reject) { cv.toBlob(function (blob) { blob ? resolve(blob) : reject(new Error('The 3D image could not be exported.')); }, 'image/png'); });
  };
  Scene.prototype.dispose = function () { this.disposed = true; if (this.observer) this.observer.disconnect(); this.clear(); if (this.renderer) { this.renderer.dispose(); this.renderer.forceContextLoss(); } };
  async function panorama(source, size) {
    var T = await three(), scene = new T.Scene(), texture = new T.CanvasTexture(canvas(source)); texture.colorSpace = T.SRGBColorSpace; texture.wrapS = T.RepeatWrapping;
    var geometry = new T.SphereGeometry(100, 48, 32), material = new T.MeshBasicMaterial({map: texture, side: T.BackSide}), sphere = new T.Mesh(geometry, material); scene.add(sphere);
    var renderer = new T.WebGLRenderer({preserveDrawingBuffer: true}); renderer.outputColorSpace = T.SRGBColorSpace; renderer.setSize(size, size); var camera = new T.PerspectiveCamera(90, 1, .1, 200);
    var directions = [[0, 0, 1], [1, 0, 0], [0, 0, -1], [-1, 0, 0], [0, 1, 0], [0, -1, 0]], frames = [];
    try {
      for (var i = 0; i < directions.length; i++) {
        camera.up.set(0, i === 4 || i === 5 ? 0 : 1, i === 4 ? -1 : i === 5 ? 1 : 0); camera.lookAt(new T.Vector3().fromArray(directions[i])); renderer.render(scene, camera);
        var cv = document.createElement('canvas'); cv.width = cv.height = size; cv.getContext('2d').drawImage(renderer.domElement, 0, 0); frames.push(cv.getContext('2d').getImageData(0, 0, size, size));
      }
    } finally { texture.dispose(); geometry.dispose(); material.dispose(); renderer.dispose(); renderer.forceContextLoss(); }
    return frames;
  }
  async function encodeAudio(input) {
    if (!input || input.size > 33554432) throw new Error('Choose an audio file smaller than 32 MB.');
    var context = new AudioContext({sampleRate: 44100}), buffer;
    try { buffer = await context.decodeAudioData(await input.arrayBuffer()); } finally { await context.close(); }
    if (buffer.duration > 180) throw new Error('Audio clips are limited to three minutes. Trim the song or recording first.');
    var channels = Array.from({length: Math.min(buffer.numberOfChannels, 2)}, function (_, i) { return new Float32Array(buffer.getChannelData(i)); });
    return new Promise(function (resolve, reject) {
      var worker = new Worker(new URL('vorbis-worker.js', document.baseURI)), timeout = setTimeout(function () { worker.terminate(); reject(new Error('Audio encoding took too long. Try a shorter clip.')); }, 90000);
      worker.onerror = function () { clearTimeout(timeout); worker.terminate(); reject(new Error('The offline audio encoder could not load. Open Bench over HTTPS or localhost.')); };
      worker.onmessage = function (event) { clearTimeout(timeout); worker.terminate(); if (event.data.error) reject(new Error(event.data.error)); else resolve(event.data.blob); };
      worker.postMessage({sampleRate: buffer.sampleRate, channels: channels}, channels.map(function (channel) { return channel.buffer; }));
    });
  }
  async function lookup(name) {
    if (!/^[a-zA-Z0-9_]{1,16}$/.test(name)) throw new Error('Enter a Minecraft username with 1–16 letters, numbers or underscores.');
    var response;
    try { response = await fetch('https://api.ashcon.app/mojang/v2/user/' + encodeURIComponent(name), {signal: AbortSignal.timeout(12000)}); }
    catch (_) { throw new Error('Player lookup needs an internet connection and a reachable public profile service. You can import a skin PNG instead.'); }
    if (response.status === 404) return {available: true, name: name};
    if (!response.ok) throw new Error('The public profile service is busy. Try again or import a PNG.');
    var result = await response.json();
    if (!result.uuid || !result.username) throw new Error('The profile service returned an incomplete player profile.');
    var image = result.textures && result.textures.skin && result.textures.skin.data, skin = null;
    if (image) { if (!/^[a-zA-Z0-9+/=]+$/.test(image) || image.length > 1048576) throw new Error('The profile image is invalid.'); var bytes = Uint8Array.from(atob(image), function (c) { return c.charCodeAt(0); }); skin = window.BenchToolsCore.normalizeSkin(await readImage(new Blob([bytes], {type: 'image/png'}))); }
    return {available: false, name: result.username, uuid: result.uuid, skin: skin, slim: !!(result.textures && result.textures.slim), textureValue: result.textures && result.textures.raw && result.textures.raw.value};
  }
  window.ToolboxMedia = {Scene: Scene, readImage: readImage, vanilla: vanilla, projectSkin: projectSkin, fit: fit, paintPreview: paintPreview, canvas: canvas, panorama: panorama, encodeAudio: encodeAudio, lookup: lookup};
})();
