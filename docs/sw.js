/* Service worker for the Groundwater Investigation Toolkit.
 *
 * GENERATED FILE - do not edit. The source of truth is the app shell under
 * docs/; regenerate with:
 *
 *     python web/build_offline.py
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

/* A hash of the precached files, not a number someone bumps by hand. Change
 * any byte of the shell and this changes with it, so the browser fetches the
 * new worker and drops the old cache; forget to change it and a device keeps
 * serving last month's app with nothing to show that it is doing so. */
var VERSION = 'gwt-vde5b8940ec3e';
/* The release: exactly what install put on disk, and nothing else. Only the
 * install handler ever writes to it. */
var CACHE = VERSION + '-app';
/* Everything else in scope that the app asks for and the release does not
 * carry. Versioned too, so a new release starts with an empty one rather than
 * inheriting answers fetched against the shell it replaced. */
var RUNTIME = VERSION + '-runtime';

/* Relative to the worker's own directory, so the app works unchanged at a
 * domain root or under a GitHub Pages project path. In the order a browser
 * meets them: the page, the links in its head, the icons the manifest names,
 * the faces the stylesheet loads, then the scripts. A precache interrupted
 * part way therefore leaves the most useful part on disk. */
var PRECACHE = [
  './',
  'index.html',
  'manifest.webmanifest',
  'icon-192.png',
  'css/gwt.css',
  'icon.svg',
  'icon-512.png',
  'icon-maskable-512.png',
  'fonts/space-grotesk-latin.woff2',
  'fonts/inter-latin.woff2',
  'fonts/ibm-plex-mono-latin-400.woff2',
  'fonts/ibm-plex-mono-latin-500.woff2',
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
     * browser's own HTTP cache - the point of this pass is a known-good set.
     *
     * addAll rather than a tolerated pass of individual adds: a release is
     * all of these files or it is none of them. If one cannot be fetched the
     * install fails, this worker never activates, and whatever the device
     * already had keeps serving. Half a release installed is the worst of
     * both - an app that looks updated and is missing a page - and the build
     * script has already checked that every one of these files exists, so a
     * failure here means a deploy that genuinely did not arrive. */
    try {
      await cache.addAll(PRECACHE.map(function (path) {
        return new Request(new URL(path, self.registration.scope).href,
          { cache: 'reload' });
      }));
    } catch (e) {
      /* Opening the cache created it, so a release that could not be fetched
       * would otherwise leave an empty one behind under its own name, to be
       * swept by whichever release eventually succeeds. Take it back out: a
       * release that did not arrive should leave no trace that it tried. */
      await caches.delete(CACHE);
      throw e;
    }
    /* No skipWaiting: a tab that is open keeps the release it started with.
     * Swapping the engine under a page that is half way through a recompute
     * is how one app ends up running two releases at once. The new worker
     * waits, the app says so, and the next open is the new release. */
  })());
});

self.addEventListener('activate', function (event) {
  event.waitUntil((async function () {
    var names = await caches.keys();
    await Promise.all(names.map(function (name) {
      /* only this app's caches, and only the ones this version replaced */
      return name.indexOf('gwt-v') === 0 && name !== CACHE && name !== RUNTIME
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

/* Whether this request is for a file the release itself carries.
 *
 * A navigation counts whatever its path: the app is a single page, so the
 * release's index.html is the right answer for any in-app URL. */
var RELEASE_PATHS = null;
function isReleaseRequest(request) {
  if (request.mode === 'navigate') return true;
  if (!RELEASE_PATHS) {
    RELEASE_PATHS = {};
    PRECACHE.forEach(function (path) {
      RELEASE_PATHS[new URL(path, self.registration.scope).pathname] = true;
    });
  }
  var url;
  try { url = new URL(request.url); } catch (e) { return false; }
  return RELEASE_PATHS[url.pathname] === true;
}

function offline() {
  return new Response(
    'Offline, and this file was never downloaded. Reconnect once and it ' +
    'will be available from then on.',
    { status: 504, statusText: 'Offline', headers: { 'Content-Type': 'text/plain' } });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  /* Not calling respondWith leaves the request entirely alone: no cache
   * lookup, no cache write, no worker in the path at all. This is the branch
   * WPdx and the Anthropic API take. */
  if (!isAppRequest(request)) return;

  event.respondWith((async function () {
    if (isReleaseRequest(request)) {
      /* Served from the release, and the release is never written to here.
       *
       * This used to revalidate in the background and put the answer back
       * into the versioned cache, which quietly undid the thing the whole
       * design is for. Every page load rewrote the running release's files
       * one at a time from whatever was on the server, so a deploy that was
       * half uploaded became the app a file at a time, under the old
       * release's identifier and without an install ever succeeding - the
       * exact failure the addAll in install refuses. A release changes only
       * by a new worker installing a new one whole. */
      var cache = await caches.open(CACHE);
      var hit = await cache.match(request, { ignoreSearch: true });
      if (hit) return hit;
      if (request.mode === 'navigate') {
        var shell = await cache.match(new URL('index.html', self.registration.scope).href)
          || await cache.match(self.registration.scope);
        if (shell) return shell;
      }
      /* Named in the shell but not on disk: this device is running an older
       * release that never carried it. Ask the network, and still do not
       * write the answer into a release that does not contain it. */
      var live = await fetch(request).catch(function () { return null; });
      return live || offline();
    }

    /* In scope, but not part of the release - so there is no release to
     * damage, and ordinary revalidation is the right behaviour. */
    var runtime = await caches.open(RUNTIME);
    var cached = await runtime.match(request, { ignoreSearch: true });
    var network = fetch(request).then(function (response) {
      if (response && response.ok && response.type === 'basic') {
        runtime.put(request, response.clone());
      }
      return response;
    }).catch(function () { return null; });

    if (cached) {
      event.waitUntil(network);
      return cached;
    }
    var fresh = await network;
    return fresh || offline();
  })());
});
