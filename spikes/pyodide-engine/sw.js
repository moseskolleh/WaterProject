/* sw.js - the spike's precache, so its starts are timed as a field device
 * would see them once the app is installed: every file from Cache Storage,
 * none from the network.
 *
 * It mirrors what docs/sw.js does for the app (addAll at install, cache
 * first after) and nothing else. measure.mjs serves it at /sw.js with scope
 * /, over the spike's files and the app's engine scripts the comparison
 * runs; the list comes from vendor/manifest.json, which build.py writes.
 */
'use strict';

var CACHE = 'pyodide-spike-v1';

/* The bench page and both engines: the JavaScript one the app ships, and
 * the Pyodide one with everything it fetches. */
var SHELL = [
  '/spike/bench.html',
  '/spike/pyodide-worker.js',
  '/app/js/support.js',
  '/app/js/gwt-data.js',
  '/app/js/gwt-samples.js',
  '/app/js/gwt-core.js',
  '/app/js/gwt-worker.js',
];

self.addEventListener('install', function (event) {
  event.waitUntil((async function () {
    var manifest = await (await fetch('/spike/vendor/manifest.json')).json();
    var urls = SHELL.concat(manifest.files.map(function (f) {
      return '/spike/vendor/' + f.url;
    }));
    var cache = await caches.open(CACHE);
    await cache.addAll(urls);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', function (event) {
  event.respondWith(caches.match(event.request).then(function (hit) {
    return hit || fetch(event.request);
  }));
});
