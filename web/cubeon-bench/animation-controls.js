(function () {
  'use strict';
  var TA = window.TextureAnimation, MT = window.MinecraftTextures;
  function Controls(options) {
    var self = this; this.options = options; this.doc = null; this.playing = false; this.raf = 0; this.signature = ''; this.version = -1; this.selected = -1;
    this.panel = document.getElementById('edAnimation');
    this.rail = document.getElementById('edFrames'); this.editor = document.getElementById('ed');
    this.$ = function (id) { return document.getElementById(id); };
    function click(event) {
      var target = event.target, frame = target.closest('[data-frame]'), action = target.closest('[data-anim-action]'), view = target.closest('[data-anim-view]'), clipboard = target.closest('[data-frame-action]');
      if (frame) { options.select(Number(frame.dataset.frame), true); if (innerWidth <= 900) self.setRailOpen(false); }
      else if (clipboard) {options.clipboard(clipboard.dataset.frameAction);self.focusSelected(false);}
      else if (view) options.select(null, view.dataset.animView === 'frame');
      else if (action && !action.disabled) options.change(action.dataset.animAction, action.dataset.direction ? Number(action.dataset.direction) : undefined);
      else if (target.closest('#animToggle') && !self.$('animToggle').disabled) options.change('toggle');
      else if (target.closest('#animInterpolate')) options.change('interpolate', self.$('animInterpolate').getAttribute('aria-checked') !== 'true');
      else if (target.closest('#animPlay')) self.playing ? self.stop() : self.play();
      else if (target.closest('#animAllTime')) options.change('all-time', Number(self.$('animTime').value));
    }
    this.rail.addEventListener('click', click);
    this.$('canvasAnimate').addEventListener('click', function () {
      options.change('toggle');
      if (self.info) { self.setRailOpen(true); self.$('animPlay').focus({preventScroll: true}); }
    });
    this.$('edFramesToggle').addEventListener('click', function () {
      self.editor.classList.remove('l-open', 'r-open');
      var open = this.getAttribute('aria-expanded') !== 'true'; self.setRailOpen(open);
      if (open) { var active = self.$('animFrames').querySelector('[aria-pressed="true"]'); if (active) { active.scrollIntoView({block: 'nearest'}); active.focus({preventScroll: true}); } }
    });
    this.$('edFramesClose').addEventListener('click', function () { self.setRailOpen(false); self.$('edFramesToggle').focus(); });
    window.addEventListener('resize', function () { self.layoutRail(); });
    this.$('animTime').addEventListener('change', function () { options.change('time', Number(this.value)); });
    this.$('animSeconds').addEventListener('change', function () {
      var seconds = Number(this.value);
      if (Number.isFinite(seconds) && seconds >= .05 && seconds <= 300) options.change('time', Math.round(seconds * 20));
      if (self.info) this.value = Number((self.info.steps[self.doc.frame].time / 20).toFixed(2));
      self.refresh();
    });
    this.$('animFrames').addEventListener('pointerdown', function (event) {
      var handle = event.target.closest('.anim-drag');
      if (!handle || event.button !== 0 || !self.info || self.info.steps.length < 2) return;
      event.preventDefault(); self.cancelDrag();
      self.drag = {doc: self.doc, handle: handle, pointer: event.pointerId, from: Number(handle.dataset.step), to: Number(handle.dataset.step), start: event.clientY, y: event.clientY, active: false};
      handle.setPointerCapture(event.pointerId);
      function tick() { if (!self.drag) return; self.dragTarget(); self.dragRaf = requestAnimationFrame(tick); }
      self.dragRaf = requestAnimationFrame(tick);
    });
    this.$('animFrames').addEventListener('pointermove', function (event) {
      var drag = self.drag; if (!drag || drag.pointer !== event.pointerId) return;
      if (event.pointerType === 'mouse' && event.buttons !== 1) { self.cancelDrag(); return; }
      drag.y = event.clientY;
      if (Math.abs(drag.y - drag.start) > 5) drag.active = true;
    });
    this.$('animFrames').addEventListener('pointerup', function (event) {
      var drag = self.drag; if (!drag || drag.pointer !== event.pointerId) return;
      drag.y = event.clientY; self.dragTarget();
      self.cancelDrag();
      if (drag.doc !== self.options.read()) return;
      if (drag.active && drag.to !== drag.from) {
        options.change('reorder', {from: drag.from, to: drag.to});
        self.$('animReorderStatus').textContent = 'Frame moved to position ' + (drag.to + 1) + '.';
        var handle = self.$('animFrames').querySelector('.anim-drag[data-step="' + drag.to + '"]');
        if (handle) handle.focus({preventScroll: true});
      } else if (!drag.active) options.select(drag.from, true);
    });
    this.$('animFrames').addEventListener('pointercancel', function () { self.cancelDrag(); });
    this.$('animFrames').addEventListener('lostpointercapture', function () { self.cancelDrag(); });
    window.addEventListener('blur', function () { self.cancelDrag(); });
    this.rail.addEventListener('keydown', function (event) {
      if (event.defaultPrevented || event.isComposing || event.target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])') || document.querySelector('dialog[open]') || !self.info) return;
      if (self.drag && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); self.cancelDrag(); return; }
      var handle = event.target.closest('.anim-drag'), button = event.target.closest('[data-frame]');
      var mod = event.ctrlKey || event.metaKey, key = event.key.toLowerCase(), from = handle ? Number(handle.dataset.step) : button ? Number(button.dataset.frame) : self.doc.frame;
      var action = mod ? {c:'copy',x:'cut',v:'paste',d:'duplicate'}[key] : (key === 'delete' || key === 'backspace') ? 'remove' : null;
      if (action && !event.altKey) {
        event.preventDefault(); event.stopPropagation();
        if (event.repeat) return;
        options.select(from, true); options.clipboard(action); self.focusSelected(!!handle); return;
      }
      if (event.altKey && !mod && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
        event.preventDefault(); event.stopPropagation();
        var to = Math.max(0, Math.min(self.info.steps.length - 1, from + (event.key === 'ArrowUp' ? -1 : 1)));
        options.change('reorder', {from: from, to: to});
        self.focusSelected(!!handle);
        return;
      }
      if (mod || event.altKey) return;
      if (key === ' ') {event.preventDefault();event.stopPropagation();if(!event.repeat)self.playing?self.stop():self.play();return;}
      if (!button && !handle) return;
      var next = from;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next--;
      else if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next++;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = self.info.steps.length - 1;
      else return;
      event.preventDefault(); event.stopPropagation(); next = Math.max(0, Math.min(self.info.steps.length - 1, next)); options.select(next, true);
      self.focusSelected(!!handle);
    });
  }
  Controls.prototype.focusSelected = function (handle) {
    var button = this.$('animFrames').querySelector((handle ? '.anim-drag[data-step="' : '[data-frame="') + this.doc.frame + '"]');
    if (button) {button.scrollIntoView({block:'nearest'});button.focus({preventScroll:true});}
  };
  Controls.prototype.setRailOpen = function (open) {
    this.cancelDrag();
    if (innerWidth > 1100) { window.CB.D.set.animationFrames = open; window.CB.save(); }
    else this.editor.classList.toggle('frames-open', open);
    this.layoutRail();
  };
  Controls.prototype.layoutRail = function () {
    var hasFrames = !!this.info && !!this.doc && this.doc.id !== 'skin', wide = innerWidth > 1100;
    var open = hasFrames && (wide ? window.CB.D.set.animationFrames !== false : this.editor.classList.contains('frames-open'));
    var layoutChanged = this.editor.classList.contains('frames-visible') !== (wide && open);
    if (layoutChanged) getComputedStyle(this.editor.querySelector('.edmn')).getPropertyValue('--frames-width');
    this.editor.classList.toggle('has-animation', hasFrames); this.editor.classList.toggle('frames-visible', wide && open);
    if (!hasFrames || wide) this.editor.classList.remove('frames-open');
    window.Motion.panel(this.rail, open);
    this.$('edFramesToggle').hidden = !hasFrames;
    this.$('edFramesToggle').setAttribute('aria-expanded', String(open));
    this.$('edFramesToggle').title = (open ? 'Hide animation frames' : 'Show animation frames') + ' · Shift F';
    if (!open && this.playing) this.stop();
    if (layoutChanged && window.EditorLayout) window.EditorLayout.fit();
  };
  Controls.prototype.cancelDrag = function () {
    var drag = this.drag; this.drag = null; cancelAnimationFrame(this.dragRaf);
    this.$('animFrames').classList.remove('is-reordering');
    this.$('animFrames').querySelectorAll('.anim-row').forEach(function (row) { row.classList.remove('is-drag-source', 'drop-before', 'drop-after'); });
    if (drag && drag.handle.hasPointerCapture(drag.pointer)) drag.handle.releasePointerCapture(drag.pointer);
  };
  Controls.prototype.dragTarget = function () {
    var drag = this.drag; if (!drag || !drag.active) return;
    var strip = this.$('animFrames'), bounds = strip.getBoundingClientRect();
    if (drag.y < bounds.top + 28) strip.scrollTop -= 8;
    else if (drag.y > bounds.bottom - 28) strip.scrollTop += 8;
    var rows = Array.from(strip.querySelectorAll('.anim-row')), best = Infinity;
    rows.forEach(function (row, i) { var r = row.getBoundingClientRect(), distance = Math.abs(drag.y - r.top - r.height / 2); if (distance < best) { best = distance; drag.to = i; } });
    strip.classList.add('is-reordering');
    rows.forEach(function (row, i) { row.classList.toggle('is-drag-source', i === drag.from); row.classList.toggle('drop-before', i === drag.to && drag.to < drag.from); row.classList.toggle('drop-after', i === drag.to && drag.to > drag.from); });
  };
  Controls.prototype.refresh = function () {
    var doc = this.options.read(), previous = this.doc, info = null, error = '';
    if (doc) { try { info = TA.layout(doc.e); } catch (e) { error = e.message; } }
    this.panel.hidden = !doc || doc.id === 'skin';
    if (previous !== doc) { this.cancelDrag(); this.stop(); this.signature = ''; this.version = -1; this.selected = -1; this.rail.querySelector('details').open = false; }
    this.doc = doc; this.info = info;
    this.layoutRail();
    this.$('canvasAnimate').hidden = !doc || doc.id === 'skin' || !!info || !TA.supported(doc.e) || !!error;
    if (!doc) return;
    var allowed = TA.supported(doc.e); this.$('animToggle').disabled = !allowed || !!error;
    this.$('animToggle').setAttribute('aria-checked', String(!!doc.e.animation)); this.$('animBody').hidden = !info;
    this.$('animHint').textContent = error || ''; this.$('animHint').hidden = !error;
    if (!info) { this.stop(); return; }
    doc.frame = Math.max(0, Math.min(info.steps.length - 1, doc.frame));
    var signature = JSON.stringify([doc.w, doc.h, doc.e.animation]);
    var rowBoxes, focused = document.activeElement, restoreFocus = previous === doc && this.$('animFrames').contains(focused), restoreHandle = restoreFocus && focused.classList.contains('anim-drag');
    if (signature !== this.signature) {
      rowBoxes = window.Motion.capture(this.$('animFrames').querySelectorAll('.anim-row'));
      this.cancelDrag();
      var occurrences = Object.create(null);
      this.$('animFrames').innerHTML = info.steps.map(function (step, i) {
        var key = step.index + ':' + step.time, occurrence = occurrences[key] || 0; occurrences[key] = occurrence + 1;
        return '<div class="anim-row" data-motion-key="' + key + ':' + occurrence + '"><button class="anim-drag" type="button" data-step="' + i + '" aria-label="Reorder frame ' + (i + 1) + '" title="Drag to reorder · Alt + up / down"><svg viewBox="0 0 12 24" width="12" height="24" fill="currentColor" aria-hidden="true"><circle cx="3" cy="6" r="1.5"/><circle cx="9" cy="6" r="1.5"/><circle cx="3" cy="12" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="3" cy="18" r="1.5"/><circle cx="9" cy="18" r="1.5"/></svg></button><button class="anim-frame" type="button" data-frame="' + i + '" aria-pressed="false"><canvas width="64" height="64" aria-hidden="true"></canvas><span><b>Frame ' + (i + 1) + '</b><small>' + Number((step.time / 20).toFixed(2)) + ' s</small></span></button></div>';
      }).join('');
      this.signature = signature; this.version = -1; this.selected = -1; this.previewKey = ''; if (this.playing) this.started = performance.now();
    }
    this.$('animCount').textContent = info.steps.length + (info.steps.length === 1 ? ' frame' : ' frames');
    this.$('animSize').textContent = Number((info.duration / 20).toFixed(2)) + ' s loop';
    this.$('animFrameLabel').textContent = 'Frame ' + (doc.frame + 1) + ' of ' + info.steps.length;
    if (document.activeElement !== this.$('animTime') || this.selected !== doc.frame) this.$('animTime').value = info.steps[doc.frame].time;
    if (document.activeElement !== this.$('animSeconds') || this.selected !== doc.frame) this.$('animSeconds').value = Number((info.steps[doc.frame].time / 20).toFixed(2));
    this.$('animTimeHint').textContent = 'Lower duration = faster playback. 20 ticks = 1 second.';
    this.$('animInterpolate').setAttribute('aria-checked', String(!!doc.e.animation.interpolate));
    this.$('animRemove').disabled = info.steps.length <= 1; this.$('animEarlier').disabled = doc.frame === 0; this.$('animLater').disabled = doc.frame === info.steps.length - 1;
    this.$('animView').querySelectorAll('[data-anim-view]').forEach(function (b) { b.setAttribute('aria-pressed', String((b.dataset.animView === 'frame') === doc.frameView)); });
    var dirty = this.version !== doc.version, self = this;
    this.$('animFrames').querySelectorAll('[data-frame]').forEach(function (button, i) {
      button.setAttribute('aria-pressed', String(i === doc.frame)); button.setAttribute('aria-label', 'Edit frame ' + (i + 1) + ', ' + Number((info.steps[i].time / 20).toFixed(2)) + ' seconds');
      button.parentElement.classList.toggle('is-selected', i === doc.frame);
      if (dirty) {
        var cv = button.querySelector('canvas'), ctx = cv.getContext('2d'), r = TA.frameRect(info, i), scale = Math.min(cv.width / r.w, cv.height / r.h);
        ctx.clearRect(0, 0, cv.width, cv.height); ctx.imageSmoothingEnabled = false; ctx.drawImage(doc.cv, r.x, r.y, r.w, r.h, (cv.width - r.w * scale) / 2, (cv.height - r.h * scale) / 2, r.w * scale, r.h * scale);
      }
    });
    if (this.selected !== doc.frame) {
      var active = this.$('animFrames').querySelector('[data-frame="' + doc.frame + '"]'), strip = this.$('animFrames');
      var row = active.parentElement;
      if (row.offsetTop < strip.scrollTop) strip.scrollTop = row.offsetTop;
      else if (row.offsetTop + row.offsetHeight > strip.scrollTop + strip.clientHeight) strip.scrollTop = row.offsetTop + row.offsetHeight - strip.clientHeight;
    }
    this.version = doc.version; this.selected = doc.frame;
    window.Motion.reorder(rowBoxes, this.$('animFrames').querySelectorAll('.anim-row'));
    if (rowBoxes && restoreFocus && !this.rail.hidden && !this.rail.inert) this.focusSelected(restoreHandle);
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
    this.rail.classList.add('is-playing');
    var self = this;
    function tick(now) {
      if (!self.playing || self.options.read() !== self.doc || self.panel.hidden) { self.stop(); return; }
      if (!document.hidden) self.draw(now - self.started);
      self.raf = requestAnimationFrame(tick);
    }
    this.raf = requestAnimationFrame(tick);
  };
  Controls.prototype.stop = function () {
    this.cancelDrag();
    this.playing = false; cancelAnimationFrame(this.raf); this.raf = 0;
    this.rail.classList.remove('is-playing');
    this.$('animPlay').textContent = 'Play'; this.$('animPlay').setAttribute('aria-pressed', 'false'); this.previewKey = '';
    this.draw(null);
  };
  window.AnimationControls = Controls;
})();
