
  /* ================================================================== geodesy
   * groundwater/geo.py. Sierra Leone straddles UTM zones 28N and 29N; the
   * easting alone identifies the zone, because in-country the valid ranges
   * cannot overlap (zone 28N runs about 620000-800000, zone 29N 200000-500000).
   */

  /**
   * @param {number|string} easting
   * @returns {number}
   */
  function inferZoneForSierraLeone(easting) {
    return Number(easting) > 550000 ? 28 : 29;
  }

  /**
   * @param {number} lon
   * @returns {number}
   */
  function utmZoneFromLon(lon) {
    return Math.floor((lon + 180) / 6) + 1;
  }

  /* WGS84 geographic -> UTM, the Krueger series (Karney 2011, terms to n^4)
   * the package uses, so a pasted position lands on the same metre. */
  var GEO_A = 6378137.0;
  var GEO_F = 1 / 298.257223563;
  var GEO_E = Math.sqrt(GEO_F * (2 - GEO_F));
  var GEO_N = GEO_F / (2 - GEO_F);
  var GEO_K0 = 0.9996;
  var GEO_FALSE_EASTING = 500000.0;
  var GEO_A1 = GEO_A / (1 + GEO_N) *
    (1 + Math.pow(GEO_N, 2) / 4 + Math.pow(GEO_N, 4) / 64);
  var GEO_ALPHA = [
    GEO_N / 2 - 2 * Math.pow(GEO_N, 2) / 3 + 5 * Math.pow(GEO_N, 3) / 16 +
      41 * Math.pow(GEO_N, 4) / 180,
    13 * Math.pow(GEO_N, 2) / 48 - 3 * Math.pow(GEO_N, 3) / 5 +
      557 * Math.pow(GEO_N, 4) / 1440,
    61 * Math.pow(GEO_N, 3) / 240 - 103 * Math.pow(GEO_N, 4) / 140,
    49561 * Math.pow(GEO_N, 4) / 161280,
  ];

  /**
   * @param {number} lat
   * @param {number} lon
   * @param {number|null} [zone]
   */
  function geographicToUtm(lat, lon, zone) {
    var band = zone || utmZoneFromLon(lon);
    var lam0 = (-183.0 + 6.0 * band) * Math.PI / 180;
    var phi = lat * Math.PI / 180;
    var lam = lon * Math.PI / 180 - lam0;

    var t = Math.tan(phi);
    var sigma = Math.sinh(GEO_E * Math.atanh(GEO_E * t / Math.sqrt(1 + t * t)));
    var tauP = t * Math.sqrt(1 + sigma * sigma) - sigma * Math.sqrt(1 + t * t);

    var xiP = Math.atan2(tauP, Math.cos(lam));
    var etaP = Math.asinh(Math.sin(lam) / Math.hypot(tauP, Math.cos(lam)));

    var xi = xiP, eta = etaP;
    GEO_ALPHA.forEach(function (alpha, index) {
      var j = index + 1;
      xi += alpha * Math.sin(2 * j * xiP) * Math.cosh(2 * j * etaP);
      eta += alpha * Math.cos(2 * j * xiP) * Math.sinh(2 * j * etaP);
    });

    var northing = GEO_K0 * GEO_A1 * xi;
    var hemisphere = 'N';
    if (lat < 0) { northing += 10000000.0; hemisphere = 'S'; }
    return {
      easting: GEO_FALSE_EASTING + GEO_K0 * GEO_A1 * eta,
      northing: northing, zone: band, hemisphere: hemisphere,
    };
  }

  var GEO_E2 = GEO_F * (2 - GEO_F);
  var GEO_BETA = [
    GEO_N / 2 - 2 * Math.pow(GEO_N, 2) / 3 + 37 * Math.pow(GEO_N, 3) / 96 -
      Math.pow(GEO_N, 4) / 360,
    Math.pow(GEO_N, 2) / 48 + Math.pow(GEO_N, 3) / 15 -
      437 * Math.pow(GEO_N, 4) / 1440,
    17 * Math.pow(GEO_N, 3) / 480 - 37 * Math.pow(GEO_N, 4) / 840,
    4397 * Math.pow(GEO_N, 4) / 161280,
  ];

  /** WGS84 UTM -> geographic, the same Krueger inverse the package uses, so a
   * position converted here and a position converted there are the same
   * position rather than two that happen to be close.
   * @param {number} easting
   * @param {number} northing
   * @param {number} zone
   * @param {string|null} [hemisphere] 'N' unless it says 'S'
   * @returns {{lat: number, lon: number}|null}
   */
  function utmToGeographic(easting, northing, zone, hemisphere) {
    var y = northing;
    if (String(hemisphere || 'N').toUpperCase().charAt(0) === 'S') y -= 10000000.0;
    var xi = y / (GEO_K0 * GEO_A1);
    var eta = (easting - GEO_FALSE_EASTING) / (GEO_K0 * GEO_A1);

    var xiP = xi, etaP = eta;
    GEO_BETA.forEach(function (beta, index) {
      var j = index + 1;
      xiP -= beta * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta);
      etaP -= beta * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta);
    });

    var tauP = Math.sin(xiP) / Math.hypot(Math.sinh(etaP), Math.cos(xiP));
    var lam = Math.atan2(Math.sinh(etaP), Math.cos(xiP));

    /* invert tau'(tau) by Newton iteration (Karney 2011) */
    var tau = tauP / Math.sqrt(1 - GEO_E2);
    for (var i = 0; i < 10; i++) {
      var sigma = Math.sinh(GEO_E * Math.atanh(GEO_E * tau / Math.sqrt(1 + tau * tau)));
      var fTau = tau * Math.sqrt(1 + sigma * sigma) - sigma * Math.sqrt(1 + tau * tau);
      var dTau = (Math.sqrt((1 + sigma * sigma) * (1 + tau * tau)) - sigma * tau) *
        (1 - GEO_E2) * Math.sqrt(1 + tau * tau) / (1 + (1 - GEO_E2) * tau * tau);
      var delta = (tauP - fTau) / dTau;
      tau += delta;
      if (Math.abs(delta) < 1e-14) break;
    }

    var out = {
      lat: Math.atan(tau) * 180 / Math.PI,
      lon: lam * 180 / Math.PI + (-183.0 + 6.0 * zone),
    };
    return isFinite(out.lat) && isFinite(out.lon) ? out : null;
  }

  /** Distance in metres between two WGS84 points, along the ellipsoid.
   * Vincenty's inverse formula - the same one groundwater/geo.py uses, so the
   * two engines report the same separation rather than two that happen to be
   * close. Vincenty does not converge for near-antipodal points; nothing in a
   * country survey is antipodal, but the spherical value is returned rather
   * than failing if it ever happens.
   * @param {number} lat1
   * @param {number} lon1
   * @param {number} lat2
   * @param {number} lon2
   * @returns {number}
   */
  function geodesicDistanceM(lat1, lon1, lat2, lon2) {
    if (lat1 === lat2 && lon1 === lon2) return 0.0;
    var b = GEO_A * (1 - GEO_F);
    var phi1 = lat1 * Math.PI / 180, phi2 = lat2 * Math.PI / 180;
    var lDiff = (lon2 - lon1) * Math.PI / 180;
    var u1 = Math.atan((1 - GEO_F) * Math.tan(phi1));
    var u2 = Math.atan((1 - GEO_F) * Math.tan(phi2));
    var sinU1 = Math.sin(u1), cosU1 = Math.cos(u1);
    var sinU2 = Math.sin(u2), cosU2 = Math.cos(u2);

    var lam = lDiff, sinSigma = 0, cosSigma = 0, sigma = 0;
    var cosSqAlpha = 0, cos2SigmaM = 0, converged = false;
    for (var i = 0; i < 200; i++) {
      var sinLam = Math.sin(lam), cosLam = Math.cos(lam);
      sinSigma = Math.hypot(cosU2 * sinLam,
        cosU1 * sinU2 - sinU1 * cosU2 * cosLam);
      if (sinSigma === 0) return 0.0;   // coincident points
      cosSigma = sinU1 * sinU2 + cosU1 * cosU2 * cosLam;
      sigma = Math.atan2(sinSigma, cosSigma);
      var sinAlpha = cosU1 * cosU2 * sinLam / sinSigma;
      cosSqAlpha = 1 - sinAlpha * sinAlpha;
      cos2SigmaM = cosSqAlpha !== 0
        ? cosSigma - 2 * sinU1 * sinU2 / cosSqAlpha
        : 0.0;                          // equatorial line
      var c = GEO_F / 16 * cosSqAlpha * (4 + GEO_F * (4 - 3 * cosSqAlpha));
      var lamPrev = lam;
      lam = lDiff + (1 - c) * GEO_F * sinAlpha * (sigma + c * sinSigma *
        (cos2SigmaM + c * cosSigma * (-1 + 2 * cos2SigmaM * cos2SigmaM)));
      if (Math.abs(lam - lamPrev) < 1e-12) { converged = true; break; }
    }
    if (!converged) return geodesicHaversineM(lat1, lon1, lat2, lon2);

    var uSq = cosSqAlpha * (GEO_A * GEO_A - b * b) / (b * b);
    var bigA = 1 + uSq / 16384 * (4096 + uSq * (-768 + uSq * (320 - 175 * uSq)));
    var bigB = uSq / 1024 * (256 + uSq * (-128 + uSq * (74 - 47 * uSq)));
    var deltaSigma = bigB * sinSigma * (cos2SigmaM + bigB / 4 * (
      cosSigma * (-1 + 2 * cos2SigmaM * cos2SigmaM) -
      bigB / 6 * cos2SigmaM * (-3 + 4 * sinSigma * sinSigma) *
        (-3 + 4 * cos2SigmaM * cos2SigmaM)));
    return b * bigA * (sigma - deltaSigma);
  }

  /* Non-convergence fallback only. Deliberately not the exported haversineM
   * used for water points: that one mirrors waterpoints.py and uses a
   * different earth radius. */
  function geodesicHaversineM(lat1, lon1, lat2, lon2) {
    var radius = 6371008.8;
    var phi1 = lat1 * Math.PI / 180, phi2 = lat2 * Math.PI / 180;
    var dPhi = phi2 - phi1;
    var dLam = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dPhi / 2) * Math.sin(dPhi / 2) +
      Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLam / 2) * Math.sin(dLam / 2);
    return 2 * radius * Math.asin(Math.min(1.0, Math.sqrt(a)));
  }

  /** Ground distance between two UTM points, each read in its own zone.
   * Subtracting eastings from different zones is meaningless: the false
   * easting restarts at every central meridian, so two sites a couple of
   * kilometres apart either side of the 12 degrees W boundary between zones
   * 28N and 29N differ by hundreds of thousands of metres on paper.
   * @param {{easting: number, northing: number, zone: number, hemisphere?: string|null}} a
   * @param {{easting: number, northing: number, zone: number, hemisphere?: string|null}} b
   * @returns {number|null}
   */
  function utmDistanceM(a, b) {
    var p = utmToGeographic(a.easting, a.northing, a.zone, a.hemisphere);
    var q = utmToGeographic(b.easting, b.northing, b.zone, b.hemisphere);
    if (!p || !q) return null;
    return geodesicDistanceM(p.lat, p.lon, q.lat, q.lon);
  }

  /* Sierra Leone's own extent, in degrees: about 6.9 to 10.0 north, and 10.3
   * to 13.3 WEST. These bands recognise a longitude typed without its western
   * sign; nothing here moves a coordinate that carries a sign or a letter. */
  var SIERRA_LEONE_LAT_BAND = [6.9, 10.0];
  var SIERRA_LEONE_LON_BAND = [-13.3, -10.3];

  var ZONE_NUMBER_RE = /\d+(?:\.\d+)?/g;

  /* The datum a GPS writes beside the zone. Its 84 is a year, not a second
   * zone, so it is taken out before the numbers in the cell are counted. */
  var DATUM_RE = /WGS\s*-?\s*84(?!\d)/gi;

  /** The UTM zone a cell states, or null when it states no single zone.
   *
   * Sheets write the zone as "28N", "28", "zone 28" or - when the operator
   * copies the label into the value cell - "Zone 28". Reading such a cell
   * means taking the number that follows the label and nothing else. A value
   * cell mistaken for a label let the neighbouring easting through as the
   * zone, so a site recorded in zone 28N was carried as "zone 708958" and
   * projected tens of degrees from the survey.
   *
   * A cell naming more than one number states no single zone - "28N or 29N"
   * is the sheet's own instruction, not an answer - and neither does a number
   * outside the 1 to 60 a UTM zone can be. Both are refused rather than
   * guessed at, so the caller can say the zone is unrecorded and fall back to
   * the easting.
   *
   * The datum is not a second number: "28N WGS84" and "WGS 84 / UTM zone
   * 28N", which is how a handheld GPS and a GIS write the zone, were refused
   * for naming two numbers, and the sheet was then flagged "UTM zone not
   * recorded" when it had recorded one. Nor is a spreadsheet's float: a zone
   * cell read back as "28.0" states zone 28.
   * @param {*} value a cell
   * @returns {number|null}
   */
  function parseUtmZone(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === 'boolean') return null;
    var numbers;
    if (typeof value === 'number') {
      numbers = [value];
    } else {
      var text = String(value).replace(DATUM_RE, ' ');
      ZONE_NUMBER_RE.lastIndex = 0;
      var found = text.match(ZONE_NUMBER_RE);
      numbers = (found || []).map(Number);
    }
    if (numbers.length !== 1) return null;
    var number = numbers[0];
    if (!isFinite(number) || Math.trunc(number) !== number) return null;
    if (!(number >= 1 && number <= 60)) return null;
    return number;
  }

  /* --- a pasted "lat, lon", as a field crew writes it ----------------------
   *
   * Every longitude in Sierra Leone is west, and a handheld GPS writes that
   * as a W rather than a minus sign. Discarding the letter and taking the
   * number at face value puts the site 26 degrees east of where it is -
   * silently, on the wrong side of the continent - so the letter is read as a
   * sign. A letter that contradicts an explicit sign ("-13.2317 E") is
   * refused rather than guessed at, and an explicit E/W on the first value
   * means the pair was written longitude first. */

  var LATLON_TOKEN_RE = /^([+-]?\d*\.?\d+)\s*([NSEWnsew])?$/;
  var HEMISPHERES = ['N', 'S', 'E', 'W'];

  /* Degree, minute and second marks as a phone, a handheld GPS or a sheet
   * writes them; they separate the parts of a coordinate rather than
   * belonging to any of them, so they are read as spaces. */
  var SEXAGESIMAL_MARKS_RE =
    /[\u00b0\u00ba\u2218\u0027\u2019\u2032\u0022\u201d\u2033]/g;

  var LATLON_UNREADABLE = 'Could not read those coordinates.';
  var LATLON_AMBIGUOUS = 'Two numbers with nothing between them are either ' +
    'a decimal pair or one degrees-and-minutes value. Separate a pair with ' +
    'a comma (8.4657, -13.2317), or mark the hemispheres ' +
    '(8 27.942 N, 13 13.902 W).';

  /* A coordinate the parser will not read, carrying the reason why. Thrown
   * rather than returned so the token loop can refuse from where it stands,
   * the way the Python parser raises. */
  function coordinateRefused(code, message) {
    /** @type {Error & {refusedCoordinate?: boolean, code?: string}} */
    var refusal = new Error(message);
    refusal.refusedCoordinate = true;
    refusal.code = code;
    return refusal;
  }

  /* Split a pasted coordinate into its two components. Numbers accumulate
   * into the component being read. A hemisphere letter, a comma or
   * semicolon, or an explicit sign ends that component and starts the next,
   * because a number of minutes or seconds is never signed and never carries
   * a hemisphere of its own. */
  function latLonComponents(raw) {
    var components = [];
    var current = /** @type {Rec|null} */ (null);

    function openComponent(letter) {
      current = { numbers: [], letter: letter === undefined ? null : letter,
        signed: false, negative: false };
      components.push(current);
      return current;
    }

    var segments = raw.replace(SEXAGESIMAL_MARKS_RE, ' ').split(/[,;]/);
    for (var s = 0; s < segments.length; s++) {
      if (s) current = null;
      var tokens = segments[s].split(/\s+/).filter(Boolean);
      for (var t = 0; t < tokens.length; t++) {
        var token = tokens[t];
        if (token.length === 1 && HEMISPHERES.indexOf(token.toUpperCase()) >= 0) {
          var bare = token.toUpperCase();
          if (current !== null && current.letter === null && current.numbers.length) {
            current.letter = bare;                 /* trailing "8.4657 N" */
            current = null;
          } else {
            current = null;
            openComponent(bare);                   /* leading "N 8.4657" */
          }
          continue;
        }
        var match = LATLON_TOKEN_RE.exec(token);
        if (match === null) {
          throw coordinateRefused('latlon_unreadable', LATLON_UNREADABLE);
        }
        var number = Number(match[1]);
        if (!isFinite(number)) {
          throw coordinateRefused('latlon_unreadable', LATLON_UNREADABLE);
        }
        var signed = match[1].charAt(0) === '+' || match[1].charAt(0) === '-';
        if (signed && current !== null && current.numbers.length) {
          current = null;                          /* "8 -13.2317" is a pair */
        }
        var component = current !== null ? current : openComponent();
        if (!component.numbers.length) {
          component.signed = signed;
          component.negative = match[1].charAt(0) === '-';
        }
        component.numbers.push(number);
        if (match[2]) {
          component.letter = match[2].toUpperCase();          /* "13.2317W" */
          current = null;
        }
      }
    }

    if (components.length === 1 && components[0].letter === null &&
        components[0].numbers.length === 2) {
      /* Nothing separates the two numbers, so they are either a decimal pair
       * or one degrees-and-minutes value. Where they could be either,
       * refusing is the only honest reading: "8 27.942" read as a pair lands
       * 2000 km from the same text read as degrees and minutes. */
      var only = components[0];
      var degrees = only.numbers[0], rest = only.numbers[1];
      if (degrees === Math.floor(degrees) && rest >= 0 && rest < 60) {
        throw coordinateRefused('latlon_unreadable', LATLON_AMBIGUOUS);
      }
      components = [
        { numbers: [degrees], letter: null,
          signed: only.signed, negative: only.negative },
        { numbers: [rest], letter: null, signed: false, negative: false },
      ];
    }
    return components;
  }

  /* One component of a pasted pair as signed decimal degrees. Read as decimal
   * degrees, "8 27.942 N" came back as latitude 27.942 and longitude 8: the
   * sheet's own numbers, in the wrong units and the wrong order. */
  function latLonComponentDegrees(component, what) {
    var numbers = component.numbers;
    if (!numbers.length || numbers.length > 3) {
      throw coordinateRefused('latlon_unreadable', LATLON_UNREADABLE);
    }
    var magnitude = Math.abs(numbers[0]);
    if (numbers.length > 1) {
      var minutes = numbers[1];
      if (magnitude !== Math.floor(magnitude)) {
        throw coordinateRefused('latlon_unreadable', 'Read the ' + what +
          ' as degrees and minutes, but ' + formatG(numbers[0]) +
          ' is not a whole number of degrees.');
      }
      if (!(minutes >= 0 && minutes < 60)) {
        throw coordinateRefused('latlon_unreadable', 'Read the ' + what +
          ' as degrees and minutes, but ' + formatG(minutes) +
          ' is not a number of minutes (0 up to 60).');
      }
      magnitude += minutes / 60.0;
      if (numbers.length === 3) {
        var seconds = numbers[2];
        if (minutes !== Math.floor(minutes)) {
          throw coordinateRefused('latlon_unreadable', 'Read the ' + what +
            ' as degrees, minutes and seconds, but ' + formatG(minutes) +
            ' is not a whole number of minutes.');
        }
        if (!(seconds >= 0 && seconds < 60)) {
          throw coordinateRefused('latlon_unreadable', 'Read the ' + what +
            ' as degrees, minutes and seconds, but ' + formatG(seconds) +
            ' is not a number of seconds (0 up to 60).');
        }
        magnitude += seconds / 3600.0;
      }
    }
    var negative = component.negative;
    var letter = component.letter;
    if (letter) {
      var letterNegative = letter === 'S' || letter === 'W';
      if (negative && !letterNegative) {
        throw coordinateRefused('latlon_sign_contradiction', 'The ' + what +
          ' is written both as a negative number and as ' + letter +
          ', which contradict each other.');
      }
      negative = negative || letterNegative;
    }
    return negative ? -magnitude : magnitude;
  }

  /** Read "lat, lon" as a field crew writes it, saying what was assumed:
   * { lat, lon, code, message } with lat and lon null when the text was
   * refused and message then saying why, in a sentence an operator can act
   * on. A reading that succeeded carries a code and a message only when
   * something was assumed rather than read.
   *
   * A positive longitude between 10.3 and 13.3 degrees, carrying neither a
   * sign nor a letter and paired with a latitude inside Sierra Leone's own
   * band, is a western longitude whose minus sign was never typed:
   * "8.4657, 13.2317" is Freetown short of a sign, not a site 2,900 km east
   * in central Africa. That reading is taken - the country is what this
   * toolkit is for, and read as written the pair used to be stored as a
   * zone-33 position under the zone the browser wrote beside it - but it is
   * the parser's reading rather than the sheet's, so it comes back under the
   * longitude_west_assumed code with a sentence saying what was assumed.
   * Nothing downstream may present it as read.
   * @param {*} text
   * @returns {{lat: number|null, lon: number|null, code?: string, message?: string}}
   */
  function readLatLon(text) {
    var raw = String(text === null || text === undefined ? '' : text).trim();
    if (!raw) {
      return { lat: null, lon: null, code: 'latlon_unreadable',
        message: LATLON_UNREADABLE };
    }
    var first, second, lat, lon;
    try {
      var components = latLonComponents(raw);
      if (!components.length) {
        throw coordinateRefused('latlon_unreadable', LATLON_UNREADABLE);
      }
      if (components.length < 2) {
        throw coordinateRefused('latlon_incomplete', 'Read one coordinate ' +
          'where a latitude and a longitude are both needed.');
      }
      if (components.length > 2) {
        throw coordinateRefused('latlon_incomplete', 'Read more than two ' +
          'values where only a latitude and a longitude are expected.');
      }
      first = components[0];
      second = components[1];
      if (first.letter === 'E' || first.letter === 'W' ||
          second.letter === 'N' || second.letter === 'S') {
        var swap = first; first = second; second = swap;
      }
      lat = latLonComponentDegrees(first, 'latitude');
      lon = latLonComponentDegrees(second, 'longitude');
    } catch (err) {
      if (!err || !err.refusedCoordinate) throw err;
      return { lat: null, lon: null, code: err.code, message: err.message };
    }
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      return { lat: null, lon: null, code: 'latlon_out_of_range',
        message: 'A latitude runs to 90 degrees and a longitude to 180; ' +
          'these do not.' };
    }
    if (lon > 0 && !second.signed && second.letter === null &&
        lat >= SIERRA_LEONE_LAT_BAND[0] && lat <= SIERRA_LEONE_LAT_BAND[1] &&
        -lon >= SIERRA_LEONE_LON_BAND[0] && -lon <= SIERRA_LEONE_LON_BAND[1]) {
      var written = formatG(lon);
      return { lat: lat, lon: -lon, code: 'longitude_west_assumed',
        message: 'Longitude ' + written + ' was read as ' + written + ' W: ' +
          'every longitude in Sierra Leone is west, and ' + written +
          ' east is some 2,900 km away in central Africa. Type -' + written +
          ' or ' + written + ' W to record the sign rather than leave it ' +
          'assumed.' };
    }
    return { lat: lat, lon: lon, code: '', message: '' };
  }

  Object.assign(C, {
    inferZoneForSierraLeone: inferZoneForSierraLeone,
    utmToGeographic: utmToGeographic, geographicToUtm: geographicToUtm,
    utmZoneFromLon: utmZoneFromLon, parseUtmZone: parseUtmZone,
    readLatLon: readLatLon,
    SIERRA_LEONE_LAT_BAND: SIERRA_LEONE_LAT_BAND,
    SIERRA_LEONE_LON_BAND: SIERRA_LEONE_LON_BAND,
    geodesicDistanceM: geodesicDistanceM, utmDistanceM: utmDistanceM,
  });
