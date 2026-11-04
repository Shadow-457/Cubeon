(function () {
  'use strict';
  function clamp(value, min, max) { return Math.min(max, Math.max(min, value)); }
  function rgb(hex) { return [1, 3, 5].map(function (offset) { return parseInt(hex.slice(offset, offset + 2), 16); }); }
  function hsvToRGB(h, s, v) {
    var chroma = v * s, x = chroma * (1 - Math.abs(h / 60 % 2 - 1)), m = v - chroma;
    var sector = Math.floor(h / 60) % 6, components = [[chroma,x,0],[x,chroma,0],[0,chroma,x],[0,x,chroma],[x,0,chroma],[chroma,0,x]][sector];
    return components.map(function (c) { return Math.round((c + m) * 255); });
  }
  function rgbToHSV(components, previousHue) {
    var r = components[0] / 255, g = components[1] / 255, b = components[2] / 255;
    var max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min, h = previousHue;
    if (delta) {
      h = max === r ? 60 * ((g - b) / delta % 6) : max === g ? 60 * ((b - r) / delta + 2) : 60 * ((r - g) / delta + 4);
      h = (h + 360) % 360;
    }
    return {h: h, s: max ? delta / max : 0, v: max};
  }
  function hex(components) { return '#' + components.map(function (c) { return c.toString(16).padStart(2, '0'); }).join(''); }

  function ColorChooser(options) {
    this.options = options; this.h = 0; this.s = 0; this.v = 1; this.alpha = 100; this.hex = '';
    var self = this, panel = document.createElement('div');
    panel.id = 'colorChooser'; panel.className = 'color-chooser'; panel.hidden = true;
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'Custom color chooser');
    panel.innerHTML = '<div class="color-chooser-header"><span>Custom color</span><button class="task-close" id="colorClose" type="button" aria-label="Close color chooser">×</button></div>' +
      '<div class="color-sv" id="colorSV" tabindex="0" role="slider" aria-label="Saturation and brightness" aria-valuemin="0" aria-valuemax="100" aria-describedby="colorKeyboard"><span class="color-cursor" id="colorCursor"></span></div>' +
      '<span class="visually-hidden" id="colorKeyboard">Use left and right arrows for saturation, and up and down arrows for brightness. Hold Shift for larger steps.</span>' +
      '<label class="color-slider-label" for="colorHue">Hue <output id="colorHueValue" for="colorHue"></output></label><input class="color-range" id="colorHue" type="range" min="0" max="359" step="1" aria-label="Hue">' +
      '<label class="color-slider-label" for="colorAlpha">Opacity <output id="colorAlphaValue" for="colorAlpha"></output></label><input class="color-range" id="colorAlpha" type="range" min="0" max="100" step="1" aria-label="Color opacity">' +
      '<div class="color-preview-row"><div class="color-preview-checker"><div id="colorPreview"></div></div><input class="pack-input" id="colorHex" maxlength="7" autocomplete="off" spellcheck="false" aria-label="Custom HEX color"></div>' +
      '<div class="color-rgb">' + ['R','G','B'].map(function (c) { return '<label>' + c + '<input class="pack-input" id="color' + c + '" type="number" min="0" max="255" step="1" inputmode="numeric" aria-label="' + ({R:'Red',G:'Green',B:'Blue'})[c] + '"></label>'; }).join('') + '</div>' +
      '<button class="gb" id="colorDone" type="button">Done</button>';
    document.body.appendChild(panel); this.panel = panel;
    this.$ = function (id) { return panel.querySelector('#' + id); };
    options.button.setAttribute('aria-controls', panel.id);
    options.button.addEventListener('click', function () { panel.hidden ? self.open() : self.close(true); });
    this.$('colorClose').onclick = this.$('colorDone').onclick = function () { self.close(true); };
    this.$('colorHue').addEventListener('input', function () { self.h = Number(this.value); self.emit(); });
    this.$('colorAlpha').addEventListener('input', function () { self.alpha = Number(this.value); self.emit(); });
    this.$('colorHex').addEventListener('input', function () {
      var value = this.value.trim(); if (!value.startsWith('#')) value = '#' + value;
      if (/^#[0-9a-f]{6}$/i.test(value)) { self.set(value, self.alpha); options.onChange(self.hex, self.alpha); }
    });
    this.$('colorHex').addEventListener('blur', function () { this.value = self.hex.toUpperCase(); });
    ['R','G','B'].forEach(function (channel, index) {
      self.$('color' + channel).addEventListener('input', function () {
        if (this.value === '') return;
        var values = rgb(self.hex); values[index] = clamp(Math.round(Number(this.value)), 0, 255);
        if (Number.isFinite(values[index])) { self.set(hex(values), self.alpha); options.onChange(self.hex, self.alpha); }
      });
      self.$('color' + channel).addEventListener('blur', function () { this.value = rgb(self.hex)[index]; });
    });
    var square = this.$('colorSV'), pointer = null;
    function select(event) {
      var rect = square.getBoundingClientRect();
      self.s = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      self.v = 1 - clamp((event.clientY - rect.top) / rect.height, 0, 1); self.emit();
    }
    square.addEventListener('pointerdown', function (event) {
      if (event.button > 0) return;
      event.preventDefault(); pointer = event.pointerId; square.focus({preventScroll: true});
      try { square.setPointerCapture(pointer); } catch (_) {}
      select(event);
    });
    square.addEventListener('pointermove', function (event) { if (event.pointerId === pointer) select(event); });
    function end() { pointer = null; }
    ['pointerup','pointercancel','lostpointercapture'].forEach(function (name) { square.addEventListener(name, end); });
    square.addEventListener('keydown', function (event) {
      var step = event.shiftKey ? .1 : .01;
      if (event.key === 'ArrowLeft') self.s = clamp(self.s - step, 0, 1);
      else if (event.key === 'ArrowRight') self.s = clamp(self.s + step, 0, 1);
      else if (event.key === 'ArrowUp') self.v = clamp(self.v + step, 0, 1);
      else if (event.key === 'ArrowDown') self.v = clamp(self.v - step, 0, 1);
      else if (event.key === 'Home') self.s = 0;
      else if (event.key === 'End') self.s = 1;
      else return;
      event.preventDefault(); event.stopPropagation(); self.emit();
    });
    document.addEventListener('keydown', function (event) {
      if (!panel.hidden && event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); self.close(true); }
    }, true);
    document.addEventListener('pointerdown', function (event) {
      if (!panel.hidden && !panel.contains(event.target) && !options.button.contains(event.target)) self.close(false);
    });
    document.addEventListener('focusin', function (event) {
      if (!panel.hidden && !panel.contains(event.target) && !options.button.contains(event.target)) self.close(false);
    });
    window.addEventListener('resize', function () { if (!panel.hidden) self.position(); }, {passive: true});
    if (window.visualViewport) ['resize', 'scroll'].forEach(function (name) {
      window.visualViewport.addEventListener(name, function () { if (!panel.hidden) self.position(); }, {passive: true});
    });
    window.addEventListener('scroll', function (event) { if (!panel.hidden && !panel.contains(event.target)) self.position(); }, {passive: true, capture: true});
    var initial = options.read(); this.set(initial.hex, initial.alpha);
  }
  ColorChooser.prototype.set = function (value, alpha) {
    value = value.toLowerCase();
    if (value !== this.hex) {
      var hsv = rgbToHSV(rgb(value), this.h); this.h = hsv.h; this.s = hsv.s; this.v = hsv.v; this.hex = value;
    }
    if (alpha != null) this.alpha = clamp(alpha, 0, 100);
    this.render();
  };
  ColorChooser.prototype.render = function () {
    var values = rgb(this.hex), alpha = this.alpha / 100, active = document.activeElement;
    this.$('colorSV').style.backgroundColor = 'hsl(' + this.h + ',100%,50%)';
    this.$('colorSV').setAttribute('aria-valuenow', Math.round(this.s * 100));
    this.$('colorSV').setAttribute('aria-valuetext', 'Saturation ' + Math.round(this.s * 100) + '%, brightness ' + Math.round(this.v * 100) + '%');
    this.$('colorCursor').style.left = this.s * 100 + '%'; this.$('colorCursor').style.top = (1 - this.v) * 100 + '%';
    this.$('colorHue').value = Math.round(this.h); this.$('colorHueValue').value = Math.round(this.h) + '°';
    this.$('colorAlpha').value = this.alpha; this.$('colorAlphaValue').value = this.alpha + '%';
    this.$('colorAlpha').style.backgroundImage = 'linear-gradient(to right,rgba(' + values.join(',') + ',0),' + this.hex + '),conic-gradient(#d9d9d9 25%,#fff 0 50%,#d9d9d9 0 75%,#fff 0)';
    this.$('colorAlpha').style.backgroundSize = '100% 100%,10px 10px';
    this.$('colorPreview').style.backgroundColor = 'rgba(' + values.join(',') + ',' + alpha + ')';
    if (active !== this.$('colorHex')) this.$('colorHex').value = this.hex.toUpperCase();
    ['R','G','B'].forEach(function (channel, i) { if (active !== this.$('color' + channel)) this.$('color' + channel).value = values[i]; }, this);
  };
  ColorChooser.prototype.emit = function () {
    this.hex = hex(hsvToRGB(this.h, this.s, this.v)); this.render(); this.options.onChange(this.hex, this.alpha);
  };
  ColorChooser.prototype.position = function () {
    var anchor = this.options.button.getBoundingClientRect(), panel = this.panel;
    var viewport = window.visualViewport, width = viewport ? viewport.width : innerWidth, height = viewport ? viewport.height : innerHeight;
    var left = viewport ? viewport.offsetLeft : 0, top = viewport ? viewport.offsetTop : 0;
    panel.style.maxHeight = Math.max(80, height - 24) + 'px'; panel.style.maxWidth = Math.max(100, width - 24) + 'px';
    var x = clamp(anchor.right - panel.offsetWidth, left + 12, left + width - panel.offsetWidth - 12);
    var y = anchor.bottom + 10;
    if (y + panel.offsetHeight > top + height - 12) y = anchor.top - panel.offsetHeight - 10;
    panel.style.left = x + 'px'; panel.style.top = clamp(y, top + 12, top + height - panel.offsetHeight - 12) + 'px';
  };
  ColorChooser.prototype.open = function () {
    var current = this.options.read(); this.set(current.hex, current.alpha);
    this.panel.hidden = false; this.position(); this.options.button.setAttribute('aria-expanded', 'true');
    this.$('colorSV').focus({preventScroll: true}); window.Motion.surface(this.panel);
  };
  ColorChooser.prototype.close = function (focus) {
    this.panel.hidden = true; this.options.button.setAttribute('aria-expanded', 'false');
    if (focus) this.options.button.focus({preventScroll: true});
  };
  window.ColorChooser = ColorChooser;
})();
