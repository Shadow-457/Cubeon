(function () {
  'use strict';
  var MT = window.MinecraftTextures;

  function Preview(getDoc) {
    this.getDoc = getDoc;
    this.world = document.getElementById('pvW');
    this.stage = document.getElementById('pvS');
    this.host = document.getElementById('edPv');
    this.title = document.getElementById('pvT');
    this.materials = [];
    this.rx = -22; this.ry = -35; this.zoom = 1; this.auto = true;
    this.width = 240; this.height = 240; this.token = 0; this.raf = 0; this.pointer = null;
    var self = this;
    this.stage.addEventListener('pointerdown', function (e) {
      if (e.button > 0) return;
      self.pointer = {x: e.clientX, y: e.clientY};
      try { self.stage.setPointerCapture(e.pointerId); } catch (_) {}
      self.host.classList.add('grab');
    });
    this.stage.addEventListener('pointermove', function (e) {
      if (!self.pointer) return;
      self.ry += (e.clientX - self.pointer.x) * .6;
      self.rx = Math.max(-89, Math.min(89, self.rx - (e.clientY - self.pointer.y) * .6));
      self.pointer = {x: e.clientX, y: e.clientY}; self.transform();
    });
    function end() { self.pointer = null; self.host.classList.remove('grab'); }
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function (name) { self.stage.addEventListener(name, end); });
    this.stage.addEventListener('wheel', function (e) {
      e.preventDefault();
      self.zoom = Math.max(.35, Math.min(3, self.zoom * (e.deltaY < 0 ? 1.08 : .92))); self.transform();
    }, {passive: false});
    document.getElementById('pvAuto').addEventListener('click', function () {
      self.auto = !self.auto; self.syncAuto();
    });
    document.getElementById('pvReset').addEventListener('click', function () { self.reset(); });
    if (window.ResizeObserver) new ResizeObserver(function () { self.transform(); }).observe(this.stage);
  }

  Preview.prototype.syncAuto = function () {
    document.getElementById('pvAuto').textContent = 'Auto-rotate: ' + (this.auto ? 'on' : 'off');
  };
  Preview.prototype.reset = function () { this.rx = -22; this.ry = -35; this.zoom = 1; this.transform(); };
  Preview.prototype.stop = function () {
    this.token++; cancelAnimationFrame(this.raf); this.raf = 0;
    this.pointer = null; this.host.classList.remove('grab');
  };
  Preview.prototype.transform = function () {
    var fit = Math.max(.1, Math.min(1, (this.stage.clientWidth - 56) / this.width, (this.stage.clientHeight - 164) / this.height));
    this.world.style.transform = 'scale(' + (fit * this.zoom) + ') rotateX(' + this.rx + 'deg) rotateY(' + this.ry + 'deg)';
    document.getElementById('pvShadow').style.top = 'calc(50% + ' + (this.height * fit * this.zoom * .42) + 'px)';
  };

  function tint(canvas, color) {
    if (!color) return;
    var ctx = canvas.getContext('2d'), data = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var rgb = [1, 3, 5].map(function (i) { return parseInt(color.slice(i, i + 2), 16) / 255; });
    for (var i = 0; i < data.data.length; i += 4) {
      data.data[i] *= rgb[0]; data.data[i + 1] *= rgb[1]; data.data[i + 2] *= rgb[2];
    }
    ctx.putImageData(data, 0, 0);
  }

  function crop(doc, time, full, canvas) {
    var f = full ? {x: 0, y: 0, w: doc.w, h: doc.h, index: 0} : MT.frame(doc.e, time, doc.w, doc.h);
    var cv = canvas || document.createElement('canvas');
    if (cv.width !== f.w || cv.height !== f.h) {cv.width = f.w; cv.height = f.h;}
    var ctx = cv.getContext('2d'); ctx.clearRect(0, 0, cv.width, cv.height); ctx.imageSmoothingEnabled = false;
    window.TextureAnimation.paintFrame(ctx, doc.cv, f, 0, 0, cv.width, cv.height);
    return cv;
  }

  function updateMaterial(m, time) {
    var frame = m.full ? {index: 0} : MT.frame(m.doc.e, time, m.doc.w, m.doc.h);
    var overlayFrame = m.overlay ? MT.frame(m.overlay.e, time, m.overlay.w, m.overlay.h) : {index: 0};
    var key = [m.doc.version, frame.index, frame.step, Math.round((frame.mix || 0) * 20), m.overlay && m.overlay.version, overlayFrame.index, overlayFrame.step, Math.round((overlayFrame.mix || 0) * 20)].join(':');
    if (key === m.key) return;
    m.key = key; m.canvas = crop(m.doc, time, m.full, m.canvas); if(m.doc.viewTint!==false)tint(m.canvas, m.tint);
    if (m.overlay) {
      var overlay = m.overlayCanvas = crop(m.overlay, time, false, m.overlayCanvas); if(m.overlay.viewTint!==false)tint(overlay, '#91bd59');
      m.canvas.getContext('2d').drawImage(overlay, 0, 0, m.canvas.width, m.canvas.height);
    }
    m.w = m.canvas.width; m.h = m.canvas.height;
    if (m.animated) m.surfaces.forEach(function (surface) {paintSurface(m, surface);});
    else {
      m.url = m.canvas.toDataURL();
      m.elements.forEach(function (el) { el.style.backgroundImage = 'url("' + m.url + '")'; });
    }
  }
  function paintSurface(material, surface) {
    var cv = surface.canvas, ctx = cv.getContext('2d'), u = surface.uv, scale = material.w / 64;
    ctx.clearRect(0, 0, cv.width, cv.height); ctx.imageSmoothingEnabled = false;
    if (u) ctx.drawImage(material.canvas, u[0]*scale, u[1]*scale, u[2]*scale, u[3]*scale, 0, 0, cv.width, cv.height);
    else ctx.drawImage(material.canvas, 0, 0, cv.width, cv.height);
  }

  Preview.prototype.material = async function (spec, current, full) {
    var doc = spec.id === current.id ? current : await this.getDoc(spec.id);
    var overlay = spec.overlay ? await this.getDoc(spec.overlay) : null;
    var m = {doc: doc, overlay: overlay, tint: spec.tint, full: full, elements: [], surfaces: [], key: null,
      animated: !full && !!(doc.e.animation || overlay && overlay.e.animation)};
    updateMaterial(m, 0); return m;
  };

  Preview.prototype.box = function (cx, cy, cz, w, h, depth, materials, uv, only, angle) {
    var specs = {
      front: [w, h, 'translateZ(' + depth / 2 + 'px)'],
      back: [w, h, 'rotateY(180deg) translateZ(' + depth / 2 + 'px)'],
      right: [depth, h, 'rotateY(90deg) translateZ(' + w / 2 + 'px)'],
      left: [depth, h, 'rotateY(-90deg) translateZ(' + w / 2 + 'px)'],
      top: [w, depth, 'rotateX(90deg) translateZ(' + h / 2 + 'px)'],
      bottom: [w, depth, 'rotateX(-90deg) translateZ(' + h / 2 + 'px)']
    }, self = this;
    Object.keys(specs).forEach(function (name) {
      if (only && !only.includes(name)) return;
      var s = specs[name], m = materials[name], u = uv && uv[name];
      var el = document.createElement('div'); el.className = 'pv-face pv-face-' + name;
      el.dataset.texture = m.doc.e.src;
      el.style.width = s[0] + 'px'; el.style.height = s[1] + 'px';
      el.style.left = -s[0] / 2 + 'px'; el.style.top = -s[1] / 2 + 'px';
      if (m.animated) {
        var canvas = document.createElement('canvas'), scale = m.w / 64;
        canvas.className = 'pv-texture'; canvas.setAttribute('aria-hidden', 'true');
        canvas.width = u ? u[2]*scale : m.w; canvas.height = u ? u[3]*scale : m.h;
        var surface = {canvas:canvas, uv:u};m.surfaces.push(surface);paintSurface(m, surface);el.appendChild(canvas);
      } else el.style.backgroundImage = 'url("' + m.url + '")';
      if (u) {
        var scale = m.w / 64, kx = s[0] / (u[2] * scale), ky = s[1] / (u[3] * scale);
        el.style.backgroundSize = m.w * kx + 'px ' + m.h * ky + 'px';
        el.style.backgroundPosition = -u[0] * scale * kx + 'px ' + -u[1] * scale * ky + 'px';
      } else el.style.backgroundSize = '100% 100%';
      el.style.transform = (angle ? 'rotateY(' + angle + 'deg) ' : '') + 'translate3d(' + cx + 'px,' + cy + 'px,' + cz + 'px) ' + s[2];
      m.elements.push(el); self.world.appendChild(el);
    });
  };

  function sameMaterial(m) { return {front: m, back: m, left: m, right: m, top: m, bottom: m}; }
  function skinUV(x, y, w, h, depth) {
    return {top: [x + depth, y, w, depth], bottom: [x + depth + w, y, w, depth],
      left: [x, y + depth, depth, h], front: [x + depth, y + depth, w, h],
      right: [x + depth + w, y + depth, depth, h], back: [x + 2 * depth + w, y + depth, w, h]};
  }

  Preview.prototype.skin = function (m, slim) {
    var k = 8, arm = slim ? 3 : 4, armX = 4 + arm / 2, self = this;
    var parts = [
      [0, -12, 8, 8, 8, 0, 0, 32, 0, 1],
      [0, -2, 8, 12, 4, 16, 16, 16, 32, .5],
      [-armX, -2, arm, 12, 4, 40, 16, 40, 32, .5],
      [armX, -2, arm, 12, 4, 32, 48, 48, 48, .5],
      [-2, 10, 4, 12, 4, 0, 16, 0, 32, .5],
      [2, 10, 4, 12, 4, 16, 48, 0, 48, .5]
    ];
    parts.forEach(function (p) {
      self.box(p[0] * k, p[1] * k, 0, p[2] * k, p[3] * k, p[4] * k, sameMaterial(m), skinUV(p[5], p[6], p[2], p[3], p[4]));
      self.box(p[0] * k, p[1] * k, 0, (p[2] + p[9]) * k, (p[3] + p[9]) * k, (p[4] + p[9]) * k,
        sameMaterial(m), skinUV(p[7], p[8], p[2], p[3], p[4]));
    });
    this.width = 220; this.height = 300;
  };

  Preview.prototype.itemEdges = function (m, w, h, depth) {
    var cv = m.canvas;
    if (cv.width * cv.height > 4096) return;
    var data = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
    var pw = w / cv.width, ph = h / cv.height, self = this;
    function opaque(x, y) { return x >= 0 && y >= 0 && x < cv.width && y < cv.height && data[(y * cv.width + x) * 4 + 3] > 0; }
    for (var y = 0; y < cv.height; y++) for (var x = 0; x < cv.width; x++) {
      if (!opaque(x, y)) continue;
      var i = (y * cv.width + x) * 4, color = 'rgba(' + data[i] + ',' + data[i + 1] + ',' + data[i + 2] + ',' + data[i + 3] / 255 + ')';
      var cx = (x + .5) * pw - w / 2, cy = (y + .5) * ph - h / 2;
      [[-1, 0, 'left', depth, ph, cx - pw / 2, cy, 'rotateY(-90deg)'],
       [1, 0, 'right', depth, ph, cx + pw / 2, cy, 'rotateY(90deg)'],
       [0, -1, 'top', pw, depth, cx, cy - ph / 2, 'rotateX(90deg)'],
       [0, 1, 'bottom', pw, depth, cx, cy + ph / 2, 'rotateX(-90deg)']].forEach(function (s) {
        if (opaque(x + s[0], y + s[1])) return;
        var el = document.createElement('div'); el.className = 'pv-face pv-face-' + s[2] + ' pv-item-edge';
        el.style.cssText = 'width:' + s[3] + 'px;height:' + s[4] + 'px;left:' + -s[3] / 2 + 'px;top:' + -s[4] / 2 + 'px;background:' + color + ';transform:translate3d(' + s[5] + 'px,' + s[6] + 'px,0) ' + s[7];
        self.world.appendChild(el);
      });
    }
  };

  Preview.prototype.build = async function (doc, skinProject, calm, faceModel) {
    this.stop(); var token = this.token, self = this;
    this.world.innerHTML = ''; this.materials = []; this.title.textContent = 'Loading preview…';
    if (!doc) { this.title.textContent = 'Open a texture to preview it'; return; }
    if (calm) this.auto = false;
    this.syncAuto();
    var player = skinProject || /^entity\/player\/(wide|slim)\//.test(doc.e.textureId || doc.e.id);
    try {
      if (player) {
        var skinMat = await this.material({id: doc.id}, doc, true);
        if (token !== this.token) return;
        this.materials = [skinMat]; this.skin(skinMat, doc.e.id.includes('/slim/'));
      } else if (doc.e.cat === 'block') {
        var name = (doc.e.textureId || doc.e.id).slice(6);
        var cross = /(?:_sapling|_flower|_tulip|_orchid|_mushroom|_fern)$/.test(name) || /^(short_grass|tall_grass_(top|bottom)|fern|dead_bush|dandelion|poppy|allium|azure_bluet|cornflower|lily_of_the_valley|wither_rose|sugar_cane|fire_[01]|soul_fire_[01])$/.test(name);
        var plane = /(?:_door_(top|bottom)|_trapdoor)$/.test(name) || /^(ladder|vine|lily_pad|rail.*|.*_rail.*)$/.test(name);
        if (cross || plane) {
          var flat = await this.material({id: doc.id}, doc);
          if (token !== this.token) return;
          this.materials = [flat];
          if (/^(lily_pad|rail.*|.*_rail.*)$/.test(name)) this.box(0, 60, 0, 170, 0, 170, sameMaterial(flat), null, ['top', 'bottom']);
          else {
            this.box(0, 0, 0, 170, 170, 0, sameMaterial(flat), null, ['front', 'back'], cross ? 45 : 0);
            if (cross) this.box(0, 0, 0, 170, 170, 0, sameMaterial(flat), null, ['front', 'back'], -45);
          }
        } else {
          var model = faceModel || MT.blockModel(doc.e), names = Object.keys(model.faces), materials = {}, cache = {};
          var loaded = await Promise.all(names.map(function (n) {
            var spec = model.faces[n], key = JSON.stringify(spec);
            if (!cache[key]) cache[key] = self.material(spec, doc);
            return cache[key];
          }));
          if (token !== this.token) return;
          names.forEach(function (n, i) { materials[n] = loaded[i]; });
          this.materials = Array.from(new Set(loaded));
          this.box(0, 0, 0, 170 * model.width, 170 * model.height, 170 * model.width, materials);
        }
        this.width = 270; this.height = 270;
      } else {
        var m = await this.material({id: doc.id}, doc);
        if (token !== this.token) return;
        this.materials = [m];
        var ratio = Math.min(170 / m.w, 170 / m.h), w = m.w * ratio, h = m.h * ratio;
        var depth = doc.e.cat === 'item' ? 6 : 1;
        this.box(0, 0, 0, w, h, depth, sameMaterial(m), null, ['front', 'back']);
        if (doc.e.cat === 'item') this.itemEdges(m, w, h, depth);
        this.width = 230; this.height = 230;
      }
      this.title.textContent = doc.e.n;
      this.title.title = doc.e.src;
      this.transform();
      var started = performance.now(), previous = started;
      function tick(now) {
        if (token !== self.token || !self.host.classList.contains('on')) { self.raf = 0; return; }
        if (self.auto && !self.pointer) self.ry += Math.min(50, now - previous) * .027;
        previous = now;
        self.materials.forEach(function (material) { updateMaterial(material, now - started); });
        self.transform(); self.raf = requestAnimationFrame(tick);
      }
      this.raf = requestAnimationFrame(tick);
    } catch (err) {
      if (token === this.token) this.title.textContent = err.message;
    }
  };

  window.MinecraftPreview = Preview;
})();
