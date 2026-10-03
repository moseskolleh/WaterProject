/* gwt-store.js - where this browser keeps the working session between visits.
 *
 * The session used to be stringified whole into one localStorage key,
 * gwt.project.v1, 400 ms after every change: every workbook as base64 and
 * every photograph as a data URL, some 20 MB of text for a project with fifty
 * photos, rewritten because a caption changed. It stuttered while the user
 * typed and it ran out of room on a real project, at which point nothing was
 * being kept at all.
 *
 * Here the session lives in IndexedDB instead, as records rather than one
 * string:
 *
 *   records  one per top-level field of the state (site, costing, photos...),
 *            with every long base64 string in it - a workbook, a photograph -
 *            replaced by a reference to a Blob;
 *   blobs    those files, as bytes;
 *   cache    the inversion cache, one record per sounding's key;
 *   meta     which tab is writing, and when the last write went in.
 *
 * A write stores only the records whose text has changed since the last one
 * that went in, and only the files it has not stored before, in a single
 * transaction, so the copy on disk is always one whole session and never
 * half of two. The inversion cache is written separately and may be refused
 * without that being a failure: it can always be worked out again, and it
 * must never be what stops the fieldwork being kept.
 *
 * Only one tab writes. It holds a Web Lock for as long as it is open, and
 * every write checks, inside its transaction, that the tab is still the one
 * named as the writer. A second tab opened on the app reads the saved copy
 * and saves nothing until the user asks to carry on there, which moves the
 * writing to it; the first tab is then refused on its next write and says
 * so. Without Web Locks the newest tab takes the writing over when it opens,
 * and the older one is refused the same way. Either way two tabs never
 * interleave their records into one copy that neither of them had.
 *
 * Where IndexedDB is missing or will not open - some private windows, some
 * browsers on file:// - the module says so on every write, and the app
 * reports that it is not saving, as it always has when storage fails. A
 * session left in the old localStorage key by an earlier build is read on the
 * first visit, written here, and removed only once it has been read back; one
 * an earlier build writes there after that is the newer session, and is
 * opened and moved across in its turn (see load).
 */
