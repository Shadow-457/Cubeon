/* World parsing stays off the editor's UI thread. No files leave the browser. */
'use strict';
self.window = self;
importScripts('vendor/fflate.js', 'toolbox-core.js', 'world-tools.js');
self.onmessage = async function (event) {
  try {
    var report = await WorldTools.scanWorld(event.data.files, function (progress, message) { self.postMessage({progress: progress, message: message}); });
    self.postMessage({report: report});
  } catch (error) { self.postMessage({error: error.message}); }
};
