/* Bump the version whenever a shipped application asset changes. */
'use strict';
var VERSION = 'cubeon-bench-v2-20261108-21';
var DEVELOPMENT = ['localhost','127.0.0.1','[::1]'].includes(self.location.hostname);
var ROOT = new URL('./', self.location.href);
var SHELL = ['index.html', 'workspace.html', 'entry.js', 'workbench.css', 'app.css', 'studio.css', 'fonts/Inter.ttf', 'minecraft-textures.js', 'textures-manifest.js', 'textures-local.js',
  'local-store.js', 'texture-codec.js', 'texture-animation.js', 'archive.js', 'vendor/fflate.js', 'resource-packs.js',
  'motion.js', 'minecraft-preview.js', 'color-chooser.js', 'animation-controls.js', 'image-import.js', 'image-import.css', 'editor.js', 'ui-dialog.js',
  'workspace.js', 'editor-layout.js', 'app-shell.js', 'manifest.webmanifest', 'icons/bench-logo.png', 'icons/bench-32.png', 'icons/bench-192.png', 'icons/bench-512.png', 'icons/bench-maskable-512.png',
  'landing.html', 'landing.css', 'landing.js', 'vendor/three.module.min.js', 'landing-assets/editor-draw.webp', 'landing-assets/editor-animate.webp', 'landing-assets/editor-preview.webp',
  'textures/block/oak_planks.png', 'textures/block/moss_block.png', 'textures/block/stone.png', 'textures/block/bricks.png', 'textures/entity/player/wide/steve.png',
  'landing-assets/editor-draw-dark.webp', 'landing-assets/editor-animate-dark.webp', 'landing-assets/editor-preview-dark.webp'];
self.addEventListener('install', function (event) {
  // An update waits until the user saves and chooses to reload.
  event.waitUntil(caches.open(VERSION).then(function (cache) {
    return cache.addAll(SHELL.map(function (path) { return new Request(new URL(path, ROOT), {cache: 'reload'}); })).then(function(){if(DEVELOPMENT)return self.skipWaiting();});
  }));
});
self.addEventListener('activate', function (event) {
  event.waitUntil((async function () {
    var names = await caches.keys();
    await Promise.all(names.filter(function (name) { return name.startsWith('cubeon-bench-') && name !== VERSION; }).map(function (name) { return caches.delete(name); }));
    await self.clients.claim();
  })());
});
self.addEventListener('message', function (event) { if (event.data && event.data.type === 'ACTIVATE_UPDATE') self.skipWaiting(); });
function navigationPage(url) {
  if (/\/(?:workspace)(?:\.html)?\/?$/.test(url.pathname)) return 'workspace.html';
  if (/\/landing(?:\.html)?\/?$/.test(url.pathname)) return 'landing.html';
  if (url.pathname === ROOT.pathname || url.pathname === ROOT.pathname.slice(0, -1) ||
      url.pathname === new URL('index.html', ROOT).pathname || url.pathname === new URL('index', ROOT).pathname) return 'index.html';
  return null;
}
self.addEventListener('fetch', function (event) {
  var request = event.request, url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== ROOT.origin || !(url.pathname.startsWith(ROOT.pathname) || url.pathname === ROOT.pathname.slice(0, -1))) return;
  var page = request.mode === 'navigate' ? navigationPage(url) : null;
  if (request.mode === 'navigate' && !page) return;
  if(DEVELOPMENT){
    event.respondWith((async function(){
      var cache=await caches.open(VERSION),key=page?new URL(page,ROOT):request;
      try{var response=await fetch(new Request(request,{cache:'no-store'}));if(response.ok&&(!url.pathname.includes('/textures/')||url.pathname.endsWith('textures-local.js')))await cache.put(key,response.clone());return response;}
      catch(_){return await cache.match(key)||new Response('Offline asset unavailable',{status:503});}
    })());return;
  }
  if (request.mode === 'navigate') {
    // Installed and offline sessions use one consistent app version.
    event.respondWith(caches.open(VERSION).then(function (cache) { return cache.match(new URL(page, ROOT)); }).then(function (response) { return response || fetch(request); })); return;
  }
  event.respondWith((async function () {
    var cache = await caches.open(VERSION), cached = await cache.match(request);
    if (cached) return cached;
    try {
      var response = await fetch(request);
      // Vanilla PNGs are served online; the bundled library supplies them offline.
      return response;
    } catch (_) { return new Response('Offline asset unavailable', {status: 503, headers: {'Content-Type': 'text/plain'}}); }
  })());
});
