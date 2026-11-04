(function () {
  'use strict';
  function encode(image) {
    var pixels = new Uint32Array(image.data.buffer, image.data.byteOffset, image.data.length / 4);
    var runs = [], count = 1, previous = pixels[0];
    for (var i = 1; i <= pixels.length; i++) {
      if (i < pixels.length && pixels[i] === previous) count++;
      else {
        runs.push(count + '.' + previous.toString(16));
        if (i < pixels.length) { previous = pixels[i]; count = 1; }
      }
    }
    return {w: image.width, h: image.height, pixels: runs.join(',')};
  }
  function decode(edit, project) {
    var legacy = typeof edit === 'string';
    var w = legacy ? (project.type === 'skin' ? 64 : project.size) : edit.w;
    var h = legacy ? w : edit.h;
    if (!Number.isInteger(w) || !Number.isInteger(h) || w < 1 || h < 1 || w * h > 67108864) {
      throw new Error('The saved texture has invalid dimensions.');
    }
    var image = new ImageData(w, h), pixels = new Uint32Array(image.data.buffer), offset = 0;
    var encoded = legacy ? edit : edit.pixels;
    if (typeof encoded !== 'string') throw new Error('The saved texture is incomplete.');
    encoded.split(',').forEach(function (run) {
      var parts = run.split('.'), count = Number(parts[0]);
      if (parts.length !== 2 || !Number.isInteger(count) || count < 1 || offset + count > pixels.length || !/^[0-9a-f]{1,8}$/i.test(parts[1])) {
        throw new Error('The saved texture is incomplete.');
      }
      pixels.fill(parseInt(parts[1], 16) >>> 0, offset, offset + count); offset += count;
    });
    if (offset !== pixels.length) throw new Error('The saved texture is incomplete.');
    return image;
  }
  function png(image) {
    var canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
    canvas.getContext('2d').putImageData(image, 0, 0);
    return new Promise(function (resolve, reject) {
      canvas.toBlob(function (blob) { blob ? resolve(blob) : reject(new Error('This texture could not be encoded as a PNG.')); }, 'image/png');
    });
  }
  window.TextureCodec = {encode: encode, decode: decode, png: png};
})();
