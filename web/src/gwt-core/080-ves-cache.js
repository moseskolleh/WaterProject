
  /* ======================================================= inversion cache
   * ves/cache.py. An inversion is fully determined by the readings, the VES
   * settings and the code that runs it, so each result is saved in the
   * project under the SHA-256 of all three, and reopening a survey does not
   * invert it again. It is a cache, not a source of truth: the key is worked
   * out afresh from the sounding in hand, an entry carries a digest of its own
   * content under that key, and only the model and what the search alone
   * knows are stored - the rest is rebuilt by restoreInversion, and the
   * misfit has to be the one the search recorded. A changed reading, a
   * changed setting or a different engine finds no entry; a damaged or
   * hand-edited one is ignored. The digest catches accident, not a forger:
   * there is no secret to sign with in a file anybody can open.
   *
   * The engine is this file, named by the release and a digest of its source
   * that build_webapp_data.py writes into gwt-data.js, because the release
   * number moves only at a release and a fix between two must not be
   * answered with the old code's result. The Python engine keeps entries of
   * its own under its own name: the two agree to a tolerance, not to the
   * bit, so neither ever reads the other's, and the key is canonical within
   * this engine only. Worker and page run this same file, and smoke.mjs
   * holds them to the same answer to the last bit, so they share one cache. */

  /* 2: the entry records why the fit stopped */
  var INVERSION_CACHE_FORMAT = 2;

  /* SHA-256 of a string's UTF-8 bytes, or of the bytes themselves, as hex.
   * Written out because crypto.subtle answers only asynchronously and only
   * in a secure context, and a copy of the app opened from a laptop's disk
   * or a LAN address is not always one. */
  var SHA256_K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];

  /**
   * @param {string|Uint8Array} text
   * @returns {string}
   */
  function sha256Hex(text) {
    var bytes = ArrayBuffer.isView(text)
      ? new Uint8Array(text.buffer, text.byteOffset, text.byteLength)
      : new TextEncoder().encode(String(text));
    var n = bytes.length;
    var padded = new Uint8Array(((n + 9 + 63) >> 6) << 6);
    padded.set(bytes);
    padded[n] = 0x80;
    var view = new DataView(padded.buffer);
    view.setUint32(padded.length - 8, Math.floor(n / 0x20000000));
    view.setUint32(padded.length - 4, (n * 8) >>> 0);
    var hash = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var w = new Uint32Array(64);
    function rotr(x, r) { return (x >>> r) | (x << (32 - r)); }
    for (var block = 0; block < padded.length; block += 64) {
      var t;
      for (t = 0; t < 16; t++) w[t] = view.getUint32(block + 4 * t);
      for (t = 16; t < 64; t++) {
        var s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >>> 3);
        var s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >>> 10);
        w[t] = (w[t - 16] + s0 + w[t - 7] + s1) >>> 0;
      }
      var a = hash[0], b = hash[1], c = hash[2], d = hash[3];
      var e = hash[4], f = hash[5], g = hash[6], hh = hash[7];
      for (t = 0; t < 64; t++) {
        var t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) +
          SHA256_K[t] + w[t]) >>> 0;
        var t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
        hh = g; g = f; f = e; e = (d + t1) >>> 0;
        d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      hash = [(hash[0] + a) >>> 0, (hash[1] + b) >>> 0, (hash[2] + c) >>> 0,
        (hash[3] + d) >>> 0, (hash[4] + e) >>> 0, (hash[5] + f) >>> 0,
        (hash[6] + g) >>> 0, (hash[7] + hh) >>> 0];
    }
    return hash.map(function (x) { return ('00000000' + x.toString(16)).slice(-8); }).join('');
  }

  /** One text for one value: keys sorted, no spaces, a number as the shortest
   * text that reads back to it, and NaN (a blank MN) and the infinities
   * written as themselves rather than folded into null as JSON would. An
   * undefined is written as itself too: the engine reads a missing AB/2 as
   * NaN and a null one as 0, so the two must not share a key.
   * @param {*} value
   * @returns {string}
   */
  function canonicalText(value) {
    if (value === undefined) return 'undefined';
    if (value === null) return 'null';
    if (typeof value === 'number') return String(value);
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (typeof value === 'string') return JSON.stringify(value);
    if (Array.isArray(value) || ArrayBuffer.isView(value)) {
      return '[' + Array.prototype.map.call(value, canonicalText).join(',') + ']';
    }
    return '{' + Object.keys(value).sort().map(function (k) {
      return JSON.stringify(k) + ':' + canonicalText(value[k]);
    }).join(',') + '}';
  }

  /* What computed an inversion here, or null - which turns the cache off -
   * when the bundle carries no digest of this file to name it by. */
  function inversionEngine() {
    var data = GWT.data || {};
    if (!data.engineDigest) return null;
    return 'gwt-core ' + data.version + ' code ' + String(data.engineDigest).slice(0, 16);
  }

  /** The cache key of invertSounding(sounding, {config: config}), or null.
   * @param {Sounding} sounding
   * @param {Config} [config]
   * @returns {string|null}
   */
  function inversionCacheKey(sounding, config) {
    var engine = inversionEngine();
    if (!engine) return null;
    return sha256Hex(canonicalText({
      cache: INVERSION_CACHE_FORMAT,
      engine: engine,
      sounding: {
        id: String(sounding.sounding_id || ''),
        array_type: sounding.array_type || 'schlumberger',
        ab2: sounding.ab2, mn: sounding.mn || [], rho_app: sounding.rho_app,
      },
      config: inversionSettings((config || defaultConfig()).ves),
    }));
  }

  /* The VES settings an inversion reads: all but the suitability weights,
   * which nothing in it reads, so that a calibration set (PLAN.md step 5.3)
   * changing them does not invert a survey again (ves/cache.py
   * _inversion_settings). */
  function inversionSettings(ves) {
    /** @type {Rec} */
    var out = {};
    Object.keys(ves).forEach(function (key) {
      if (key !== 'suitability_weights') out[key] = ves[key];
    });
    return out;
  }

  function inversionDigest(key, record) {
    return sha256Hex(key + '\n' + canonicalText(record));
  }

  /** What to save under key for one sounding: its inversion, or the message
   * the inversion failed with - a failure is as determined as a result, and
   * would otherwise be tried again at every recompute. Plain JSON, so it
   * comes back unchanged from the store and the project file. Null if it
   * will not keep.
   * @param {string|null} key
   * @param {Sounding} sounding
   * @param {Rec|null} result
   * @param {*} [error]
   */
  function inversionCacheEntry(key, sounding, result, error) {
    if (!key) return null;
    var record;
    if (result) {
      record = {
        resistivities: Array.from(result.model.resistivities),
        thicknesses: Array.from(result.model.thicknesses),
        n_iterations: result.n_iterations,
        converged: !!result.converged,
        stopped: String(result.stopped),
        trials: result.trials.map(function (t) { return [t[0], t[1]]; }),
      };
      var numbers = record.resistivities.concat(record.thicknesses,
        record.trials.map(function (t) { return t[1]; }));
      if (!numbers.every(isFiniteNum)) return null;
    } else {
      record = { error: String(error) };
    }
    return {
      /* for whoever opens the file; neither is read back */
      sounding: String(sounding.sounding_id || ''),
      engine: inversionEngine(),
      result: record,
      digest: inversionDigest(key, record),
    };
  }

  function positiveList(value, length) {
    return Array.isArray(value) && (length === undefined || value.length === length) &&
      value.every(function (x) { return isFiniteNum(x) && x > 0; });
  }

  function isCount(value, lo, hi) {
    return typeof value === 'number' && Math.floor(value) === value && value >= lo && value <= hi;
  }

  /** The saved inversion of a sounding, as {result} or {error}, or null to
   * invert it afresh. key is inversionCacheKey of this sounding and
   * configuration. Anything short of a well-formed entry whose digest
   * matches under this key, and whose model reproduces the misfit the
   * search recorded for it, is null. Never throws.
   * @param {*} entry whatever the store or the project file held
   * @param {string|null} key
   * @param {Sounding} sounding
   * @param {Config} [config]
   */
  function inversionFromCache(entry, key, sounding, config) {
    try {
      if (!key || !entry || typeof entry !== 'object') return null;
      var record = entry.result;
      if (!record || typeof record !== 'object' || typeof entry.digest !== 'string') return null;
      if (entry.digest !== inversionDigest(key, record)) return null;
      if (Object.keys(record).join() === 'error') {
        return typeof record.error === 'string' ? { error: record.error } : null;
      }
      var cfg = (config || defaultConfig()).ves;
      var rho = record.resistivities, h = record.thicknesses, trials = record.trials;
      if (!(positiveList(rho) && isCount(rho.length, cfg.min_layers, cfg.max_layers) &&
            positiveList(h, rho.length - 1) &&
            isCount(record.n_iterations, 0, cfg.max_iterations) &&
            typeof record.converged === 'boolean' &&
            STOPS.indexOf(record.stopped) >= 0 &&
            Array.isArray(trials) && trials.length)) return null;
      for (var i = 0; i < trials.length; i++) {
        var t = trials[i];
        if (!(Array.isArray(t) && t.length === 2 &&
              isCount(t[0], cfg.min_layers, cfg.max_layers) && isFiniteNum(t[1]))) return null;
      }
      var result = restoreInversion(sounding, record);
      /* no layer count the search would not have tried on these readings */
      var most = mostLayers(result.ab2.filter(function (v, k) {
        return result.ab2.indexOf(v) === k;
      }).length);
      if (trials.some(function (t1) { return t1[0] > most; })) return null;
      /* the model has to fit the readings as well as the search said it did */
      var recorded = trials.filter(function (t2) { return t2[0] === rho.length; });
      if (!recorded.length || Math.abs(recorded[0][1] - result.fit_error_percent) >
          1e-12 * Math.max(1, Math.abs(result.fit_error_percent))) return null;
      return { result: result };
    } catch (e) {
      return null;
    }
  }

  /** A layered model with the derived depth arrays the rest of the code reads.
   * @param {ArrayLike<number>} resistivities
   * @param {ArrayLike<number>} thicknesses
   * @param {Rec} [extra] further fields to set on the model
   */
  function layeredModel(resistivities, thicknesses, extra) {
    var rho = Array.prototype.slice.call(resistivities);
    var h = Array.prototype.slice.call(thicknesses);
    var tops = [0.0], bottoms = [];
    for (var i = 0; i < h.length; i++) {
      bottoms.push(tops[i] + h[i]);
      tops.push(tops[i] + h[i]);
    }
    bottoms.push(Infinity);
    var model = {
      resistivities: rho,
      thicknesses: h,
      n_layers: rho.length,
      depths_top: tops.slice(0, rho.length),
      depths_bottom: bottoms,
      fit_error_percent: null,
      method: '',
      sounding_id: '',
    };
    return Object.assign(model, extra || {});
  }
