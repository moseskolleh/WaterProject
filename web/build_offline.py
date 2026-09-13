"""Generate the service worker that keeps the web app working offline.

The toolkit is used where the network is a luxury: a chiefdom with one
bar of signal, a vehicle between villages, a drilling site with none at
all. Everything the app computes already runs in the browser, so the
only thing standing between a user and a working tool is whether the
files arrived. ``docs/sw.js`` is what makes sure they did - once - and
the list it precaches has to be the app's real file list, not a list
someone remembered to update.

That is what this script is for. It reads the app shell the way a
browser does - the scripts and stylesheet ``docs/index.html`` loads, the
fonts the stylesheet loads, the icons the manifest names - and emits a
worker whose precache list is exactly those files. A script added to
``index.html`` is precached by the next run; nobody has to remember.

The release identifier is a hash of the shell rather than a number
somebody bumps by hand, for the same reason: a forgotten bump is a
device that keeps serving last month's app with no sign anything is
wrong. Change any precached byte and the identifier changes with it.

Run from the repository root, after ``web/build_webapp_data.py`` (the
bundled data is part of the shell, so its hash feeds this one):

    python web/build_offline.py             # write docs/sw.js
    python web/build_offline.py --check     # verify it, don't rewrite

``--check`` is what CI uses to keep the committed worker honest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
OUT = DOCS / "sw.js"

# Files the app does not load itself but that a reader offline still wants:
# the guide is published beside the app on Pages, and a device that installed
# the toolkit in town should be able to read it at the borehole.
EXTRA = [
    "user_guide.md",
    "depth-spine.md",
]

# Never precached, whatever references it. The stlite build under wasm/ is a
# 60 MB Python runtime pulled from a CDN; putting it on someone's phone
# without asking is not a decision this script gets to make. The service
# worker's own fetch handler refuses it at runtime too.
EXCLUDE_PREFIXES = ("wasm/",)


class ShellError(Exception):
    """The shell could not be read the way a browser would read it."""


def _is_local(url: str) -> bool:
    """Whether a URL names a file in docs/ rather than a remote or inline one."""
    if not url or url.startswith(("data:", "blob:", "#", "//")):
        return False
    return "://" not in url


def _normalise(base: Path, url: str) -> str:
    """Resolve a reference found in ``base`` to a path relative to docs/."""
    target = (base.parent / url.split("?")[0].split("#")[0]).resolve()
    try:
        return target.relative_to(DOCS.resolve()).as_posix()
    except ValueError as exc:  # a ../ that climbs out of the published site
        raise ShellError(f"{url!r} in {base.name} points outside docs/") from exc


def shell_assets() -> list[str]:
    """Every same-origin file the app shell loads, in the order a browser meets it.

    Order is not cosmetic: the precache runs in this order, so the markup and
    the links in its head land before the fonts and the megabyte of engine,
    and a precache interrupted part way leaves the most useful part on disk.
    """
    index = DOCS / "index.html"
    if not index.exists():
        raise ShellError(f"{index} is missing; there is no app to cache")
    html = index.read_text(encoding="utf-8")

    paths: list[str] = ["./", "index.html"]

    # <link href> in the head: the manifest, the touch icon, the stylesheet.
    # Taken in document order so the sheet arrives with the markup.
    for href in re.findall(r'<link\b[^>]*\bhref="([^"]+)"', html):
        if _is_local(href):
            paths.append(_normalise(index, href))

    # The icons the manifest names. A PWA installed from the launcher shows
    # these before any script has run, so they belong in the shell.
    manifest = DOCS / "manifest.webmanifest"
    if manifest.exists():
        icons = json.loads(manifest.read_text(encoding="utf-8")).get("icons", [])
        for icon in icons:
            src = icon.get("src", "")
            if _is_local(src):
                paths.append(_normalise(manifest, src))

    # The faces the stylesheet loads. A missing font is not a broken app, but
    # it is a page that reflows the first time it is opened without a network.
    for sheet in sorted(DOCS.glob("css/*.css")):
        css = sheet.read_text(encoding="utf-8")
        for url in re.findall(r'url\(\s*["\']?([^"\')]+)["\']?\s*\)', css):
            if _is_local(url):
                paths.append(_normalise(sheet, url))

    # <script src> in body order: support, data, engine, charts, app.
    for src in re.findall(r'<script\b[^>]*\bsrc="([^"]+)"', html):
        if _is_local(src):
            paths.append(_normalise(index, src))

    paths.extend(EXTRA)

    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path in seen or path.startswith(EXCLUDE_PREFIXES):
            continue
        seen.add(path)
        ordered.append(path)

    missing = [p for p in ordered if p != "./" and not (DOCS / p).exists()]
    if missing:
        raise ShellError(
            "the shell references files that are not in docs/: "
            + ", ".join(missing)
        )
    return ordered


def release_id(paths: list[str]) -> str:
    """A release identifier that changes when any precached byte changes.

    Hashing the shell rather than counting releases by hand is what makes an
    update actually reach a device: the worker script differs from the one
    the browser holds, so the browser fetches the new one, and the old cache
    is dropped on activate. A version nobody remembered to bump looks
    identical to the browser, and the device keeps last month's app.
    """
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        # './' is index.html under another name; hashing it twice is harmless
        # and keeps the loop free of a special case.
        source = DOCS / ("index.html" if path == "./" else path)
        digest.update(hashlib.sha256(source.read_bytes()).digest())
    # The 'gwt-v' prefix is load-bearing: activate() sweeps caches by it, so
    # the worker that replaces a 'gwt-v3-app' cache has to be recognisable to
    # itself as the same app.
    return "gwt-v" + digest.hexdigest()[:12]


WORKER = """/* Service worker for the Groundwater Investigation Toolkit.
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
var VERSION = '__VERSION__';
var CACHE = VERSION + '-app';

/* Relative to the worker's own directory, so the app works unchanged at a
 * domain root or under a GitHub Pages project path. In the order a browser
 * meets them: the page, the links in its head, the icons the manifest names,
 * the faces the stylesheet loads, then the scripts. A precache interrupted
 * part way therefore leaves the most useful part on disk. */