(function (global) {
  'use strict';

  /** @type {GWTNamespace} */
  var GWT = global.GWT || (global.GWT = {});

  var DB_NAME = 'gwt-project';
  var DB_VERSION = 1;
  var LEGACY_KEY = 'gwt.project.v1';
  var LOCK_NAME = 'gwt-project-writer';
  var CACHE_FIELD = 'inversionCache';
  /* A string at least this long that is base64 is kept as a Blob. Anything
   * shorter costs more as a separate record than it saves. */
  var BLOB_MIN = 16384;

  function storageError(name, message) {
    var err = new Error(message);
    err.name = name;
    return err;
  }

  function newId() {
    if (global.crypto && global.crypto.randomUUID) return global.crypto.randomUUID();
    return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
  }

  /* 'data:image/jpeg;base64,' for a base64 data URL, '' for bare base64
   * under a field named b64, null for anything to keep as text. */
  function base64Head(value, key) {
    if (value.charCodeAt(0) === 100 && value.slice(0, 5) === 'data:') {
      var comma = value.indexOf(',');
      if (comma > 0 && comma < 256 && /;base64$/i.test(value.slice(0, comma))) {
        return value.slice(0, comma + 1);
      }
      return null;
    }
    return key === 'b64' ? '' : null;
  }

  function decodeBase64(text) {
    if (typeof Uint8Array.fromBase64 === 'function') return Uint8Array.fromBase64(text);
    var bin = atob(text);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  /* The bytes back as base64, encoded off the main thread. */
  function blobToBase64(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onerror = function () { reject(reader.error); };
      reader.onload = function () {
        var url = String(reader.result);
        resolve(url.slice(url.indexOf(',') + 1));
      };
      reader.readAsDataURL(blob);
    });
  }

  function blobToText(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onerror = function () { reject(reader.error); };
      reader.onload = function () { resolve(String(reader.result)); };
      reader.readAsText(blob);
    });
  }

  function done(request) {
    return new Promise(function (resolve, reject) {
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error); };
    });
  }

  function finished(tx) {
    return new Promise(function (resolve, reject) {
      tx.oncomplete = function () { resolve(); };
      tx.onabort = function () {
        reject(tx.__reason || tx.error || storageError('AbortError', 'The write was abandoned.'));
      };
    });
  }

  function openDatabase() {
    return new Promise(function (resolve, reject) {
      var request;
      try {
        if (!global.indexedDB) throw storageError('NotSupportedError', 'This browser has no IndexedDB.');
        request = global.indexedDB.open(DB_NAME, DB_VERSION);
      } catch (e) { reject(e); return; }
      request.onupgradeneeded = function () {
        var db = request.result;
        ['meta', 'records', 'blobs', 'cache'].forEach(function (name) {
          if (!db.objectStoreNames.contains(name)) db.createObjectStore(name);
        });
      };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () {
        reject(request.error || storageError('UnknownError', 'IndexedDB would not open.'));
      };
      request.onblocked = function () {
        reject(storageError('UnknownError', 'IndexedDB is held open by an older copy of the app.'));
      };
    });
  }

  function legacyRaw() {
    try { return global.localStorage.getItem(LEGACY_KEY); }
    catch (e) { return null; }
  }

  function legacyParse(raw) {
    if (!raw) return null;
    try {
      var saved = JSON.parse(raw);
      return saved && typeof saved === 'object' ? saved : null;
    } catch (e) { return null; }
  }

  /* The old key's text as its length and a 32-bit FNV-1a hash: enough to
   * tell the copy that was moved from one an earlier build wrote since. */
  function fingerprint(raw) {
    var h = 0x811c9dc5;
    for (var i = 0; i < raw.length; i++) {
      h ^= raw.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return raw.length + ':' + (h >>> 0).toString(16);
  }

  function legacyExists() {
    try { return global.localStorage.getItem(LEGACY_KEY) !== null; }
    catch (e) { return false; }
  }

  function legacyRemove() {
    try { global.localStorage.removeItem(LEGACY_KEY); } catch (e) { /* ignore */ }
  }

  /* create({onLost}) -> the session's storage. onLost() is called when
   * another tab takes the writing over from this one. */
  function create(options) {
    var opts = options || {};
    var tab = newId();
    var mode = 'pending';       // 'indexeddb', or 'none' once it has failed
    var role = 'pending';       // 'writer' or 'reader'
    var openError = null;
    /* set when the stored copy could not be read back: nothing is written
     * over it, since the session in this tab is not the one on disk */
    var damage = null;
    var db = null;
    var persistAsked = null;
    /* set from taking the writing over until the saved session has been
     * read: the state this tab holds meanwhile is the one it had as a
     * reader, older than what is on disk, and is not written over it */
    var adopting = false;
    /* the old localStorage copy load() handed over, as fingerprint() */
    var legacySeen = null;

    /* What the copy on disk holds, as far as this tab wrote or read it. */
    var written = {
      records: new Map(),       // field -> the text of its stored record
      blobIds: new Map(),       // file content -> blob id
      blobs: new Set(),         // blob ids on disk
      texts: new Set(),         // blob ids of text that was not base64
      cache: new Map(),         // cache key -> the entry object stored
    };

    /* What each write did, so a test can see that a changed field wrote its
     * record and nothing else. */
    var stats = { writes: 0, last: null };

    var chain = Promise.resolve();
    function queued(fn) {
      var next = chain.then(fn, fn);
      chain = next.catch(function () {});
      return next;
    }

    function claim() {
      var tx = db.transaction('meta', 'readwrite');
      tx.objectStore('meta').put({ tab: tab, since: Date.now() }, 'writer');
      return finished(tx).then(function () { role = 'writer'; });
    }

    function lost() {
      if (role !== 'writer') return;
      role = 'reader';
      if (opts.onLost) opts.onLost();
    }

    /* Hold the writer's lock until this tab closes or another steals it.
     * Resolves true if it was granted, false if another tab has it. */
    function holdLock(steal) {
      return new Promise(function (resolve) {
        var request = navigator.locks.request(LOCK_NAME,
          steal ? { steal: true } : { ifAvailable: true }, function (lock) {
            if (!lock) { resolve(false); return null; }
            resolve(true);
            return new Promise(function () { /* held for the tab's life */ });
          });
        /* a lock taken by another tab's steal rejects here */
        request.catch(function () { lost(); });
      });
    }

    var ready = openDatabase().then(function (opened) {
      db = opened;
      mode = 'indexeddb';
      /* a newer build that upgrades the database asks every open tab to
       * let go of it; this tab then stops saving and says so */
      db.onversionchange = function () {
        db.close();
        mode = 'none';
        openError = storageError('InvalidStateError',
          'A newer copy of the app has taken over this browser\'s storage.');
      };
      if (global.navigator && navigator.locks && navigator.locks.request) {
        return holdLock(false).then(function (granted) {
          if (granted) return claim();
          role = 'reader';
          return null;
        });
      }
      return claim();
    }).catch(function (e) {
      mode = 'none';
      openError = e;
    });

    /* The state as records: every field but the inversion cache, each with
     * its long base64 strings swapped for blob references. Returns the
     * records and the files not yet on disk. */
    function dehydrate(state) {
      var fresh = new Map();    // file content -> {id, head, refs: [ref objects]}
      function walk(value, key, ids) {
        if (typeof value === 'string') {
          if (value.length < BLOB_MIN) return value;
          var head = base64Head(value, key);
          if (head === null) return value;
          var id = written.blobIds.get(value), ref;
          if (id) {
            ref = written.texts.has(id) ? { $blob: id, text: true } : { $blob: id, head: head };
          } else {
            var pending = fresh.get(value);
            if (!pending) {
              pending = { id: newId(), head: head, refs: [] };
              fresh.set(value, pending);
            }
            ref = { $blob: pending.id, head: head };
            pending.refs.push(ref);
          }
          ids.push(ref.$blob);
          return ref;
        }
        if (Array.isArray(value)) {
          return value.map(function (item) { return walk(item, '', ids); });
        }
        if (value && typeof value === 'object') {
          var out = {};
          Object.keys(value).forEach(function (k) { out[k] = walk(value[k], k, ids); });
          return out;
        }
        return value;
      }
      var records = [];
      Object.keys(state).forEach(function (field) {
        if (field === CACHE_FIELD) return;
        var ids = [];
        records.push({ field: field, value: walk(state[field], field, ids), ids: ids });
      });
      return { records: records, fresh: fresh };
    }

    /* The new files as Blobs. Decoding is on the main thread, so a batch of
     * them - the first write of a migrated project - gives the page a turn
     * between files rather than holding it for all of them at once. */
    async function makeBlobs(fresh) {
      var made = [], since = 0;
      for (var entry of fresh) {
        var content = entry[0], pending = entry[1], blob, isText = false;
        var text = pending.head ? content.slice(pending.head.length) : content;
        try {
          blob = new Blob([decodeBase64(text)]);
        } catch (e) {
          /* not base64 after all: keep it as text, in a Blob all the same */
          blob = new Blob([content], { type: 'text/plain' });
          isText = true;
          pending.refs.forEach(function (ref) { delete ref.head; ref.text = true; });
        }
        made.push({ id: pending.id, content: content, blob: blob, text: isText });
        since += content.length;
        if (since > 2e6) {
          since = 0;
          await new Promise(function (resolve) { setTimeout(resolve, 0); });
        }
      }
      return made;
    }

    /* One readwrite transaction that first checks, inside itself, that this
     * tab is still the one named as the writer, and only then runs fill(tx).
     * Resolves once it has committed. A put that throws - a value that
     * cannot be stored, or quota reported at once - abandons all of it. */
    function asWriter(names, fill) {
      var tx = db.transaction(names, 'readwrite');
      var outcome = finished(tx);
      var check = tx.objectStore('meta').get('writer');
      check.onsuccess = function () {
        try {
          if (!check.result || check.result.tab !== tab) {
            throw storageError('OpenElsewhereError',
              'This project is being saved by another tab.');
          }
          fill(tx);
        } catch (e) {
          tx.__reason = e;
          try { tx.abort(); } catch (ignore) { /* already finished */ }
        }
      };
      return outcome.catch(function (e) {
        if (e && e.name === 'OpenElsewhereError') lost();
        throw e;
      });
    }

    function refused() {
      if (damage) return damage;
      if (mode !== 'indexeddb') {
        return openError || storageError('NotSupportedError', 'IndexedDB is not available.');
      }
      if (role !== 'writer') {
        return storageError('OpenElsewhereError',
          'This project is being saved by another tab.');
      }
      return null;
    }

    /* Write what has changed. `state` is the session, or a function that
     * returns it when this write's turn comes. Resolves once it is on disk;
     * rejects, leaving the copy on disk exactly as it was, if anything in it
     * was refused. */
    function write(source) {
      return queued(async function () {
        await ready;
        var no = refused();
        if (no) throw no;
        if (adopting) return { records: [], removed: [], blobs: 0, orphans: 0,
          cache: 0, cacheRemoved: 0, skipped: true };
        var state = typeof source === 'function' ? source() : source;
        var plan = dehydrate(state);
        var made = plan.fresh.size ? await makeBlobs(plan.fresh) : [];
        var puts = [], texts = new Map(), live = new Set();
        plan.records.forEach(function (record) {
          var text = JSON.stringify(record.value);
          texts.set(record.field, text);
          record.ids.forEach(function (id) { live.add(id); });
          if (written.records.get(record.field) !== text) puts.push(record);
        });
        var gone = [];
        written.records.forEach(function (text, field) {
          if (!texts.has(field)) gone.push(field);
        });
        var orphans = [];
        written.blobs.forEach(function (id) { if (!live.has(id)) orphans.push(id); });

        var cachePlan = cacheChanges(state[CACHE_FIELD]);
        var summary = { records: puts.map(function (r) { return r.field; }),
          removed: gone, blobs: made.length, orphans: orphans.length,
          cache: cachePlan.puts.length, cacheRemoved: cachePlan.gone.length };

        if (puts.length || gone.length || made.length || orphans.length) {
          await asWriter(['meta', 'records', 'blobs'], function (tx) {
            var records = tx.objectStore('records'), blobs = tx.objectStore('blobs');
            made.forEach(function (m) { blobs.put(m.blob, m.id); });
            puts.forEach(function (r) { records.put(r.value, r.field); });
            gone.forEach(function (field) { records.delete(field); });
            orphans.forEach(function (id) { blobs.delete(id); });
            tx.objectStore('meta').put({ at: Date.now(), tab: tab }, 'saved');
          });
          made.forEach(function (m) {
            written.blobIds.set(m.content, m.id);
            written.blobs.add(m.id);
            if (m.text) written.texts.add(m.id);
          });
          orphans.forEach(function (id) {
            written.blobs.delete(id);
            written.texts.delete(id);
          });
          written.blobIds.forEach(function (id, content) {
            if (!written.blobs.has(id)) written.blobIds.delete(content);
          });
          puts.forEach(function (r) { written.records.set(r.field, texts.get(r.field)); });
          gone.forEach(function (field) { written.records.delete(field); });
          /* asked once the session holds a file, which is when being
           * cleared under pressure would cost something; Firefox asks the
           * user, and a blank first visit is no time for that */
          if (made.length) askToPersist();
        }
        await writeCache(cachePlan);
        stats.writes += 1;
        stats.last = summary;
        return summary;
      });
    }

    function cacheChanges(cache) {
      var puts = [], gone = [];
      cache = cache && typeof cache === 'object' ? cache : {};
      Object.keys(cache).forEach(function (key) {
        if (written.cache.get(key) !== cache[key]) puts.push([key, cache[key]]);
      });
      written.cache.forEach(function (entry, key) {
        if (!Object.prototype.hasOwnProperty.call(cache, key)) gone.push(key);
      });
      return { puts: puts, gone: gone };
    }

    /* The inversion cache, apart. Refused - most likely for want of room -
     * it is simply not kept: the next write offers it again, and a reload
     * without it inverts the survey once more. Another tab having taken the
     * writing over is a refusal like any other. */
    async function writeCache(plan) {
      if (!plan.puts.length && !plan.gone.length) return;
      try {
        await asWriter(['meta', 'cache'], function (tx) {
          var store = tx.objectStore('cache');
          plan.puts.forEach(function (pair) { store.put(pair[1], pair[0]); });
          plan.gone.forEach(function (key) { store.delete(key); });
        });
        plan.puts.forEach(function (pair) { written.cache.set(pair[0], pair[1]); });
        plan.gone.forEach(function (key) { written.cache.delete(key); });
      } catch (e) {
        if (e && e.name === 'OpenElsewhereError') throw e;
        if (global.console) console.warn('The inversion cache was not kept:', e && e.name);
      }
    }

    function askToPersist() {
      if (persistAsked || !global.navigator || !navigator.storage ||
          !navigator.storage.persist) return;
      persistAsked = navigator.storage.persist().catch(function () { return false; });
    }

    /* Read the stored session back. prime: this tab takes what it read as
     * what is on disk, so the next write stores only what changes after. */
    async function readBack(prime) {
      var tx = db.transaction(['meta', 'records', 'blobs', 'cache'], 'readonly');
      var saved = done(tx.objectStore('meta').get('saved'));
      /* each of these is a request, and then, awaited into the same name,
       * what it read */
      /** @type {any} */
      var fields = done(tx.objectStore('records').getAllKeys());
      /** @type {any} */
      var values = done(tx.objectStore('records').getAll());
      /** @type {any} */
      var blobKeys = done(tx.objectStore('blobs').getAllKeys());
      /** @type {any} */
      var blobValues = done(tx.objectStore('blobs').getAll());
      /** @type {any} */
      var cacheKeys = done(tx.objectStore('cache').getAllKeys());
      /** @type {any} */
      var cacheValues = done(tx.objectStore('cache').getAll());
      await finished(tx);
      if (!(await saved)) return null;
      fields = await fields; values = await values;
      blobKeys = await blobKeys; blobValues = await blobValues;
      var blobs = new Map();
      blobKeys.forEach(function (id, i) { blobs.set(id, blobValues[i]); });

      var needed = new Map();   // blob id -> whether it holds text, not bytes
      function collect(value) {
        if (Array.isArray(value)) { value.forEach(collect); return; }
        if (value && typeof value === 'object') {
          if (typeof value.$blob === 'string') {
            needed.set(value.$blob, !!value.text);
            return;
          }
          Object.keys(value).forEach(function (k) { collect(value[k]); });
        }
      }
      values.forEach(collect);
      var decoded = new Map();
      await Promise.all(Array.from(needed.keys()).map(async function (id) {
        var blob = blobs.get(id);
        if (!blob) {
          throw storageError('DataError', 'The saved session names a file it does not hold.');
        }
        decoded.set(id, needed.get(id) ? await blobToText(blob) : await blobToBase64(blob));
      }));
      var byId = new Map();
      function rehydrate(value) {
        if (Array.isArray(value)) return value.map(rehydrate);
        if (value && typeof value === 'object') {
          if (typeof value.$blob === 'string') {
            var text = value.text ? decoded.get(value.$blob)
              : (value.head || '') + decoded.get(value.$blob);
            byId.set(value.$blob, text);
            return text;
          }
          var out = {};
          Object.keys(value).forEach(function (k) { out[k] = rehydrate(value[k]); });
          return out;
        }
        return value;
      }
      var state = {};
      fields.forEach(function (field, i) { state[field] = rehydrate(values[i]); });
      cacheKeys = await cacheKeys; cacheValues = await cacheValues;
      var cache = {};
      cacheKeys.forEach(function (key, i) { cache[key] = cacheValues[i]; });
      state[CACHE_FIELD] = cache;

      if (prime) {
        written.records = new Map();
        fields.forEach(function (field, i) {
          written.records.set(field, JSON.stringify(values[i]));
        });
        written.blobIds = new Map();
        byId.forEach(function (text, id) { written.blobIds.set(text, id); });
        written.blobs = new Set(blobKeys);
        written.texts = new Set();
        needed.forEach(function (isText, id) { if (isText) written.texts.add(id); });
        written.cache = new Map();
        Object.keys(cache).forEach(function (key) { written.cache.set(key, cache[key]); });
      }
      return state;
    }

    /* The saved session: {state, from} where from is 'indexeddb', or
     * 'localStorage' for a session an earlier build left there, not yet
     * moved (see retireLegacy); null when there is none.
     *
     * Both can be there. The copy here was moved from the old key, which
     * then went, or was kept because the move did not read back; the old
     * key's fingerprint was recorded either way. An old key that does not
     * match it was written after the move, by an earlier build opened on
     * this browser since, and is the newer session of the two: it is the
     * one opened, and moved across again. */
    function load() {
      return queued(async function () {
        await ready;
        adopting = false;
        var raw = legacyRaw();
        if (mode === 'indexeddb') {
          var state;
          try {
            state = await readBack(true);
          } catch (e) {
            damage = e;
            throw e;
          }
          if (state) {
            if (raw === null) return { state: state, from: 'indexeddb' };
            var print = fingerprint(raw);
            var moved = await done(db.transaction('meta', 'readonly')
              .objectStore('meta').get('legacy'));
            var newer = moved === print ? null : legacyParse(raw);
            if (!newer) {
              if (role === 'writer' && moved === print) legacyRemove();
              return { state: state, from: 'indexeddb' };
            }
            legacySeen = print;
            return { state: newer, from: 'localStorage' };
          }
        }
        var legacy = legacyParse(raw);
        legacySeen = legacy ? fingerprint(raw) : null;
        return legacy ? { state: legacy, from: 'localStorage' } : null;
      });
    }

    /* Remove the old localStorage copy, once the copy here has been read
     * back and is `expected`, the session as it was moved across. Resolves
     * true if it was removed. Its fingerprint is recorded first, removed or
     * not, so that load() can tell it from one an earlier build writes
     * later; and it is left if it has changed since load() read it. */
    function retireLegacy(expected) {
      return queued(async function () {
        await ready;
        if (mode !== 'indexeddb' || role !== 'writer' || !legacyExists()) return false;
        var copy = null;
        try {
          if (legacySeen) {
            var seen = legacySeen;
            await asWriter(['meta'], function (tx) { tx.objectStore('meta').put(seen, 'legacy'); });
          }
          copy = await readBack(false);
        } catch (e) { return false; }
        var complete = !!copy && Object.keys(expected).every(function (field) {
          return field === CACHE_FIELD || same(copy[field], expected[field]);
        });
        if (!complete) return false;
        var raw = legacyRaw();
        if (raw === null || fingerprint(raw) !== legacySeen) return false;
        legacyRemove();
        return true;
      });
    }

    /* Deep equality of two JSON-shaped values, without stringifying twenty
     * megabytes of photographs to find it out. */
    function same(a, b) {
      if (a === b) return true;
      if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
      if (Array.isArray(a) !== Array.isArray(b)) return false;
      var ka = Object.keys(a), kb = Object.keys(b);
      if (ka.length !== kb.length) return false;
      return ka.every(function (k) {
        return Object.prototype.hasOwnProperty.call(b, k) && same(a[k], b[k]);
      });
    }

    /* Whether a copy from an earlier write can still be read. */
    function hasCopy() {
      return queued(async function () {
        await ready;
        if (db) {
          try {
            var tx = db.transaction('meta', 'readonly');
            if (await done(tx.objectStore('meta').get('saved'))) return true;
          } catch (e) { /* fall through to the old copy */ }
        }
        return legacyExists();
      });
    }

    /* Delete the stored session, and any copy an earlier build left. This is
     * also the way out of a stored copy that could not be read back. */
    function clear() {
      return queued(async function () {
        await ready;
        legacyRemove();
        var no = mode === 'indexeddb' && role === 'writer' ? null : refused();
        if (no) throw no;
        await asWriter(['meta', 'records', 'blobs', 'cache'], function (tx) {
          tx.objectStore('meta').delete('saved');
          ['records', 'blobs', 'cache'].forEach(function (name) { tx.objectStore(name).clear(); });
        });
        written.records = new Map();
        written.blobIds = new Map();
        written.blobs = new Set();
        written.texts = new Set();
        written.cache = new Map();
        damage = null;
      });
    }

    /* Make this tab the one that writes, taking it from whichever tab has
     * it. The caller reads the saved session again afterwards: what this tab
     * holds may be older than what the other tab wrote. */
    function takeOver() {
      return queued(async function () {
        await ready;
        if (mode !== 'indexeddb') throw refused();
        if (role === 'writer') return;
        if (global.navigator && navigator.locks && navigator.locks.request) {
          await holdLock(true);
        }
        await claim();
        /* until load() has read what the other tab saved */
        adopting = true;
      });
    }

    /* How much this origin keeps and may keep, and whether the browser has
     * agreed not to clear it under pressure. Any part may be null. */
    async function estimate() {
      await ready;
      var out = { usage: null, quota: null, persisted: null, mode: mode, role: role };
      var storage = global.navigator && navigator.storage;
      if (!storage) return out;
      try {
        if (storage.estimate) {
          var e = await storage.estimate();
          out.usage = e.usage; out.quota = e.quota;
        }
        if (storage.persisted) out.persisted = await storage.persisted();
      } catch (e) { /* leave what could not be read as null */ }
      return out;
    }

    return {
      ready: ready,
      write: write, load: load, hasCopy: hasCopy, clear: clear,
      retireLegacy: retireLegacy, takeOver: takeOver, estimate: estimate,
      /* the stored session as it would load, without touching what this tab
       * believes is on disk; for checks */
      readBack: function () {
        return queued(async function () {
          await ready;
          return mode === 'indexeddb' ? readBack(false) : null;
        });
      },
      stats: stats,
      get mode() { return mode; },
      get role() { return role; },
      get error() { return openError; },
      LEGACY_KEY: LEGACY_KEY,
    };
  }

  GWT.storage = { create: create, DB_NAME: DB_NAME, LEGACY_KEY: LEGACY_KEY };
}(typeof window !== 'undefined' ? window : globalThis));
