/* Retire the old offline editor; saved projects and open tabs stay intact. */
'use strict';
self.addEventListener('install', function (event) {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener('activate', function (event) {
  event.waitUntil((async function () {
    var names = await caches.keys();
    await Promise.all(names.filter(function (name) {
      return name.startsWith('cubeon-bench-');
    }).map(function (name) { return caches.delete(name); }));
    await self.registration.unregister();
  })());
});
