/* Service worker for the Groundwater Investigation Toolkit.
 *
 * The toolkit is used in places where the network is a luxury: a chiefdom
 * with one bar of signal, a vehicle between villages, a drilling site with
 * none at all. Everything the app computes already runs in the browser, so
 * the only thing standing between the user and a working tool is whether the
 * files arrived. This worker makes sure they did - once - and then keeps
 * serving them whether or not there is a network.
 *
 * Two rules govern what is cached:
 *
 *   1. Same-origin GETs inside the app's own scope are cached. These are the
 *      app: its HTML, stylesheet, scripts and bundled data tables.
 *
 *   2. Everything else is passed straight through, untouched. That means the
 *      Water Point Data Exchange and the Anthropic API are never intercepted
 *      and never cached - a stale water point inventory read back from disk
 *      would be indistinguishable from a live one, and caching a request that
 *      carries an API key is not something to do by accident.
 */

/* Bump when the precache list below changes. Existing files do not need it:
 * they are revalidated on every load (see the fetch handler), so a deploy
 * reaches users without a version change. */
var VERSION = 'gwt-v2';
var CACHE = VERSION + '-app';

/* Relative to the worker's own directory, so the app works unchanged at a
 * domain root or under a GitHub Pages project path. */
var PRECACHE = [
  './',
  'index.html',
  'manifest.webmanifest',
  'icon.svg',
  'icon-192.png',
  'icon-512.png',
  'icon-maskable-512.png',
  'css/gwt.css',
  'js/support.js',
  'js/gwt-data.js',
  'js/gwt-core.js',
  'js/gwt-charts.js',
  'js/gwt-geolibre.js',
  'js/image-slot.js',
  'js/gwt-docx.js',
  'js/gwt-app.js',
  'user_guide.md',
  'depth-spine.md',
];

self.addEventListener('install', function (event) {
  event.waitUntil((async function () {
    var cache = await caches.open(CACHE);
    /* cache: 'reload' so a precache never copies a stale entry out of the
     * browser's own HTTP cache - the point of this pass is a known-good set. */
    var results = await Promise.allSettled(PRECACHE.map(function (path) {
      return cache.add(new Request(new URL(path, self.registration.scope).href,
        { cache: 'reload' }));
    }));
    var failed = results.filter(function (r) { return r.status === 'rejected'; });
    if (failed.length) {
      /* One missing optional file must not leave the app half-installed and
       * unusable offline; the rest of the shell is cached and works. */
      console.warn('[sw] ' + failed.length + ' of ' + PRECACHE.length +
        ' assets could not be precached');
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', function (event) {
  event.waitUntil((async function () {
    var names = await caches.keys();
    await Promise.all(names.map(function (name) {
      /* only this app's caches, and only the ones this version replaced */
      return name.indexOf('gwt-v') === 0 && name !== CACHE
        ? caches.delete(name) : null;
    }));
    await self.clients.claim();
  })());
});

/* Whether a request is part of the app itself, as opposed to something the
 * app talks to. Only the former is ours to cache. */
function isAppRequest(request) {
  if (request.method !== 'GET') return false;
  var url;
  try { url = new URL(request.url); } catch (e) { return false; }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
  if (url.origin !== self.location.origin) return false;
  /* the stlite build under wasm/ is a 60 MB Python runtime pulled from a CDN;
   * precaching or mirroring it is not something to do behind the user's back */
  if (url.pathname.indexOf(new URL('wasm/', self.registration.scope).pathname) === 0) {
    return false;
  }
  return url.href.indexOf(self.registration.scope) === 0;
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  /* Not calling respondWith leaves the request entirely alone: no cache
   * lookup, no cache write, no worker in the path at all. This is the branch
   * WPdx and the Anthropic API take. */
  if (!isAppRequest(request)) return;

  event.respondWith((async function () {
    var cache = await caches.open(CACHE);
    var cached = await cache.match(request, { ignoreSearch: true });

    /* Revalidate in the background: the user gets the cached file straight
     * away, and the next load gets whatever was deployed since. */
    var network = fetch(request).then(function (response) {
      if (response && response.ok && response.type === 'basic') {
        cache.put(request, response.clone());
      }
      return response;
    }).catch(function () { return null; });

    if (cached) {
      event.waitUntil(network);
      return cached;
    }

    var fresh = await network;
    if (fresh) return fresh;

    /* Offline, and never seen before. A navigation is still answerable - the
     * app is a single page, so the cached shell is the right answer for any
     * in-app URL. Anything else has genuinely failed. */
    if (request.mode === 'navigate') {
      var shell = await cache.match(new URL('index.html', self.registration.scope).href)
        || await cache.match(self.registration.scope);
      if (shell) return shell;
    }
    return new Response(
      'Offline, and this file was never downloaded. Reconnect once and it ' +
      'will be available from then on.',
      { status: 504, statusText: 'Offline', headers: { 'Content-Type': 'text/plain' } });
  })());
});
