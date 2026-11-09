/* The Xiph encoder runs in an isolated worker and emits Minecraft-ready Vorbis. */
'use strict';
var module = {exports: {}};
importScripts('vendor/vorbis.js');
var library = module.exports;
self.onmessage = function (event) {
  var handle = null;
  try {
    var data = event.data, channels = data.channels;
    if (!channels.length || channels.length > 2 || channels[0].length > data.sampleRate * 180) throw new Error('Audio must be mono/stereo and at most three minutes.');
    handle = library._encoder_init(channels.length, data.sampleRate, .4);
    if (!handle) throw new Error('The Ogg Vorbis encoder could not start.');
    library.cwrap('encoder_set_tag', null, ['number', 'string', 'string'])(handle, 'ENCODER', 'Cubeon Bench');
    library._encoder_stream_init(handle);
    var parts = [];
    function process(length) {
      library._encoder_process(handle, length);
      var n = library._encoder_data_len(handle);
      if (n) { var address = library._encoder_transfer_data(handle); parts.push(new Uint8Array(library.HEAPU8.subarray(address, address + n))); }
    }
    for (var offset = 0; offset < channels[0].length; offset += 4096) {
      var length = Math.min(4096, channels[0].length - offset), pointers = library._encoder_analysis_buffer(handle, length) >>> 2;
      for (var i = 0; i < channels.length; i++) library.HEAPF32.set(channels[i].subarray(offset, offset + length), library.HEAPU32[pointers + i] >>> 2);
      process(length);
    }
    process(0);
    self.postMessage({blob: new Blob(parts, {type: 'audio/ogg'})});
  } catch (error) { self.postMessage({error: error.message}); }
  finally { if (handle) library._encoder_clear(handle); }
};