var PRECACHE = [
__PRECACHE__
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
"""


def render(paths: list[str]) -> str:
    """The worker source for this shell."""
    listing = "\n".join(f"  '{path}'," for path in paths)
    return WORKER.replace("__VERSION__", release_id(paths)).replace(
        "__PRECACHE__", listing)


def write_atomically(path: Path, text: str) -> None:
    """Replace ``path`` in one step, or leave what is there untouched.

    A worker truncated half way through a write is a release that precaches
    nothing and shadows the one that worked. The rename is the commit.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="compare the committed worker against a fresh run instead of "
             "rewriting it; exit non-zero if it is out of date",
    )
    args = parser.parse_args()

    try:
        paths = shell_assets()
    except ShellError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    fresh = render(paths)

    if args.check:
        if not OUT.exists():
            print(f"{OUT} is missing; run this without --check to create it")
            return 1
        if OUT.read_text(encoding="utf-8") == fresh:
            print(f"{OUT} is current ({len(paths)} files precached)")
            return 0
        print(f"{OUT} is out of date. Regenerate it with:\n"
              "  python web/build_offline.py")
        return 1

    write_atomically(OUT, fresh)
    version = re.search(r"var VERSION = '([^']+)'", fresh).group(1)
    size_kb = sum(
        (DOCS / ("index.html" if p == "./" else p)).stat().st_size for p in paths
    ) / 1024
    print(f"wrote {OUT} (release {version})")
    print(f"  precaches {len(paths)} files, {size_kb:.0f} KB of app shell")
    print(f"  scripts: {', '.join(p for p in paths if p.endswith('.js'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
