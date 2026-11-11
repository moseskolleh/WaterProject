
  /* ===================================================== Elevation models
   * groundwater/mapping/elevation.py's elevation layer: what turns the
   * files an operator supplies into the window the terrain analysis reads.
   * A file is opened for its layout alone (elevationFile: a GeoTIFF's
   * directories, nothing at all for .hgt) and refused here unless it is in
   * WGS 84 longitude and latitude, clear of the poles; its source is then
   * recognised from its name and georeferencing together. The window is
   * planned around the site (windowCentre, planElevationWindow): the square
   * shown, the margin analysed beyond it and the cap on cells, the files
   * joined on one lattice and never resampled, and the blocks each file
   * must give up, edge blocks of a missing tile included. The page reads
   * those bytes (elevationBlockRanges says which) and readElevationWindow
   * turns them into one grid: each block's samples judged first, overlaps
   * held to the bit, a missing tile taken as sea only when the full edges
   * beside it are at sea level, and the read report written.
   *
   * Every float expression is Python's, operation for operation and in the
   * same order, and every refusal is raised in the same order with the
   * same catalogued sentence, so the two engines plan and read the same
   * window to the bit; the parity suite and tests/test_terrain_engine_js.py
   * hold them together. The browser never reads a strided window (the
   * Python app's wide topographic map does), so the stride is always 1
   * here. Everything is synchronous, for the worker and the Node sandboxes
   * alike. */

  /** @typedef {{name: string, size: number, layout: TiffLayout, kind: string, sourceId: string,
   *   notes: string[]}} ElevationFile  one file opened for its layout: kind 'geotiff' or 'hgt',
   *   sourceId what it was recognised as, notes the catalogue ids of what is said about it alone */
  /** @typedef {{lon: number, lat: number, label: string, exact: boolean, note: string|null}} WindowCentre */
  /** @typedef {{missing: number, file: number, row: number|null, column: number|null}} PlanEdge */
  /** @typedef {{file: number, index: number, offset: number, length: number, rows: [number, number]|null,
   *   window: boolean, edges: number[]}} PlanBlock */
  /** @typedef {{files: ElevationFile[], sources: string[], declared: [string, string],
   *   offsets: Array<[number, number]>, x0: number, y0: number, sx: number, sy: number,
   *   centre: WindowCentre, ci: number, cj: number, stride: number, hx: number, hy: number,
   *   hxs: number, hys: number, width: number, height: number, cells: number,
   *   shown: [number, number, number, number], radiusKm: number, marginKm: number, dx: number,
   *   dy: number, lons: Float64Array, lats: Float64Array, tile: number,
   *   missing: Array<[number, number]>, edges: PlanEdge[], blocks: PlanBlock[]}} WindowPlan */
  /** @typedef {{file: number, name: string, offset: number, length: number, blocks: number[]}} ElevationRange */
  /** @typedef {{label: string, credit: string, notice: string|null, surface: string,
   *   seaClean: boolean}} TerrainCredit */

  /* SRTM marks a void with this value; it is not an elevation */
  var SRTM_VOID = -32768;
  /* An .hgt name: the south-west corner, ASCII letters and digits only, as
   * Python's expression has them. */
  var HGT_NAME = /^([NSns])([0-9]{2})([EWew])([0-9]{3})/;
  /* What a file's source is recognised from: its name without the
   * extension, letters in either case (ASCII only, as Python's re.ASCII has
   * them; without the u flag JavaScript folds no other letter to an ASCII
   * one either). Python's $ also matches before a newline that ends the
   * text, which \n?$ copies. */
  var COPERNICUS_NAME = /^Copernicus_DSM_(?:COG_)?10_([NS])(\d{2})_00_([EW])(\d{3})_00_DEM\n?$/i;
  var SRTM_NAME = /^([ns])(\d{2})_([ew])(\d{3})_[13]arc_v[23]\n?$/i;
  var FABDEM_NAME = /_fabdem_v1-\d/i;
  /* products that write the sea as exactly 0 m and publish no tiles of
   * open sea, so a tile missing from a set of them may be sea */
  var SEA_AT_0 = ['copernicus_glo30', 'srtm', 'hgt'];
  /* how a product is named in a sentence */
  var PRODUCT_NAMES = /** @type {Record<string, string>} */ (
    { copernicus_glo30: 'Copernicus GLO-30', srtm: 'SRTM', hgt: 'SRTM' });
  /* what the operator may declare a set to be */
  var DECLARED_KINDS = ['detect', 'copernicus_glo30', 'srtm', 'other'];
  /* within this much of a whole degree, a file's first centre is on it */
  var DEGREE_TOL = 1e-9;
  var ARCSEC = 1.0 / 3600.0;
  /* Python's str.isspace characters, which str.strip() takes from both
   * ends of the operator's own words; String.trim takes a byte-order mark
   * that Python keeps and keeps U+0085 and U+001C to U+001F, which Python
   * takes */
  var PY_SPACE = '\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005' +
    '\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000';
  /* reads of one file closer than this are made as one, and no merged
   * read is longer than ELEVATION_MERGE_MAX, as Python merges its reads */
  var ELEVATION_MERGE_GAP = 65536;
  var ELEVATION_MERGE_MAX = 16 * 1048576;

  /* a over b, rounded down, exactly for any two safe integers (b > 0) */
  function floorDiv(a, b) {
    var q = Math.floor(a / b);
    if (q * b > a) q -= 1;
    else if ((q + 1) * b <= a) q += 1;
    return q + 0;
  }

  function isHgt(name) {
    return name.slice(-4).toLowerCase() === '.hgt';
  }

  /* the name without its extension: up to its last dot, unless that is the
   * first character */
  function nameStem(name) {
    var dot = name.lastIndexOf('.');
    return dot > 0 ? name.slice(0, dot) : name;
  }

  /** An SRTM-format .hgt tile described as geotiffLayout describes a file,
   * so that a window of it is read block by block as a GeoTIFF's is:
   * elevation.hgt_layout. The file has no header: its corner comes from its
   * name and its resolution from its length. It is big-endian int16 with
   * -32768 for no data, northern row first, each row a strip of its own, so
   * a window reads only its own rows; cells are centred on whole fractions
   * of a degree from the named corner, the 1201 or 3601 samples a side
   * including both edges of the degree. A name that does not carry the
   * corner, or a length of neither size, is refused.
   * @param {string} name the file's name, as the sentences give it
   * @param {number} size the file's length in bytes
   * @returns {TiffLayout}
   */
  function hgtLayout(name, size) {
    var match = HGT_NAME.exec(name);
    if (match === null) throw tiffError('terrain.hgt_name', { file: name });
    var side = size === 2 * 1201 * 1201 ? 1201 : size === 2 * 3601 * 3601 ? 3601 : 0;
    if (!side) throw tiffError('terrain.hgt_size', { file: name, n: Math.floor(size / 2) });
    /* + 0, so that S00 and W000 are +0 as Python's integers are */
    var lat0 = Number(match[2]) * (match[1] === 'N' || match[1] === 'n' ? 1 : -1) + 0;
    var lon0 = Number(match[4]) * (match[3] === 'E' || match[3] === 'e' ? 1 : -1) + 0;
    var step = 1.0 / (side - 1);
    var offsets = new Array(side), counts = new Array(side);
    for (var j = 0; j < side; j++) {
      offsets[j] = 2 * side * j;
      counts[j] = 2 * side;
    }
    return {
      name: name, size: size, byteOrder: '>', bigtiff: false, width: side, height: side, bits: 16,
      sampleFormat: 2, compression: 1, predictor: 1, predictorApplied: false, tiled: false,
      blockWidth: side, blockHeight: 1, rowsPerStrip: 1, offsets: offsets, byteCounts: counts,
      modelType: 2, rasterType: 2, epsg: 4326, datum: null, angularUnit: null,
      x0: lon0, y0: lat0 + 1, sx: step, sy: step, nodata: SRTM_VOID, ifdIndex: 0,
      geoAscii: null, hasNodataTag: false, hasMask: false,
    };
  }

  /** One file of an elevation model opened for its layout alone:
   * elevation.open_elevation_file, one round of it. A file is .hgt by its
   * name, which needs no bytes, and a GeoTIFF otherwise, whose layout is
   * read from `chunks` by geotiffLayout's rule; while bytes are missing the
   * sorted [offset, length] ranges still to read come back instead, to be
   * read (each rounded up to 64 KiB, at most 16 rounds, as Python reads
   * them) and passed back with the rest. The file is refused, with its own
   * sentence, unless it is in WGS 84 longitude and latitude in degrees with
   * every cell centre more than a degree from a pole; then its source is
   * recognised, and `notes` holds the ids of what is said about it alone
   * (fileNotes writes them out).
   * @param {string} name the file's name, as the sentences give it
   * @param {number} size the file's length in bytes
   * @param {Array<[number, Uint8Array]>} chunks the bytes read so far, as [offset, bytes]
   * @returns {ElevationFile|Array<[number, number]>}
   */
  function elevationFile(name, size, chunks) {
    if (isHgt(name)) return openedElevationFile(name, size, hgtLayout(name, size), 'hgt');
    var layout = geotiffLayout(name, size, chunks);
    if (Array.isArray(layout)) return layout;
    return openedElevationFile(name, size, layout, 'geotiff');
  }

  /** @returns {ElevationFile} */
  function openedElevationFile(name, size, layout, kind) {
    acceptElevation(layout, name);
    var found = identifySource(name, layout);
    return { name: name, size: size, layout: layout, kind: kind, sourceId: found[0], notes: found[1] };
  }

  /* Refuse a file that is not in WGS 84 longitude and latitude, in
   * degrees, with every cell centre more than a degree from a pole:
   * elevation._accept. A file carrying a GDAL mask is refused first, since
   * the cells it hides usually hold 0, which would read as ground at sea
   * level. A projected file is named by its CRS, so the operator can tell
   * which copy of the tile they sent. Georeferencing no elevation model has
   * - an origin that is infinite or not a number, longitudes beyond any
   * map, cells under 1e-7 or over 1 degree - is refused before the poles
   * are looked at, the test written so that NaN fails it. At a pole a cell
   * has no width east to west, and the window arithmetic divides by it. */
  function acceptElevation(layout, name) {
    if (layout.hasMask) throw tiffError('terrain.internal_mask', { file: name });
    var model = layout.modelType;
    if (model === 1) throw tiffError('terrain.projected', { file: name, crs: projectedName(layout.epsg) });
    if (model === null || model === undefined) throw tiffError('terrain.no_crs', { file: name });
    if (model !== 2) throw tiffError('terrain.not_wgs84', { file: name, crs: 'GeoTIFF model type ' + model });
    var wgs84 = layout.epsg === 4326 ||
      ((layout.epsg === null || layout.epsg === 32767) && layout.datum === 6326);
    if (!wgs84 || !(layout.angularUnit === null || layout.angularUnit === 9102)) {
      throw tiffError('terrain.not_wgs84', { file: name, crs: geographicName(layout) });
    }
    var east = layout.x0 + (layout.width - 1) * layout.sx;
    var south = layout.y0 - (layout.height - 1) * layout.sy;
    if (!(layout.x0 >= -540.0 && east <= 540.0 && south >= -90.0 && layout.y0 <= 90.0 &&
        layout.sx >= 1e-7 && layout.sx <= 1.0 && layout.sy >= 1e-7 && layout.sy <= 1.0)) {
      throw tiffError('terrain.bad_georeference', { file: name });
    }
    if (!(south > -89.0 && layout.y0 < 89.0)) throw tiffError('terrain.polar', { file: name });
  }

  /* a projected CRS as the refusal names it: the UTM zones and the Sierra
   * Leone 1968 grid by name, anything else by its EPSG code */
  function projectedName(epsg) {
    if (epsg === null || epsg === 32767) return 'a projected system with no EPSG code';
    if ((epsg >= 32601 && epsg <= 32660) || (epsg >= 32701 && epsg <= 32760)) {
      return 'WGS 84 / UTM zone ' + (epsg % 100) + (epsg < 32700 ? 'N' : 'S') + ' (EPSG ' + epsg + ')';
    }
    if (epsg === 2161 || epsg === 2162) {
      return 'Sierra Leone 1968 / UTM zone ' + (epsg === 2161 ? 28 : 29) + 'N (EPSG ' + epsg + ')';
    }
    return 'EPSG ' + epsg;
  }

  /* a geographic CRS that is not WGS 84 in degrees, as the refusal names it */
  function geographicName(layout) {
    var epsg = layout.epsg, datum = layout.datum, unit = layout.angularUnit, text;
    if (epsg !== null && epsg !== 32767) text = 'EPSG ' + epsg;
    else if (datum === 6326) text = 'WGS 84';
    else if (datum !== null && datum !== 32767) text = 'a geographic system on datum EPSG ' + datum;
    else text = 'a geographic system with no EPSG code';
    if (unit !== null && unit !== 9102) text += ' in angular unit EPSG ' + unit;
    return text;
  }

  function spacingIs(value, step) {
    return Math.abs(value - step) <= 1e-12;
  }

  /* finite first, as Python must have it: its math.floor of an infinity or
   * NaN raises */
  function onDegree(value) {
    return isFinite(value) && Math.abs(value - Math.floor(value + 0.5)) <= DEGREE_TOL;
  }

  /* Every cell centre lies in the 1-degree square whose south-west corner
   * is (lon0, lat0), give or take a billionth of a degree; so a tile of
   * 3600 or of 3601 samples a side passes. */
  function insideSquare(layout, lon0, lat0) {
    var east = layout.x0 + (layout.width - 1) * layout.sx;
    var south = layout.y0 - (layout.height - 1) * layout.sy;
    return layout.x0 >= lon0 - DEGREE_TOL && east <= lon0 + 1 + DEGREE_TOL &&
      south >= lat0 - DEGREE_TOL && layout.y0 <= lat0 + 1 + DEGREE_TOL;
  }

  /** [lon0, lat0, tile code such as "N08 W012"] from a name's four groups
   * @returns {[number, number, string]} */
  function namedCorner(match) {
    var ns = match[1].toUpperCase(), latDeg = match[2], ew = match[3].toUpperCase(), lonDeg = match[4];
    var lat0 = Number(latDeg) * (ns === 'N' ? 1 : -1) + 0;
    var lon0 = Number(lonDeg) * (ew === 'E' ? 1 : -1) + 0;
    return [lon0, lat0, ns + latDeg + ' ' + ew + lonDeg];
  }

  /* Laid out as a Copernicus GLO-30 tile is, whatever its name. Nothing in
   * a tile says it is Copernicus, so this only prompts the operator; it
   * never credits. */
  function glo30Fingerprint(layout) {
    return layout.modelType === 2 && layout.epsg === 4326 &&
      spacingIs(layout.sx, ARCSEC) && spacingIs(layout.sy, ARCSEC) &&
      layout.rasterType === 2 && onDegree(layout.x0) && onDegree(layout.y0) &&
      layout.sampleFormat === 3 && layout.bits === 32 && !layout.hasNodataTag &&
      layout.geoAscii === 'WGS 84|';
  }

  /** [source id, catalogue ids] for a file, from its name and
   * georeferencing together: elevation.identify_source. A tile holds
   * nothing that identifies it and operators rename files, so the name is
   * believed only when the georeferencing bears it out.
   * @returns {[string, string[]]} */
  function identifySource(name, layout) {
    if (isHgt(name)) return ['hgt', []];
    var stem = nameStem(name);
    var match = COPERNICUS_NAME.exec(stem), corner;
    if (match !== null) {
      corner = namedCorner(match);
      if (layout.modelType === 2 && layout.epsg === 4326 && spacingIs(layout.sx, ARCSEC) &&
          spacingIs(layout.sy, ARCSEC) && insideSquare(layout, corner[0], corner[1])) {
        return ['copernicus_glo30', []];
      }
      return ['unidentified', ['terrain.name_mismatch']];
    }
    match = SRTM_NAME.exec(stem);
    if (match !== null) {
      corner = namedCorner(match);
      var spacing = spacingIs(layout.sx, ARCSEC) ? ARCSEC
        : spacingIs(layout.sx, 1.0 / 1200.0) ? 1.0 / 1200.0 : null;
      if (spacing !== null && spacingIs(layout.sy, spacing) && insideSquare(layout, corner[0], corner[1])) {
        return ['srtm', []];
      }
    }
    if (FABDEM_NAME.test(stem)) return ['unidentified', ['terrain.fabdem_licence']];
    if (glo30Fingerprint(layout)) return ['unidentified', ['terrain.looks_copernicus']];
    return ['unidentified', []];
  }

  /** The operator's declaration [kind, text], checked, its text trimmed as
   * Python trims it, and another source of no stated name read as no
   * declaration at all. None given is 'detect'.
   * @returns {[string, string]} */
  function elevationDeclaration(declared) {
    var kind = declared ? declared[0] : 'detect';
    var text = declared && declared[1] ? String(declared[1]) : '';
    if (DECLARED_KINDS.indexOf(kind) < 0) {
      throw new Error('the source declared is ' + JSON.stringify(kind) + ', not one of ' +
        DECLARED_KINDS.join(', '));
    }
    var trimmed = stripChars(text, PY_SPACE);
    if (kind === 'other' && !trimmed) return ['detect', ''];
    return [kind, trimmed];
  }

  /** What is said about one file alone, written out: elevation.file_notes.
   * Once the operator has declared the source, a note about how the file
   * would otherwise be credited no longer applies; the FABDEM licence
   * warning does.
   * @param {ElevationFile} found what elevationFile opened
   * @param {[string, string]|null} [declared] the operator's [kind, text]: kind 'detect',
   *   'copernicus_glo30', 'srtm' or 'other' (text their own words); none is 'detect'
   * @returns {string[]}
   */
  function fileNotes(found, declared) {
    var kind = elevationDeclaration(declared)[0];
    /** @type {string[]} */
    var out = [];
    found.notes.forEach(function (ident) {
      if (kind !== 'detect' && ident !== 'terrain.fabdem_licence') return;
      if (ident === 'terrain.name_mismatch') {
        out.push(phrase('terrain.name_mismatch', { file: found.name }));
      } else if (ident === 'terrain.looks_copernicus') {
        out.push(phrase('terrain.looks_copernicus', { file: found.name }));
      } else {
        out.push(phrase('terrain.fabdem_licence', { file: found.name }));
      }
    });
    return out;
  }

  /* each file's source once the declaration is applied: the declaration
   * wins, and a source in the operator's own words is no product the
   * toolkit knows */
  function declaredSources(files, declared) {
    var kind = elevationDeclaration(declared)[0];
    return files.map(function (found) {
      return kind === 'detect' ? found.sourceId : kind !== 'other' ? kind : 'unidentified';
    });
  }

  function setSource(sources) {
    return sources.length && sources.every(function (s) { return s === sources[0]; })
      ? sources[0] : 'unidentified';
  }

  /** @returns {string} */
  function tileCodeOf(name) {
    var stem = nameStem(name);
    var match = COPERNICUS_NAME.exec(stem) || SRTM_NAME.exec(stem);
    return match !== null ? namedCorner(match)[2] : name;
  }

  /* Plan order: the greatest y0 first, then the smallest x0, then the name
   * in UTF-16 code-unit order, which is how < compares strings (never
   * localeCompare); the sort is stable, as Python's is. */
  function elevationPlanOrder(files) {
    return files.slice().sort(function (a, b) {
      if (a.layout.y0 !== b.layout.y0) return a.layout.y0 > b.layout.y0 ? -1 : 1;
      if (a.layout.x0 !== b.layout.x0) return a.layout.x0 < b.layout.x0 ? -1 : 1;
      return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
    });
  }

  /** What the figures drawn from a set of files say of them:
   * elevation.elevation_label_and_credit. The label names the files and
   * where they came from; the credit is what a licence asks a figure drawn
   * from them to carry ('' where none is known); the notice is the
   * Copernicus licence's liability sentence, given wherever the set holds a
   * Copernicus file (null otherwise); the surface note says what the
   * heights are heights of. The operator's declaration wins over what the
   * names say. seaClean is true when every file comes from a product that
   * writes the sea as exactly 0 m and publishes no tiles of open sea.
   * @param {ElevationFile[]} files what elevationFile opened
   * @param {[string, string]|null} [declared] the operator's [kind, text]; none is 'detect'
   * @returns {TerrainCredit}
   */
  function terrainCredit(files, declared) {
    var decl = elevationDeclaration(declared), kind = decl[0], text = decl[1];
    var ordered = elevationPlanOrder(files);
    var names = andJoin(ordered.map(function (f) { return f.name; }));
    var copernicus = phrase('terrain.credit_copernicus_modified');
    var liability = phrase('terrain.copernicus_liability');
    function credit(label, credited, notice, surface, seaClean) {
      return { label: label, credit: credited, notice: notice, surface: surface, seaClean: seaClean };
    }
    if (kind === 'copernicus_glo30') {
      return credit(phrase('terrain.label_declared', { declared: PRODUCT_NAMES[kind], files: names }),
        copernicus, liability, phrase('terrain.surface_copernicus'), true);
    }
    if (kind === 'srtm') {
      return credit(phrase('terrain.label_declared', { declared: PRODUCT_NAMES[kind], files: names }),
        phrase('terrain.credit_srtm'), null, phrase('terrain.surface_srtm'), true);
    }
    if (kind === 'other') {
      return credit(phrase('terrain.label_declared', { declared: text, files: names }), '', null,
        phrase('terrain.surface_unknown'), false);
    }
    var sources = ordered.map(function (f) { return f.sourceId; });
    var found = ordered.filter(function (f) { return f.sourceId === 'copernicus_glo30'; });
    function tiles(of) { return andJoin(of.map(function (f) { return tileCodeOf(f.name); })); }
    if (found.length && found.length === ordered.length) {
      return credit(phrase('terrain.label_copernicus', { n: found.length, tiles: tiles(found) }), copernicus,
        liability, phrase('terrain.surface_copernicus'), true);
    }
    if (found.length && sources.every(function (s) { return s === 'copernicus_glo30' || s === 'unidentified'; })) {
      var rest = andJoin(ordered.filter(function (f) { return f.sourceId !== 'copernicus_glo30'; })
        .map(function (f) { return f.name; }));
      return credit(phrase('terrain.label_mixed', { n: found.length, tiles: tiles(found), files: rest }),
        copernicus, liability, phrase('terrain.surface_unknown'), false);
    }
    if (sources.length && sources.every(function (s) { return s === 'srtm'; })) {
      return credit(phrase('terrain.label_srtm', { n: ordered.length, tiles: tiles(ordered) }),
        phrase('terrain.credit_srtm'), null, phrase('terrain.surface_srtm'), true);
    }
    if (sources.length && sources.every(function (s) { return s === 'hgt'; })) {
      return credit(phrase('terrain.label_hgt', { n: ordered.length, files: names }), '', null,
        phrase('terrain.surface_srtm'), true);
    }
    return credit(phrase('terrain.label_unidentified', { files: names }), '', null,
      phrase('terrain.surface_unknown'), false);
  }

  /* --- degrees and metres, with the same bits in both engines ------------ */

  var ELEVATION_D2R = Math.PI / 180.0;
  var WGS84_A = 6378137.0;                    // WGS 84, as groundwater.geo has it
  var WGS84_FLAT = 1.0 / 298.257223563;
  var WGS84_E2 = WGS84_FLAT * (2.0 - WGS84_FLAT);

  /* k! as an exact integer, then a double: exact for k <= 18 (< 2**53) */
  function exactFactorial(k) {
    var product = 1;
    for (var n = 2; n <= k; n++) product *= n;
    return product;
  }

  /* The Taylor coefficients, worked out at load rather than typed as
   * decimal literals, so that they are Python's doubles by construction:
   * 1/k! is one correctly rounded division in both engines. */
  var SIN_TERMS = [], COS_TERMS = [];
  (function () {
    for (var n = 0; n < 9; n++) SIN_TERMS.push((n % 2 ? -1.0 : 1.0) / exactFactorial(2 * n + 1));
    for (n = 0; n < 10; n++) COS_TERMS.push((n % 2 ? -1.0 : 1.0) / exactFactorial(2 * n));
  }());

  /** The sine and cosine of `d` degrees from additions, multiplications and
   * one floor, so that both engines give the same bits: elevation.sin_cos_deg.
   * Math.sin and Python's math.sin differ in the last bit for some inputs,
   * and every row's cell size is worked out from these. The angle is first
   * reduced to within 45 degrees of a right angle, which is exact, then a
   * Taylor polynomial is summed in a fixed order. At a right angle the
   * answer is exactly 0 or 1; elsewhere it is within about 1e-15 of the
   * true value. Something that is not a finite number gives NaN.
   * @param {number} d degrees
   * @returns {[number, number]} [sine, cosine]
   */
  function sinCosDeg(d) {
    d = Number(d);
    if (!isFinite(d)) return [NaN, NaN];
    var q = Math.floor(d / 90.0 + 0.5);
    var r = d - 90.0 * q;
    var x = r * ELEVATION_D2R;
    var x2 = x * x;
    var s = SIN_TERMS[8], k;
    for (k = 7; k >= 0; k--) s = s * x2 + SIN_TERMS[k];
    s = s * x;
    var c = COS_TERMS[9];
    for (k = 8; k >= 0; k--) c = c * x2 + COS_TERMS[k];
    var m = ((q % 4) + 4) % 4;
    return m === 0 ? [s, c] : m === 1 ? [c, -s] : m === 2 ? [-s, -c] : [-c, s];
  }

  /** The east-west and north-south size in metres of a cell centred at
   * latitude `lat`, `stepLon` by `stepLat` degrees, on the WGS 84
   * ellipsoid: elevation.wgs84_cell_size. The radii of curvature in the
   * prime vertical (N) and the meridian (M) at that latitude, times the
   * step in radians.
   * @param {number} lat the cell centre's latitude, degrees
   * @param {number} stepLon the cell's width, degrees
   * @param {number} stepLat the cell's height, degrees
   * @returns {[number, number]} [dx, dy] in metres
   */
  function wgs84CellSize(lat, stepLon, stepLat) {
    var sc = sinCosDeg(lat), s = sc[0], c = sc[1];
    var den = 1.0 - WGS84_E2 * (s * s);
    var rt = Math.sqrt(den);
    var n = WGS84_A / rt;
    var m = (WGS84_A * (1.0 - WGS84_E2)) / (den * rt);
    return [(n * c) * (stepLon * ELEVATION_D2R), m * (stepLat * ELEVATION_D2R)];
  }

  /** Each row's cell size for a grid with these centres: elevation.row_metric.
   * A cell 1 arc-second wide is 0.26% narrower at the north edge of a
   * Sierra Leone tile than at its south edge, so each row has its own size:
   * dx east-west and dy north-south in metres, dg the diagonal, and auRow
   * the cell's area in whole units of 0.01 square metres (an integer, so
   * areas add up exactly in any order). Row 0 is the first latitude given,
   * the southern row in a grid.
   * @param {ArrayLike<number>} lons the column centres, at least 2
   * @param {ArrayLike<number>} lats the row centres, at least 2
   * @returns {{dx: Float64Array, dy: Float64Array, dg: Float64Array, auRow: Float64Array}}
   */
  function rowMetric(lons, lats) {
    var width = lons.length, height = lats.length;
    if (width < 2 || height < 2) {
      throw new Error('a ' + height + ' by ' + width + ' grid has no step between its cells to measure');
    }
    var stepLon = (lons[width - 1] - lons[0]) / (width - 1);
    var stepLat = (lats[height - 1] - lats[0]) / (height - 1);
    var dx = new Float64Array(height), dy = new Float64Array(height);
    var dg = new Float64Array(height), au = new Float64Array(height);
    for (var r = 0; r < height; r++) {
      var size = wgs84CellSize(lats[r], stepLon, stepLat), x = size[0], y = size[1];
      dx[r] = x;
      dy[r] = y;
      dg[r] = Math.sqrt(x * x + y * y);
      au[r] = Math.floor(x * y * 100.0 + 0.5);
    }
    return { dx: dx, dy: dy, dg: dg, auRow: au };
  }

  function elevationCellNote(dx, dy) {
    return 'about ' + pyFixed(dx, 0) + ' by ' + pyFixed(dy, 0) + ' m';
  }

  /* a point as the read report writes one, through Python's %.5f: 9.03487 N, 11.92862 W */
  function elevationCoordinates(lon, lat) {
    return pyFixed(Math.abs(lat), 5) + ' ' + (lat >= 0 ? 'N' : 'S') + ', ' +
      pyFixed(Math.abs(lon), 5) + ' ' + (lon >= 0 ? 'E' : 'W');
  }

  /* what a model covers, as terrain._bounds_text writes it */
  function elevationBoundsText(bounds) {
    var lonMin = bounds[0], latMin = bounds[1], lonMax = bounds[2], latMax = bounds[3];
    return pyFixed(Math.abs(latMin), 3) + '-' + pyFixed(Math.abs(latMax), 3) + ' ' +
      (latMin >= 0 ? 'N' : 'S') + ', ' + pyFixed(Math.abs(lonMax), 3) + '-' +
      pyFixed(Math.abs(lonMin), 3) + ' ' + (lonMin >= 0 ? 'E' : 'W');
  }

  /* [west, south, east, north]: the bounding box of the files' cell
   * centres, which holds any gap between them too; the first of equal
   * values kept, as Python's min and max keep it */
  function elevationExtent(files) {
    var west = 0, south = 0, east = 0, north = 0;
    files.forEach(function (found, k) {
      var lay = found.layout;
      var w = lay.x0, e = lay.x0 + (lay.width - 1) * lay.sx;
      var s = lay.y0 - (lay.height - 1) * lay.sy, n = lay.y0;
      if (k === 0 || w < west) west = w;
      if (k === 0 || e > east) east = e;
      if (k === 0 || s < south) south = s;
      if (k === 0 || n > north) north = n;
    });
    return [west, south, east, north];
  }

  /* --- the window: its centre, its cells, the blocks to read ------------ */

  /** Where the window is centred, and what to call the place:
   * elevation.window_centre. The site's GPS fix (`latlon`, as the page
   * reads it), else its chiefdom, else its district, as every other local
   * map is centred (areaWindow), with a note saying so when it is not a
   * fix; with no location at all, the middle of the files' cell centres,
   * named by its coordinates.
   * @param {Rec|null} site the project's site, or null
   * @param {{lat: number, lon: number}|null} latlon the site's position, or null
   * @param {ElevationFile[]} files what elevationFile opened
   * @returns {WindowCentre}
   */
  function windowCentre(site, latlon, files) {
    if (site) {
      var area = areaWindow(site, latlon || null);
      if (area) {
        return { lon: Number(area.lon), lat: Number(area.lat), label: area.label, exact: !!area.exact,
          note: area.exact ? null : phrase('terrain.centre_area', { label: area.label }) };
      }
    }
    if (!files || !files.length) throw new Error('no elevation files to centre the window on');
    var extent = elevationExtent(files);
    var lon = (extent[0] + extent[2]) / 2.0, lat = (extent[1] + extent[3]) / 2.0;
    return { lon: lon, lat: lat, label: elevationCoordinates(lon, lat), exact: false,
      note: phrase('terrain.centre_no_site') };
  }

  /* [qLo, qHi], the window positions 0..n-1 (lattice cell start + q) that
   * fall in lattice cells first..first+count-1, or null: elevation._steps
   * at stride 1 */
  function elevationSteps(first, count, start, n) {
    var delta = first - start;
    var lo = delta > 0 ? delta : 0, hi = delta + count - 1 < n - 1 ? delta + count - 1 : n - 1;
    return lo <= hi ? [lo, hi] : null;
  }

  /* [row, column] of a block's first image cell (of rows[0] for a strip
   * read in part), row 0 north */
  function elevationBlockOrigin(layout, index, rows) {
    var box = tiffBlockBox(layout, index);
    return [box.top + (rows ? rows[0] : 0), box.left];
  }

  /* [rows, columns] of the image a block (or the rows of it read) holds */
  function elevationBlockShape(layout, index, rows) {
    if (rows) return [rows[1] - rows[0], layout.width];
    var box = tiffBlockBox(layout, index);
    return [box.rows, box.cols];
  }

  /** Plan the window: elevation.plan_window, at stride 1. Check that the
   * files join, work out which cells the window holds, and list the blocks
   * of each file to read.
   *
   * `radiusKm` is the half-side of the square shown; the analysis also
   * reads `marginKm` beyond it on every side (by default the configuration's
   * terrain.analysis_buffer_km), and terrain.max_cells caps the whole, once
   * the centre is known to lie on a file (else it lies in a gap between
   * them or outside them); terrain.max_blocks caps the blocks the plan
   * names, counted before they are listed. The
   * files are put in plan order (the greatest y0 first, then the smallest
   * x0, then the name in UTF-16 code units) and the first one's lattice is
   * the reference; each other file must lie on it, at the same spacing and
   * a whole number of cells from it, and identified files must be of one
   * product. When every file is a whole 1-degree tile of a product that
   * publishes no tiles of open sea, the tiles the window meets that no file
   * supplies are listed with the full edges of the tiles beside them, and
   * the blocks holding those edges are read too, even outside the window.
   * Each refusal is thrown with its sentence, in Python's order.
   * @param {ElevationFile[]} files what elevationFile opened
   * @param {WindowCentre} centre what windowCentre gave, or a centre of the same shape
   * @param {number} radiusKm the half-side of the square shown, km
   * @param {Rec|null} [cfg] the project's configuration (or a part of it, as withConfig takes)
   * @param {number|null} [marginKm] the margin analysed beyond the square shown, km
   * @param {[string, string]|null} [declared] the operator's [kind, text]; none is 'detect'
   * @returns {WindowPlan}
   */
  function planElevationWindow(files, centre, radiusKm, cfg, marginKm, declared) {
    var terrain = withConfig(cfg).terrain;
    var margin = marginKm === null || marginKm === undefined ? terrain.analysis_buffer_km : Number(marginKm);
    var radius = Number(radiusKm);
    if (!files || !files.length) throw new Error('no elevation files to plan a window over');
    var k;

    /* plan order, one file per name, one kind of file */
    var ordered = elevationPlanOrder(files);
    /** @type {string[]} */
    var seen = [];
    for (k = 0; k < ordered.length; k++) {
      if (seen.indexOf(ordered[k].name) >= 0) throw tiffError('terrain.duplicate_name', { file: ordered[k].name });
      seen.push(ordered[k].name);
    }
    for (k = 1; k < ordered.length; k++) {
      if (ordered[k].kind !== ordered[0].kind) {
        throw tiffError('terrain.mixed_formats', { a: ordered[0].name, b: ordered[k].name });
      }
    }
    var sources = declaredSources(ordered, declared);

    /* one lattice, the reference file's */
    var ref = ordered[0].layout, x0 = ref.x0, y0 = ref.y0, sx = ref.sx, sy = ref.sy;
    /** @type {Array<[number, number]>} */
    var offsets = [[0, 0]];
    for (k = 1; k < ordered.length; k++) {
      var lay = ordered[k].layout;
      if (Math.abs(lay.sx - sx) > 1e-9 * sx || Math.abs(lay.sy - sy) > 1e-9 * sy) {
        throw tiffError('terrain.join_spacing', { a: ordered[0].name, b: ordered[k].name });
      }
      var ex = (lay.x0 - x0) / sx, ey = (y0 - lay.y0) / sy;
      /* written so that an infinite or NaN offset fails */
      if (!(Math.abs(ex - Math.floor(ex + 0.5)) <= 1e-6) || !(Math.abs(ey - Math.floor(ey + 0.5)) <= 1e-6)) {
        throw tiffError('terrain.join_phase', { a: ordered[0].name, b: ordered[k].name });
      }
      offsets.push([Math.floor(ex + 0.5), Math.floor(ey + 0.5)]);
    }

    /* one product */
    var first = -1;
    for (k = 0; k < sources.length; k++) {
      if (sources[k] === 'unidentified') continue;
      if (first < 0) {
        first = k;
      } else if (sources[k] !== sources[first]) {
        throw tiffError('terrain.join_products', { a: ordered[first].name, pa: PRODUCT_NAMES[sources[first]],
          b: ordered[k].name, pb: PRODUCT_NAMES[sources[k]] });
      }
    }

    /* the centre cell (NaN or an infinity for a centre no cell reaches,
     * which every test below then fails, as Python refuses it) */
    var ci = Math.floor((centre.lon - x0) / sx + 0.5);
    var cj = Math.floor((y0 - centre.lat) / sy + 0.5);

    /* before the cap, the centre must lie on a file, so that a centre off
     * the files is told so rather than given a radius that would not help;
     * it lies in a gap between them when the files' bounding box holds it,
     * judged on whole cells so the engines cannot disagree */
    var inside = ordered.some(function (found, f) {
      var oi = offsets[f][0], oj = offsets[f][1];
      return oi <= ci && ci < oi + found.layout.width && oj <= cj && cj < oj + found.layout.height;
    });
    if (!inside) {
      var iLow = Infinity, iHigh = -Infinity, jLow = Infinity, jHigh = -Infinity;
      ordered.forEach(function (found, f) {
        iLow = Math.min(iLow, offsets[f][0]);
        iHigh = Math.max(iHigh, offsets[f][0] + found.layout.width);
        jLow = Math.min(jLow, offsets[f][1]);
        jHigh = Math.max(jHigh, offsets[f][1] + found.layout.height);
      });
      var extent = elevationBoundsText(elevationExtent(ordered));
      if (iLow <= ci && ci < iHigh && jLow <= cj && cj < jHigh) {
        throw tiffError('terrain.site_gap', { where: centre.label, extent: extent });
      }
      throw tiffError('terrain.site_outside', { where: centre.label, extent: extent });
    }

    /* the half sizes from the centre cell's size; + 0 keeps a ceiling of a
     * small negative from being -0, as no Python integer is */
    var size = wgs84CellSize(y0 - cj * sy, sx, sy), dxC = size[0], dyC = size[1];
    var hx = Math.ceil((radius + margin) * 1000 / dxC) + 0;
    var hy = Math.ceil((radius + margin) * 1000 / dyC) + 0;
    var hxs = Math.ceil(radius * 1000 / dxC) + 0;
    var hys = Math.ceil(radius * 1000 / dyC) + 0;
    var width = 2 * hx + 1, height = 2 * hy + 1;

    /* the cap, on everything analysed, and the least window analysed. When
     * the margin alone is over the cap no radius fits, and the sentence
     * says to lower the margin rather than offer a radius of 0 km. */
    if (width * height > terrain.max_cells) {
      var hx0 = Math.ceil(1000 * margin / dxC) + 0, hy0 = Math.ceil(1000 * margin / dyC) + 0;
      if ((2 * hx0 + 1) * (2 * hy0 + 1) > terrain.max_cells) {
        throw tiffError('terrain.margin_too_many_cells', { margin: margin, cap: terrain.max_cells });
      }
      var h = Math.floor((Math.sqrt(terrain.max_cells) - 1) / 2);
      var fit = Math.floor((h * (dyC < dxC ? dyC : dxC) - 1000 * margin) / 100) / 10;
      throw tiffError('terrain.too_many_cells', { radius: radius, margin: margin, cap: terrain.max_cells,
        fit: fit > 0.0 ? fit : 0.0 });
    }
    if (width < 3 || height < 3) throw tiffError('terrain.too_small', { w: width, h: height });

    /* the axes, origin plus index times step, south row first */
    var lons = new Float64Array(width), lats = new Float64Array(height);
    for (k = 0; k < width; k++) lons[k] = x0 + (ci + (k - hx)) * sx;
    for (k = 0; k < height; k++) lats[k] = y0 - (cj + (hy - k)) * sy;

    /* missing 1-degree tiles of a product that publishes no sea tiles */
    var iFirst = ci - hx, jFirst = cj - hy;
    var tiles = elevationMissingTiles(ordered, sources, offsets, sx, iFirst, jFirst, width, height);

    /* the blocks, counted before any is listed: each costs a decode of its
     * own, so a file cut into tiny blocks is refused here however few cells
     * the window holds; a block holding both window cells and an edge is
     * counted once for each, so the count bounds the decodes from above */
    var counts = elevationCountBlocks(ordered, offsets, iFirst, jFirst, width, height, tiles.edges);
    var total = 0, most = 0;
    counts.forEach(function (count, f) {
      total += count;
      if (count > counts[most]) most = f;
    });
    if (total > terrain.max_blocks) {
      throw tiffError('terrain.too_many_blocks', { file: ordered[most].name, n: total, cap: terrain.max_blocks });
    }
    var blocks = elevationPlanBlocks(ordered, offsets, iFirst, jFirst, width, height, tiles.edges);
    return {
      files: ordered, sources: sources, declared: elevationDeclaration(declared), offsets: offsets,
      x0: x0, y0: y0, sx: sx, sy: sy, centre: centre, ci: ci, cj: cj, stride: 1, hx: hx, hy: hy,
      hxs: hxs, hys: hys, width: width, height: height, cells: width * height,
      shown: [hy - hys, hy + hys + 1, hx - hxs, hx + hxs + 1], radiusKm: radius, marginKm: margin,
      dx: dxC, dy: dyC, lons: lons, lats: lats, tile: tiles.tile, missing: tiles.missing,
      edges: tiles.edges, blocks: blocks,
    };
  }

  /* The tiles the window meets that no file supplies, and the full edges of
   * the supplied tiles beside each, when every file is a whole 1-degree
   * tile of a product that publishes no tiles of open sea; else none. A
   * tile is numbered on the reference lattice by integer division, so the
   * numbering is exact; a file supplies the tile its first cell lies in. */
  function elevationMissingTiles(files, sources, offsets, sx, iFirst, jFirst, width, height) {
    var p = Math.floor(1 / sx + 0.5);
    /** @type {Array<[number, number]>} */
    var missing = [];
    /** @type {PlanEdge[]} */
    var edges = [];
    var whole = sources.every(function (s) { return SEA_AT_0.indexOf(s) >= 0; }) &&
      files.every(function (found) {
        var lay = found.layout;
        return (lay.width === p || lay.width === p + 1) && (lay.height === p || lay.height === p + 1) &&
          onDegree(lay.x0) && onDegree(lay.y0);
      });
    if (!whole) return { tile: 0, missing: missing, edges: edges };
    /** @type {Map<string, number[]>} */
    var supplied = new Map();
    offsets.forEach(function (o, k) {
      var key = floorDiv(o[0], p) + ',' + floorDiv(o[1], p);
      if (!supplied.has(key)) supplied.set(key, []);
      /** @type {number[]} */ (supplied.get(key)).push(k);
    });
    /* the tile columns and rows the window meets, ascending: the tile of
     * each window cell never decreases along a row or a column */
    var columns = [], rows = [], k, t;
    for (k = 0; k < width; k++) {
      t = floorDiv(iFirst + k, p);
      if (!columns.length || columns[columns.length - 1] !== t) columns.push(t);
    }
    for (k = 0; k < height; k++) {
      t = floorDiv(jFirst + k, p);
      if (!rows.length || rows[rows.length - 1] !== t) rows.push(t);
    }
    rows.forEach(function (ty) {
      columns.forEach(function (tx) {
        if (!supplied.has(tx + ',' + ty)) missing.push([tx, ty]);
      });
    });
    missing.forEach(function (tile, m) {
      var tx = tile[0], ty = tile[1];
      /* the neighbour to the north gives its last row, to the south its
       * first, to the west its last column, to the east its first */
      [[tx, ty - 1, 'last_row'], [tx, ty + 1, 'first_row'], [tx - 1, ty, 'last_column'],
        [tx + 1, ty, 'first_column']].forEach(function (side) {
        (supplied.get(side[0] + ',' + side[1]) || []).forEach(function (k) {
          var lay = files[k].layout;
          if (side[2] === 'last_row') edges.push({ missing: m, file: k, row: lay.height - 1, column: null });
          else if (side[2] === 'first_row') edges.push({ missing: m, file: k, row: 0, column: null });
          else if (side[2] === 'last_column') edges.push({ missing: m, file: k, row: null, column: lay.width - 1 });
          else edges.push({ missing: m, file: k, row: null, column: 0 });
        });
      });
    });
    return { tile: p, missing: missing, edges: edges };
  }

  /* How many blocks of `size` cells along an axis of `extent` cells hold one
   * of the window's `n` cells from `first` on, in the file's own cell
   * numbering: elevation._blocks_met at stride 1, where every block the
   * window spans holds one, so the count is worked out, never listed. */
  function elevationBlocksMet(extent, size, first, n) {
    var low = first > 0 ? first : 0, high = first + n < extent ? first + n : extent;
    return low < high ? Math.floor((high - 1) / size) - Math.floor(low / size) + 1 : 0;
  }

  /* The blocks each file gives up, counted without listing them:
   * elevation._count_blocks. The block rows holding a window row times the
   * block columns holding a window column (a strip spans every column, so
   * it is one block column), and the blocks holding each full edge, a row
   * of tiles or a column of them (or of strips). */
  function elevationCountBlocks(files, offsets, iFirst, jFirst, width, height, edges) {
    return files.map(function (found, k) {
      var lay = found.layout;
      var count = elevationBlocksMet(lay.height, lay.blockHeight, jFirst - offsets[k][1], height) *
        elevationBlocksMet(lay.width, lay.blockWidth, iFirst - offsets[k][0], width);
      edges.forEach(function (edge) {
        if (edge.file !== k) return;
        count += edge.row !== null ? Math.ceil(lay.width / lay.blockWidth) : Math.ceil(lay.height / lay.blockHeight);
      });
      return count;
    });
  }

  /* The blocks to read, file by file in plan order and each file's blocks
   * in its own order: those the window's cells lie in, and those holding
   * the edges, each block (keyed by its index and the rows read of it)
   * once, sorted by index and then rows, a whole block first. */
  function elevationPlanBlocks(files, offsets, iFirst, jFirst, width, height, edges) {
    /** @type {PlanBlock[]} */
    var planned = [];
    files.forEach(function (found, k) {
      var lay = found.layout, oi = offsets[k][0], oj = offsets[k][1];
      /** @type {Map<string, PlanBlock>} */
      var wanted = new Map();
      function want(range, inWindow) {
        var key = range[0] + '|' + (range[3] ? range[3][0] + ',' + range[3][1] : '');
        if (!wanted.has(key)) {
          wanted.set(key, { file: k, index: range[0], offset: range[1], length: range[2], rows: range[3],
            window: inWindow, edges: [] });
        }
        return /** @type {PlanBlock} */ (wanted.get(key));
      }
      blockRanges(lay, jFirst - oj, jFirst - oj + (height - 1) + 1, iFirst - oi,
        iFirst - oi + (width - 1) + 1).forEach(function (range) {
        var origin = elevationBlockOrigin(lay, range[0], range[3]);
        var shape = elevationBlockShape(lay, range[0], range[3]);
        if (elevationSteps(origin[0] + oj, shape[0], jFirst, height) === null ||
            elevationSteps(origin[1] + oi, shape[1], iFirst, width) === null) return;
        want(range, true);
      });
      edges.forEach(function (edge, e) {
        if (edge.file !== k) return;
        var ranges = edge.row !== null ? blockRanges(lay, edge.row, edge.row + 1, 0, lay.width)
          : blockRanges(lay, 0, lay.height, /** @type {number} */ (edge.column),
            /** @type {number} */ (edge.column) + 1);
        ranges.forEach(function (range) { want(range, false).edges.push(e); });
      });
      Array.from(wanted.values()).sort(function (a, b) {
        if (a.index !== b.index) return a.index - b.index;
        var ra = a.rows || [-1, -1], rb = b.rows || [-1, -1];
        return ra[0] !== rb[0] ? ra[0] - rb[0] : ra[1] - rb[1];
      }).forEach(function (block) { planned.push(block); });
    });
    return planned;
  }

  /** The reads that bring in a plan's blocks: the ranges of each file to
   * read, file by file in plan order and in order of offset within a file,
   * neighbouring blocks read together (within 64 KiB of each other, up to
   * 16 MiB a read), as Python reads them. Each is {file, name, offset,
   * length, blocks}: read `length` bytes of the file called `name` from
   * `offset`, and hand each plan block b listed in `blocks` its own bytes,
   * plan.blocks[b].length of them from plan.blocks[b].offset. A block with
   * nothing to read (a sparse one) is in no read.
   * @param {WindowPlan} plan what planElevationWindow gave
   * @returns {ElevationRange[]}
   */
  function elevationBlockRanges(plan) {
    /** @type {Map<number, number[]>} */
    var byFile = new Map();
    plan.blocks.forEach(function (block, b) {
      if (!block.length) return;
      if (!byFile.has(block.file)) byFile.set(block.file, []);
      /** @type {number[]} */ (byFile.get(block.file)).push(b);
    });
    /** @type {ElevationRange[]} */
    var reads = [];
    byFile.forEach(function (members, k) {
      members.sort(function (a, b) { return plan.blocks[a].offset - plan.blocks[b].offset; });
      /** @type {number[][]} */
      var groups = [];
      var start = 0, end = 0;
      members.forEach(function (b) {
        var block = plan.blocks[b], stop = block.offset + block.length;
        if (groups.length && block.offset <= end + ELEVATION_MERGE_GAP &&
            (end > stop ? end : stop) - start <= ELEVATION_MERGE_MAX) {
          groups[groups.length - 1].push(b);
          end = end > stop ? end : stop;
        } else {
          groups.push([b]);
          start = block.offset;
          end = stop;
        }
      });
      groups.forEach(function (group) {
        var first = plan.blocks[group[0]].offset, last = 0;
        group.forEach(function (b) {
          var stop = plan.blocks[b].offset + plan.blocks[b].length;
          if (stop > last) last = stop;
        });
        reads.push({ file: k, name: plan.files[k].name, offset: first, length: last - first, blocks: group });
      });
    });
    return reads;
  }

  /* `count` as a whole percentage of `cells`, half up, as
   * elevation._percent gives it: integers alone (all under 2^53, so the
   * division is exact enough to floor), and a share short of the whole at
   * most 99, since "100%" while some cell was read contradicts itself */
  function elevationPercent(count, cells) {
    var pct = Math.floor((200 * count + cells) / (2 * cells));
    return count < cells && pct === 100 ? 99 : pct;
  }

  /* a tile of the plan's reference lattice named by its south-west corner,
   * as tiles are: "N07 W013" */
  function planTileCode(plan, tile) {
    var lon0 = Math.floor(plan.x0 + 0.5) + tile[0];
    var lat0 = Math.floor(plan.y0 + 0.5) - 1 - tile[1];
    return (lat0 >= 0 ? 'N' : 'S') + String(Math.abs(lat0)).padStart(2, '0') + ' ' +
      (lon0 >= 0 ? 'E' : 'W') + String(Math.abs(lon0)).padStart(3, '0');
  }

  /** Read the planned window, block by block, into one grid:
   * elevation.read_window. Each block's samples are judged first (no data,
   * a height that cannot be ground, or a height), then written where they
   * fall. Where files overlap, the first file's height is kept and every
   * other file's height there must be the same to the bit; any that differ
   * refuse the join, after every block is read. A missing tile is taken as
   * open sea, with no height, only when every height on the full edges of
   * the supplied tiles beside it is at or below sea level; any other cell
   * no file covers is a gap. With no height in the window at all, it is
   * refused.
   *
   * `blocks[b]` holds the bytes of plan.blocks[b] (its `length` bytes from
   * its `offset`, as elevationBlockRanges' reads bring them in); a block
   * with nothing to read needs none. `progress(fraction, label)`, when
   * given, is told how far the read has gone.
   *
   * The read holds the grid ({lons, lats, z south row first, rows, cols,
   * shown, assumedSea, sourceId, seaClean, label, credit, notice, surface,
   * files, cellNote}); the square shown as rows [r0, r1) and columns
   * [c0, c1) of it; assumedSea, 1 where a missing tile was taken as sea;
   * reasons, why each cell holds what it does (0 a height, 1 no data,
   * 2 implausible, 3 not supplied, assumed sea included), south row first;
   * the counts of cells, voids, implausible heights, cells no file covers
   * (uncovered, not counting assumed sea) and assumed sea, and the share
   * covered; the read report (notes) sentence by sentence in the order the
   * apps print it, what is said about single files (prompts), the surface
   * note, the Copernicus notice or null, the credit line a figure carries
   * (figureCredit), and the plan itself, as Python's read keeps it, so
   * that terrainCaptions states the radius and margin the window was read
   * at.
   * @param {WindowPlan} plan what planElevationWindow gave
   * @param {Array<Uint8Array|null|undefined>} blocks each planned block's bytes, by its place in plan.blocks
   * @param {Rec|null} [cfg] the project's configuration (or a part of it, as withConfig takes)
   * @param {((fraction: number, label: string) => void)|null} [progress]
   * @returns {Rec}
   */
  function readElevationWindow(plan, blocks, cfg, progress) {
    var terrain = withConfig(cfg).terrain;
    var labelRead = phrase('terrain.stage_read');
    if (progress) progress(0.0, labelRead);
    var width = plan.width, height = plan.height, cells = width * height;
    var iFirst = plan.ci - plan.hx, jFirst = plan.cj - plan.hy;
    /* row 0 north while reading */
    var win = new Float64Array(cells).fill(NaN);
    var why = new Uint8Array(cells).fill(3);
    var owner = new Int32Array(cells).fill(-1);
    var edgeCount = plan.missing.map(function () { return 0; });
    var edgeLand = plan.missing.map(function () { return false; });
    var disagreements = 0, largest = 0.0;
    /* the files of the first disagreement: the one already holding the
     * cell, and the one that disagrees with it */
    /** @type {Array<[string, string]>} */
    var pair = [];
    /** @type {[number, number]} */
    var bounds = [terrain.implausible_below_m, terrain.implausible_above_m];
    var seaLevel = terrain.sea_level_m;
    var empty = new Uint8Array(0);

    plan.blocks.forEach(function (block, b) {
      var lay = plan.files[block.file].layout;
      var decoded = decodeTiffBlock(lay, block.index, blocks[b] || empty, block.rows, bounds);
      var values = decoded.values, reasons = decoded.reasons, cols = decoded.cols;
      var origin = elevationBlockOrigin(lay, block.index, block.rows), row0 = origin[0], col0 = origin[1];
      if (block.window) {
        var oi = plan.offsets[block.file][0], oj = plan.offsets[block.file][1];
        var down = elevationSteps(row0 + oj, decoded.rows, jFirst, height);
        var across = elevationSteps(col0 + oi, cols, iFirst, width);
        if (down !== null && across !== null) {
          /* window cell (q, k) is the block's cell (q - dr, k - dc) */
          var dr = row0 + oj - jFirst, dc = col0 + oi - iFirst;
          for (var q = down[0]; q <= down[1]; q++) {
            for (var k = across[0]; k <= across[1]; k++) {
              var at = (q - dr) * cols + (k - dc), c = q * width + k;
              var v = values[at], reason = reasons[at];
              if (reason === 0) {
                if (why[c] === 0) {
                  if (win[c] !== v) {
                    disagreements += 1;
                    var gap = Math.abs(win[c] - v);
                    if (gap > largest) largest = gap;
                    if (!pair.length) pair.push([plan.files[owner[c]].name, plan.files[block.file].name]);
                  }
                } else {
                  win[c] = v;
                  why[c] = 0;
                  owner[c] = block.file;
                }
              } else if (why[c] !== 0 && reason < why[c]) {
                why[c] = reason;
              }
            }
          }
        }
      }
      block.edges.forEach(function (e) {
        var edge = plan.edges[e], i, n, at, step;
        if (edge.row !== null) {
          at = (edge.row - row0) * cols;
          n = cols;
          step = 1;
        } else {
          at = /** @type {number} */ (edge.column) - col0;
          n = decoded.rows;
          step = cols;
        }
        for (i = 0; i < n; i++, at += step) {
          if (reasons[at] !== 0) continue;
          edgeCount[edge.missing] += 1;
          if (values[at] > seaLevel) edgeLand[edge.missing] = true;
        }
      });
      if (progress) progress((b + 1) / plan.blocks.length, labelRead);
    });

    if (disagreements) {
      throw tiffError('terrain.join_disagree', { a: pair[0][0], b: pair[0][1], n: disagreements, m: largest });
    }

    /* a missing tile is sea, with no height, when the full edges beside it
     * hold heights and every one of them is at or below sea level */
    var sea = new Uint8Array(cells);
    /** @type {string[]} */
    var seaTiles = [];
    if (plan.missing.length) {
      /** @type {number[]} */
      var tileX = [];
      /** @type {number[]} */
      var tileY = [];
      for (var x = 0; x < width; x++) tileX.push(floorDiv(iFirst + x, plan.tile));
      for (var y = 0; y < height; y++) tileY.push(floorDiv(jFirst + y, plan.tile));
      plan.missing.forEach(function (tile, m) {
        if (!(edgeCount[m] && !edgeLand[m])) return;
        /* a tile is named only when some window cell of it is taken as sea:
         * a window reaching just the row or column an .hgt tile shares with
         * the next meets that tile without a cell of it going uncovered */
        var found = false;
        for (var r = 0; r < height; r++) {
          if (tileY[r] !== tile[1]) continue;
          for (var col = 0; col < width; col++) {
            if (tileX[col] === tile[0] && why[r * width + col] === 3) {
              sea[r * width + col] = 1;
              found = true;
            }
          }
        }
        if (found) seaTiles.push(planTileCode(plan, tile));
      });
    }
    var voids = 0, implausible = 0, open = 0, assumed = 0, held = 0, i;
    for (i = 0; i < cells; i++) {
      if (why[i] === 0) held += 1;
      else if (why[i] === 1) voids += 1;
      else if (why[i] === 2) implausible += 1;
      else open += 1;
      assumed += sea[i];
    }
    if (!held) {
      throw tiffError('terrain.no_elevations', { radius: plan.radiusKm, where: plan.centre.label });
    }
    var uncovered = open - assumed;
    var credited = terrainCredit(plan.files, plan.declared);
    var dx = plan.dx, dy = plan.dy;
    /* the files read are those with a block in the plan, an edge block
     * included, in plan order; the label and credit stay the whole set's */
    var used = plan.files.map(function () { return false; });
    plan.blocks.forEach(function (block) { used[block.file] = true; });
    var names = plan.files.filter(function (f, k) { return used[k]; }).map(function (f) { return f.name; });

    /* the grid, the mask and the reasons south row first */
    var z = new Float64Array(cells), seaSouth = new Uint8Array(cells), whySouth = new Uint8Array(cells);
    for (var row = 0; row < height; row++) {
      var from = (height - 1 - row) * width;
      z.set(win.subarray(from, from + width), row * width);
      seaSouth.set(sea.subarray(from, from + width), row * width);
      whySouth.set(why.subarray(from, from + width), row * width);
    }
    var cellNote = elevationCellNote(dx, dy);
    /* the summary counts the square shown, which is what its radius
     * describes; the margin read beyond it has a sentence of its own */
    var shown = plan.shown;
    var notes = [phrase('terrain.read_summary', { n: names.length, names: andJoin(names),
      cells: (shown[1] - shown[0]) * (shown[3] - shown[2]), dx: dx, dy: dy, where: plan.centre.label,
      radius: plan.radiusKm })];
    if (plan.centre.note) notes.push(plan.centre.note);
    if (plan.marginKm > 0) notes.push(phrase('terrain.read_margin', { margin: plan.marginKm }));
    if (uncovered && 200 * uncovered < cells) {
      notes.push(phrase('terrain.read_uncovered_little', { count: uncovered }));
    } else if (uncovered) {
      notes.push(phrase('terrain.read_uncovered', { pct: elevationPercent(uncovered, cells) }));
    }
    if (assumed && 200 * assumed < cells) {
      notes.push(phrase('terrain.read_assumed_sea_little', { count: assumed, n: seaTiles.length,
        tiles: andJoin(seaTiles), level: seaLevel, product: PRODUCT_NAMES[setSource(plan.sources)] }));
    } else if (assumed) {
      notes.push(phrase('terrain.read_assumed_sea', { pct: elevationPercent(assumed, cells), n: seaTiles.length,
        tiles: andJoin(seaTiles), level: seaLevel, product: PRODUCT_NAMES[setSource(plan.sources)] }));
    }
    if (voids) notes.push(phrase('terrain.read_voids', { n: voids }));
    if (implausible) {
      notes.push(phrase('terrain.read_implausible', { n: implausible, lo: terrain.implausible_below_m,
        hi: terrain.implausible_above_m }));
    }
    notes.push(credited.surface);
    var figureCredit = credited.credit
      ? phrase('terrain.figure_credit', { label: credited.label, credit: credited.credit, dx: dx, dy: dy })
      : phrase('terrain.figure_credit_bare', { label: credited.label, dx: dx, dy: dy });
    /** @type {string[]} */
    var prompts = [];
    plan.files.forEach(function (f) {
      fileNotes(f, plan.declared).forEach(function (note) { prompts.push(note); });
    });
    if (progress) progress(1.0, labelRead);
    var grid = {
      lons: plan.lons, lats: plan.lats, z: z, rows: height, cols: width, shown: plan.shown.slice(),
      assumedSea: seaSouth, sourceId: setSource(plan.sources), seaClean: credited.seaClean,
      label: credited.label, credit: credited.credit, notice: credited.notice, surface: credited.surface,
      files: names, cellNote: cellNote,
    };
    return {
      grid: grid, assumedSea: seaSouth, reasons: whySouth, shown: plan.shown.slice(), cells: cells,
      voids: voids, uncovered: uncovered, implausible: implausible, assumed: assumed,
      coverage: (cells - uncovered - assumed) / cells, centre: plan.centre, notes: notes, prompts: prompts,
      surface: credited.surface, notice: credited.notice, figureCredit: figureCredit, plan: plan,
    };
  }

  Object.assign(C, {
    hgtLayout: hgtLayout, elevationFile: elevationFile, fileNotes: fileNotes, terrainCredit: terrainCredit,
    sinCosDeg: sinCosDeg, wgs84CellSize: wgs84CellSize, rowMetric: rowMetric, windowCentre: windowCentre,
    planElevationWindow: planElevationWindow, elevationBlockRanges: elevationBlockRanges,
    readElevationWindow: readElevationWindow,
  });
