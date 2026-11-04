(function () {
  'use strict';
  var TA = window.TextureAnimation, MT = window.MinecraftTextures;
  function Controls(options) {
    var self = this; this.options = options; this.doc = null; this.playing = false; this.raf = 0; this.signature = ''; this.version = -1; this.selected = -1;
    this.panel = document.getElementById('edAnimation');
    this.$ = function (id) { return self.panel.querySelector('#' + id); };
    this.panel.addEventListener('click', function (event) {
      var target = event.target, frame = target.closest('[data-frame]'), action = target.closest('[data-anim-action]'), view = target.closest('[data-anim-view]');
      if (frame) options.select(Number(frame.dataset.frame), true);
      else if (view) options.select(null, view.dataset.animView === 'frame');
      else if (action && !action.disabled) options.change(action.dataset.animAction, action.dataset.direction ? Number(action.dataset.direction) : undefined);
      else if (target.closest('#animToggle') && !self.$('animToggle').disabled) options.change('toggle');
      else if (target.closest('#animInterpolate')) options.change('interpolate', self.$('animInterpolate').getAttribute('aria-checked') !== 'true');
      else if (target.closest('#animPlay')) self.playing ? self.stop() : self.play();
      else if (target.closest('#animAllTime')) options.change('all-time', Number(self.$('animTime').value));
    });
    this.$('animTime').addEventListener('change', function () { options.change('time', Number(this.value)); });
    this.$('animFrames').addEventListener('keydown', function (event) {
      var button = event.target.closest('[data-frame]'); if (!button || !self.info) return;
      var next = Number(button.dataset.frame);
      if (event.key === 'ArrowLeft') next--;
      else if (event.key === 'ArrowRight') next++;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = self.info.steps.length - 1;
      else return;
      event.preventDefault(); event.stopPropagation(); next = Math.max(0, Math.min(self.info.steps.length - 1, next)); options.select(next, true);
      self.$('animFrames').querySelector('[data-frame="' + next + '"]').focus({preventScroll: true});
    });
  }
  Controls.prototype.refresh = function () {
    var doc = this.options.read(), previous = this.doc, info = null, error = '';
    if (doc) { try { info = TA.layout(doc.e); } catch (e) { error = e.message; } }
    this.panel.hidden = !doc || doc.id === 'skin';
    if (previous !== doc) { this.stop(); this.signature = ''; this.version = -1; this.selected = -1; }
    this.doc = doc; this.info = info;
    if (!doc) return;
    var allowed = TA.supported(doc.e); this.$('animToggle').disabled = !allowed || !!error;
    this.$('animToggle').setAttribute('aria-checked', String(!!doc.e.animation)); this.$('animBody').hidden = !info;
    this.$('animHint').textContent = error || (allowed ? 'Frames play in Minecraft at 20 ticks per second.' : 'Choose a block, item, or atlas sprite to animate. Minecraft renders this texture as a static image.');
    if (!info) { this.stop(); return; }
    doc.frame = Math.max(0, Math.min(info.steps.length - 1, doc.frame));
    var signature = JSON.stringify([doc.w, doc.h, doc.e.animation]);
    if (signature !== this.signature) {
      this.$('animFrames').innerHTML = info.steps.map(function (_, i) {
        return '<button class="anim-frame" type="button" data-frame="' + i + '" aria-pressed="false"><canvas width="48" height="48" aria-hidden="true"></canvas><span>' + (i + 1) + '</span></button>';
      }).join('');
      this.signature = signature; this.version = -1; this.previewKey = ''; if (this.playing) this.started = performance.now();
    }
    this.$('animCount').textContent = info.steps.length + (info.steps.length === 1 ? ' frame' : ' frames');
    this.$('animSize').textContent = info.w + '×' + info.h + ' · ' + Number((info.duration / 20).toFixed(2)) + ' s loop';
    this.$('animFrameLabel').textContent = 'Frame ' + (doc.frame + 1) + ' of ' + info.steps.length;
    if (document.activeElement !== this.$('animTime') || this.selected !== doc.frame) this.$('animTime').value = info.steps[doc.frame].time;
    this.$('animTimeHint').textContent = info.steps[doc.frame].time + ' ticks · ' + Number((info.steps[doc.frame].time / 20).toFixed(2)) + ' s';
    this.$('animInterpolate').setAttribute('aria-checked', String(!!doc.e.animation.interpolate));
    this.$('animRemove').disabled = info.steps.length <= 1; this.$('animEarlier').disabled = doc.frame === 0; this.$('animLater').disabled = doc.frame === info.steps.length - 1;
    this.$('animView').querySelectorAll('[data-anim-view]').forEach(function (b) { b.setAttribute('aria-pressed', String((b.dataset.animView === 'frame') === doc.frameView)); });
    var dirty = this.version !== doc.version, self = this;
    this.$('animFrames').querySelectorAll('[data-frame]').forEach(function (button, i) {
      button.setAttribute('aria-pressed', String(i === doc.frame)); button.setAttribute('aria-label', 'Edit frame ' + (i + 1) + ', ' + info.steps[i].time + ' ticks');
      if (dirty) {
        var cv = button.querySelector('canvas'), ctx = cv.getContext('2d'), r = TA.frameRect(info, i), scale = Math.min(48 / r.w, 48 / r.h);
        ctx.clearRect(0, 0, 48, 48); ctx.imageSmoothingEnabled = false; ctx.drawImage(doc.cv, r.x, r.y, r.w, r.h, (48 - r.w * scale) / 2, (48 - r.h * scale) / 2, r.w * scale, r.h * scale);
      }
    });
    if (this.selected !== doc.frame) {
      var active = this.$('animFrames').querySelector('[data-frame="' + doc.frame + '"]'), strip = this.$('animFrames');
      if (active.offsetLeft < strip.scrollLeft) strip.scrollLeft = active.offsetLeft;
      else if (active.offsetLeft + active.offsetWidth > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = active.offsetLeft + active.offsetWidth - strip.clientWidth;
    }
    this.version = doc.version; this.selected = doc.frame;
    if (!this.playing) this.draw(null);
  };
  Controls.prototype.draw = function (time) {
    if (!this.doc || !this.info) return;
    var doc = this.doc, frame = time == null ? TA.frameRect(this.info, doc.frame) : MT.frame(doc.e, time, doc.w, doc.h);
    var key = [frame.index, frame.step, Math.round((frame.mix || 0) * 20), doc.version].join(':');
    if (time != null && key === this.previewKey) return;
    this.previewKey = key;
    var cv = this.$('animPreview'), ctx = cv.getContext('2d'), scale = Math.min(cv.width / frame.w, cv.height / frame.h);
    ctx.clearRect(0, 0, cv.width, cv.height); TA.paintFrame(ctx, doc.cv, frame, (cv.width - frame.w * scale) / 2, (cv.height - frame.h * scale) / 2, frame.w * scale, frame.h * scale);
    this.$('animFrames').querySelectorAll('[data-frame]').forEach(function (button, i) { button.classList.toggle('is-playing', time != null && i === frame.step); });
    this.panel.dataset.playingFrame = String(time == null ? doc.frame : frame.step);
  };
  Controls.prototype.play = function () {
    if (!this.info) return;
    this.playing = true; this.started = performance.now(); this.previewKey = ''; this.$('animPlay').textContent = 'Pause'; this.$('animPlay').setAttribute('aria-pressed', 'true');
    var self = this;
    function tick(now) {
      if (!self.playing || self.options.read() !== self.doc || self.panel.hidden) { self.stop(); return; }
      if (!document.hidden) self.draw(now - self.started);
      self.raf = requestAnimationFrame(tick);
    }
    this.raf = requestAnimationFrame(tick);
  };
  Controls.prototype.stop = function () {
    this.playing = false; cancelAnimationFrame(this.raf); this.raf = 0;
    this.$('animPlay').textContent = 'Play'; this.$('animPlay').setAttribute('aria-pressed', 'false'); this.previewKey = '';
    this.draw(null);
  };
  window.AnimationControls = Controls;
})();
