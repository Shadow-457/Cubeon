(function () {
  'use strict';
  function copy(value) { return value == null ? value : structuredClone(value); }
  function hasOverride(project, id) { return !!project.animations && Object.prototype.hasOwnProperty.call(project.animations, id); }
  function effectiveEntry(source, override, width, height) {
    var meta = copy(source.mcmeta || {}), scale = width / source.w;
    if (!meta.animation && source.animation) meta.animation = copy(source.animation);
    if (override !== undefined) {
      if (override === null) delete meta.animation;
      else meta.animation = copy(override);
    } else if (meta.animation && scale === height / source.h) {
      ['width', 'height'].forEach(function (key) { if (meta.animation[key]) meta.animation[key] = Math.round(meta.animation[key] * scale); });
    }
    var entry = Object.assign({}, source, {w: width, h: height, mcmeta: meta});
    delete entry.animation;
    if (meta.animation) entry.animation = meta.animation;
    return entry;
  }
  function supported(entry) {
    var id = entry.textureId || entry.id;
    if (/^entity\/player\//.test(id) || entry.id === 'skin') return false;
    return !!entry.animation || /^(block|item|particle|painting|mob_effect|trims)\//.test(id) ||
      /^gui\/sprites\//.test(id) || /^entity\/(banner|shield|bed|chest|shulker|signs)\//.test(id);
  }
  function layout(entry) {
    var a = entry.animation; if (!a) return null;
    var w = a.width || (a.height ? entry.w : Math.min(entry.w, entry.h));
    var h = a.height || (a.width ? entry.h : Math.min(entry.w, entry.h));
    if (!Number.isInteger(w) || !Number.isInteger(h) || w < 1 || h < 1 || entry.w % w || entry.h % h) {
      throw new Error('The animation frame size does not fit this texture. Reset the texture or import a valid frame sheet.');
    }
    var columns = entry.w / w, count = columns * entry.h / h, time = a.frametime == null ? 1 : a.frametime;
    if (!Number.isInteger(time) || time < 1) throw new Error('Frame timing must be at least one Minecraft tick.');
    var sequence = a.frames && a.frames.length ? copy(a.frames) : Array.from({length: count}, function (_, i) { return i; });
    var steps = sequence.map(function (frame) {
      var index = typeof frame === 'number' ? frame : frame && frame.index;
      var duration = typeof frame === 'object' && frame && frame.time != null ? frame.time : time;
      if (!Number.isInteger(index) || index < 0 || index >= count || !Number.isInteger(duration) || duration < 1) {
        throw new Error('The animation references a missing frame or invalid timing. Import a valid frame sheet.');
      }
      return {index: index, time: duration};
    });
    return {w: w, h: h, columns: columns, count: count, sequence: sequence, steps: steps,
      duration: steps.reduce(function (sum, frame) { return sum + frame.time; }, 0)};
  }
  function physicalRect(info, index) { return {x: index % info.columns * info.w, y: Math.floor(index / info.columns) * info.h, w: info.w, h: info.h}; }
  function frameRect(info, step) { return physicalRect(info, info.steps[Math.max(0, Math.min(info.steps.length - 1, step))].index); }
  function crop(image, rect) {
    var result = new ImageData(rect.w, rect.h);
    for (var y = 0; y < rect.h; y++) {
      var start = ((rect.y + y) * image.width + rect.x) * 4;
      result.data.set(image.data.subarray(start, start + rect.w * 4), y * rect.w * 4);
    }
    return result;
  }
  function checkSize(w, h) {
    if (w > 32767 || h > 32767 || w * h > 67108864) throw new Error('This animation is too large for the editor. Use fewer frames or a smaller texture scale.');
  }
  function pack(frames) {
    var w = frames[0].width, h = frames[0].height; checkSize(w, h * frames.length);
    var result = new ImageData(w, h * frames.length);
    frames.forEach(function (frame, i) { result.data.set(frame.data, i * w * h * 4); });
    return result;
  }
  function settings(doc, info) {
    var result = copy(doc.e.animation); result.width = info.w; result.height = info.h; result.frames = copy(info.sequence); return result;
  }
  function indexed(frame, index) { return typeof frame === 'number' ? index : Object.assign({}, frame, {index: index}); }
  function copyFrame(doc) {
    var info = layout(doc.e); if (!info) return null;
    var selected = Math.max(0, Math.min(info.steps.length - 1, doc.frame));
    return {data: crop(doc.data, frameRect(info, selected)), time: info.steps[selected].time};
  }
  function change(doc, action, value) {
    var info = layout(doc.e), selected = info ? Math.max(0, Math.min(info.steps.length - 1, doc.frame)) : 0;
    if (action === 'toggle') {
      if (info) return {data: crop(doc.data, frameRect(info, selected)), animation: null, frame: 0, frameView: false};
      checkSize(doc.w, doc.h * 2);
      return {data: pack([doc.data, doc.data]), animation: {width: doc.w, height: doc.h, frametime: 2, frames: [0, 1]}, frame: 0, frameView: true};
    }
    if (!info) return null;
    var meta = settings(doc, info), frames, target;
    if (action === 'add' || action === 'paste') {
      var copied = action === 'paste' ? value : copyFrame(doc);
      if (!copied || !copied.data) return null;
      if (copied.data.width !== info.w || copied.data.height !== info.h) throw new Error('This frame is ' + copied.data.width + '×' + copied.data.height + '. Paste into an animation with ' + copied.data.width + '×' + copied.data.height + ' frames.');
      checkSize(info.w, info.h * (info.count + 1));
      frames = Array.from({length: info.count}, function (_, i) { return crop(doc.data, physicalRect(info, i)); });
      frames.push(copied.data); meta.frames.splice(selected + 1, 0, {index: info.count, time: copied.time});
      return {data: pack(frames), animation: meta, frame: selected + 1, frameView: true};
    }
    if (action === 'remove') {
      if (info.steps.length <= 1) return null;
      meta.frames.splice(selected, 1);
      var used = Array.from(new Set(meta.frames.map(function (f) { return typeof f === 'number' ? f : f.index; }))), remap = new Map();
      frames = used.map(function (index, i) { remap.set(index, i); return crop(doc.data, physicalRect(info, index)); });
      meta.frames = meta.frames.map(function (f) { return indexed(f, remap.get(typeof f === 'number' ? f : f.index)); });
      return {data: pack(frames), animation: meta, frame: Math.min(selected, meta.frames.length - 1), frameView: true};
    }
    if (action === 'move') {
      target = selected + value; if (target < 0 || target >= meta.frames.length) return null;
      var item = meta.frames[selected]; meta.frames[selected] = meta.frames[target]; meta.frames[target] = item;
      return {animation: meta, frame: target};
    }
    if (action === 'reorder') {
      var from = value && value.from, to = value && value.to;
      if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to < 0 || from >= meta.frames.length || to >= meta.frames.length || from === to) return null;
      var moved = meta.frames.splice(from, 1)[0]; meta.frames.splice(to, 0, moved);
      return {animation: meta, frame: to, frameView: true};
    }
    if (action === 'time' || action === 'all-time') {
      if (!Number.isInteger(value) || value < 1 || value > 6000) throw new Error('Choose a frame time from 1 to 6,000 ticks. Minecraft runs at 20 ticks per second.');
      if (action === 'time') {
        if (info.steps[selected].time === value) return null;
        meta.frames[selected] = Object.assign({}, typeof meta.frames[selected] === 'object' ? meta.frames[selected] : {}, {index: info.steps[selected].index, time: value});
      } else {
        meta.frametime = value;
        meta.frames = meta.frames.map(function (f) { if (typeof f === 'number') return f; var result = copy(f); delete result.time; return result; });
      }
      return {animation: meta};
    }
    if (action === 'interpolate') {
      if (!!meta.interpolate === value) return null;
      meta.interpolate = value; return {animation: meta};
    }
    return null;
  }
  function transform(image, kind) {
    var w = kind === 'rot' ? image.height : image.width, h = kind === 'rot' ? image.width : image.height;
    var result = new ImageData(w, h), sw = image.width, sh = image.height;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      if (kind === 'clear') continue;
      var sx = kind === 'fh' ? sw - 1 - x : kind === 'rot' ? y : x;
      var sy = kind === 'fv' ? sh - 1 - y : kind === 'rot' ? sh - 1 - x : y;
      var start = (sy * sw + sx) * 4; result.data.set(image.data.subarray(start, start + 4), (y * w + x) * 4);
    }
    return result;
  }
  function transformAnimation(doc, kind) {
    var info = layout(doc.e); if (!info) return {data: transform(doc.data, kind)};
    if (doc.frameView) {
      if (kind === 'rot' && info.w !== info.h) throw new Error('Use Sprite sheet view to rotate all rectangular frames together.');
      var rect = frameRect(info, doc.frame), result = new ImageData(new Uint8ClampedArray(doc.data.data), doc.w, doc.h);
      var changed = transform(crop(doc.data, rect), kind);
      for (var y = 0; y < rect.h; y++) result.data.set(changed.data.subarray(y * rect.w * 4, (y + 1) * rect.w * 4), ((rect.y + y) * doc.w + rect.x) * 4);
      return {data: result};
    }
    var frames = Array.from({length: info.count}, function (_, i) { return transform(crop(doc.data, physicalRect(info, i)), kind); });
    var meta = settings(doc, info); meta.width = frames[0].width; meta.height = frames[0].height;
    return {data: pack(frames), animation: meta};
  }
  function paintFrame(ctx, source, frame, x, y, w, h) {
    ctx.save(); ctx.imageSmoothingEnabled = false;
    ctx.globalAlpha = 1 - (frame.mix || 0); ctx.drawImage(source, frame.x, frame.y, frame.w, frame.h, x, y, w, h);
    if (frame.mix && frame.next) {
      ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = frame.mix;
      ctx.drawImage(source, frame.next.x, frame.next.y, frame.next.w, frame.next.h, x, y, w, h);
    }
    ctx.restore();
  }
  window.TextureAnimation = {copy: copy, hasOverride: hasOverride, effectiveEntry: effectiveEntry, supported: supported,
    layout: layout, frameRect: frameRect, physicalRect: physicalRect, crop: crop, copyFrame: copyFrame, change: change,
    transformAnimation: transformAnimation, paintFrame: paintFrame};
})();
