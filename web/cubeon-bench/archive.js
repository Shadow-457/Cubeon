(function () {
  'use strict';
  var LIMIT = 536870912;
  function safePath(path) {
    return typeof path === 'string' && path.length <= 1024 && !/[\x00-\x1f\\]/.test(path) &&
      !path.startsWith('/') && !/^[A-Za-z]:/.test(path) && !path.split('/').some(function (part) { return part === '..' || part === '.'; });
  }
  function check(bytes) {
    if (bytes.length > 268435456) throw new Error('Choose a ZIP smaller than 256 MB.');
    var view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), end = -1;
    for (var i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
      if (view.getUint32(i, true) === 0x06054b50 && i + 22 + view.getUint16(i + 20, true) === bytes.length) { end = i; break; }
    }
    if (end < 0) throw new Error('This file is not a complete ZIP archive.');
    var count = view.getUint16(end + 10, true), offset = view.getUint32(end + 16, true), total = 0;
    if (view.getUint16(end + 4, true) || view.getUint16(end + 6, true) || count > 16000 || count === 65535) throw new Error('Split, ZIP64, or very large archives are not supported.');
    for (var n = 0; n < count; n++) {
      if (offset + 46 > end || view.getUint32(offset, true) !== 0x02014b50) throw new Error('The ZIP file directory is damaged.');
      if (view.getUint16(offset + 8, true) & 1) throw new Error('Password-protected ZIPs are not supported.');
      total += view.getUint32(offset + 24, true);
      if (total > LIMIT) throw new Error('The expanded ZIP exceeds the 512 MB workspace limit.');
      offset += 46 + view.getUint16(offset + 28, true) + view.getUint16(offset + 30, true) + view.getUint16(offset + 32, true);
    }
    if (offset !== end) throw new Error('The ZIP file directory is damaged.');
  }
  async function read(input) {
    var bytes = input instanceof Uint8Array ? input : new Uint8Array(await input.arrayBuffer()); check(bytes);
    return new Promise(function (resolve, reject) {
      fflate.unzip(bytes, function (error, files) {
        if (error) { reject(new Error('This ZIP could not be opened.')); return; }
        var normalized = Object.create(null), total = 0;
        try {
          Object.keys(files).forEach(function (original) {
            var path = original.replace(/\\/g, '/');
            if (!safePath(path)) throw new Error('The ZIP contains an invalid file path.');
            if (path.endsWith('/')) return;
            if (Object.prototype.hasOwnProperty.call(normalized, path)) throw new Error('The ZIP contains duplicate files.');
            total += files[original].length; if (total > LIMIT) throw new Error('The expanded ZIP is too large.');
            normalized[path] = files[original];
          }); resolve(normalized);
        } catch (failure) { reject(failure); }
      });
    });
  }
  function write(files) {
    var input = Object.create(null);
    Object.keys(files).sort().forEach(function (path) {
      if (!safePath(path)) throw new Error('Cannot export an invalid file path.');
      input[path] = [files[path], {level: /\.(png|jpg|jpeg|ogg|mp3|zip|bin)$/i.test(path) ? 0 : 6}];
    });
    return new Promise(function (resolve, reject) { fflate.zip(input, function (error, bytes) { error ? reject(error) : resolve(new Blob([bytes], {type: 'application/zip'})); }); });
  }
  function download(blob, name) {
    var url = URL.createObjectURL(blob), anchor = document.createElement('a');
    anchor.href = url; anchor.download = name.replace(/[\\/:*?"<>|\x00-\x1f]/g, '').trim() || 'Cubeon download';
    document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
  }
  window.BenchArchive = {read: read, write: write, download: download, safePath: safePath};
})();
