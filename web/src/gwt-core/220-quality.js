
  /* ======================================================== water quality
   * groundwater/quality/*. The standards table itself is bundled data
   * (data/who_guidelines.csv, embedded by the build as GWT.data.whoGuidelines),
   * so a client with different national limits edits the table, not the code.
   */

  var RANGE_RE = /^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$/;

  /** A guideline limit: either a maximum or an allowed range like "6.5-8.5".
   * @param {*} text
   * @returns {Limit|null}
   */
  function parseLimit(text) {
    var s = String(text === null || text === undefined ? '' : text).trim();
    if (!s) return null;
    var m = RANGE_RE.exec(s);
    if (m) return { minimum: parseFloat(m[1]), maximum: parseFloat(m[2]) };
    var v = Number(s);
    if (!isFinite(v)) return null;
    return { minimum: null, maximum: v };
  }

  /**
   * @param {Limit|null|undefined} limit
   * @param {number} value
   * @returns {boolean}
   */
  function limitExceededBy(limit, value) {
    if (!limit) return false;
    if (limit.minimum !== null && limit.minimum !== undefined && value < limit.minimum) return true;
    if (limit.maximum !== null && limit.maximum !== undefined && value > limit.maximum) return true;
    return false;
  }

  /**
   * @param {Limit|null|undefined} limit
   * @returns {string}
   */
  function limitText(limit) {
    if (!limit) return '';
    if (limit.minimum !== null && limit.minimum !== undefined) {
      return formatG(limit.minimum) + '-' + formatG(limit.maximum);
    }
    if (limit.maximum !== null && limit.maximum !== undefined) return formatG(limit.maximum);
    return '';
  }

  var PARAMETER_ALIASES = {
    ec: 'electrical conductivity',
    conductivity: 'electrical conductivity',
    'total dissolved solids': 'tds',
    hardness: 'total hardness',
    nitrate: 'nitrate (as no3)',
    no3: 'nitrate (as no3)',
    nitrite: 'nitrite (as no2)',
    no2: 'nitrite (as no2)',
    ammonia: 'ammonia (as n)',
    ammonium: 'ammonia (as n)',
    nh3: 'ammonia (as n)',
    nh4: 'ammonia (as n)',
    chromium: 'chromium (total)',
    cr: 'chromium (total)',
    'faecal coliforms': 'e. coli',
    'fecal coliforms': 'e. coli',
    'e.coli': 'e. coli',
    'escherichia coli': 'e. coli',
    coliforms: 'total coliforms',
    sulphate: 'sulfate',
    so4: 'sulfate',
    aluminum: 'aluminium',
    /* the spellings a Sierra Leone certificate actually carries */
    'total alkalinity': 'alkalinity',
    'alkalinity (as caco3)': 'alkalinity',
    'alkalinity as caco3': 'alkalinity',
    'total alkalinity as caco3': 'alkalinity',
    'total iron': 'iron',
    'iron (total)': 'iron',
    'total dissolved solid': 'tds',
    'dissolved solids': 'tds',
    'specific conductance': 'electrical conductivity',
    'ph value': 'ph',
    color: 'colour',
    'true colour': 'colour',
    'apparent colour': 'colour',
    'thermotolerant coliforms': 'e. coli',
    'thermotolerant coliform': 'e. coli',
    'faecal coliform': 'e. coli',
    'fecal coliform': 'e. coli',
    'total coliform': 'total coliforms',
    'residual chlorine': 'free chlorine',
    'chlorine residual': 'free chlorine',
    'free residual chlorine': 'free chlorine',
    'nitrate-n': 'nitrate (as n)',
    'nitrate n': 'nitrate (as n)',
    'nitrate as n': 'nitrate (as n)',
    'nitrate nitrogen': 'nitrate (as n)',
    'no3-n': 'nitrate (as n)',
    'nitrite-n': 'nitrite (as n)',
    'nitrite n': 'nitrite (as n)',
    'nitrite as n': 'nitrite (as n)',
    'nitrite nitrogen': 'nitrite (as n)',
    'no2-n': 'nitrite (as n)',
    orthophosphate: 'phosphate',
    'phosphate (as po4)': 'phosphate',
    po4: 'phosphate',
    'silica (as sio2)': 'silica',
    sio2: 'silica',
    tss: 'total suspended solids',
    'suspended solids': 'total suspended solids',
    co3: 'carbonate',
    hco3: 'bicarbonate',
  };

  /* "Iron (Fe)", "Turbidity (NTU)", "Conductivity (EC)": a trailing bracket
   * that is a symbol or a unit, not a basis ("(as NO3)") */
  var TRAILING_QUALIFIER_RE = /\s*\((?!\s*as\s)[^)]*\)\s*$/;

  /* a trailing bracket after a name, and what it holds */
  var TRAILING_BRACKET_RE = /^(.+?)\s*\(([^()]*)\)$/;
  /* Nitrogen named as the basis anywhere in that bracket: "Nitrate (NO3-N)",
   * "(N)", "(NO3 as N)", "(as NO3-N)", "(nitrogen)", and a unit with its
   * basis, "(mg/L as N)", "(mg N/L)" or "(mgN/L)". A bracket that held
   * anything but an ion and N was stripped like a symbol, so "Nitrate (mg/L
   * as N)" was held to the 50 mg/L guideline for nitrate as the ion, where 20
   * mg/L as N is 88.5 mg/L as nitrate (standards.py _NITROGEN_NAMED_RE). */
  var NITROGEN_NAMED_RE = /\b(?:(?:no3|no2|nh4|nh3)\s*-{0,2}\s*)?(?:n|nitrogen)\b|[muµμ]gn\//;
  /* an ion's formula in that bracket, which must be the name's own */
  var NITROGEN_ION_RE = /\b(no3|no2|nh4|nh3)/g;
  /* an en dash, an em dash and the minus sign, which a name or a unit writes
   * for a hyphen */
  var DASHES_RE = /[\u2013\u2014\u2212]/g;
  /* the table key each name takes when it is reported as nitrogen, and the
   * ion a qualifier may name for it; "Nitrite (NO3-N)" contradicts itself
   * and is left to resolve to nothing */
  /** @type {Record<string, [string, string[]]>} */
  var AS_NITROGEN_KEYS = {
    nitrate: ['nitrate (as n)', ['no3']],
    nitrite: ['nitrite (as n)', ['no2']],
    ammonia: ['ammonia (as n)', ['nh3', 'nh4']],
    ammonium: ['ammonia (as n)', ['nh3', 'nh4']],
  };

  /** The standards-table key a certificate's parameter name refers to. The
   * assessment is fail-closed - an unknown name makes the whole sample "not
   * proven safe" - so name resolution is load-bearing.
   * @param {*} name
   * @returns {string}
   */
  function normaliseParameter(name) {
    var key = String(name || '').trim().toLowerCase().replace(/\s+/g, ' ')
      .replace(DASHES_RE, '-');
    if (own(PARAMETER_ALIASES, key)) return PARAMETER_ALIASES[key];
    var bracket = TRAILING_BRACKET_RE.exec(key);
    if (bracket && own(AS_NITROGEN_KEYS, bracket[1]) && NITROGEN_NAMED_RE.test(bracket[2])) {
      /* reported as nitrogen: the table's entry for nitrogen, unless the
       * bracket names another ion's ("Nitrite (NO3-N)"), which contradicts
       * the name and is left to resolve to nothing */
      var asN = AS_NITROGEN_KEYS[bracket[1]];
      var named = bracket[2].match(NITROGEN_ION_RE) || [];
      return named.every(function (ion) { return asN[1].indexOf(ion) >= 0; }) ? asN[0] : key;
    }
    var stripped = key.replace(TRAILING_QUALIFIER_RE, '');
    if (stripped !== key) {
      return own(PARAMETER_ALIASES, stripped) ? PARAMETER_ALIASES[stripped] : stripped;
    }
    return key;
  }

  /* Faecal-oral pathogens a laboratory may name on a certificate: the
   * bacteria, viruses and protozoa the faecal indicator E. coli stands for
   * (quality/standards.py _FAECAL_PATHOGEN_RE). WHO sets no guideline value
   * for any of them, because drinking water must carry none and the
   * indicator is the routine check. They are recognised by name, not by
   * unit: a count in CFU is as likely to be a heterotrophic plate count,
   * which has no health significance. */
  var FAECAL_PATHOGEN_RE = new RegExp('\\b(' + [
    'salmonella', 's\\.? ?typhi', 'typhoid', 'shigella', 'vibrio cholerae',
    'v\\.? ?cholerae', 'cholera', 'campylobacter', 'yersinia', 'e\\.? ?coli o157',
    'cryptosporidium', 'giardia', 'entamoeba histolytica', 'cyclospora',
    'hepatitis [ae]\\b', 'rotavirus', 'norovirus', 'enterovirus', 'adenovirus',
    'astrovirus',
  ].join('|') + ')');

  /** The faecal pathogen a parameter name refers to, or ''.
   * @param {*} name
   * @returns {string}
   */
  function faecalPathogen(name) {
    var match = FAECAL_PATHOGEN_RE.exec(
      String(name === null || name === undefined ? '' : name).toLowerCase()
        .replace(/\s+/g, ' '));
    return match ? match[1] : '';
  }

  var _standardsCache = null;
  /**
   * @param {Rec[]|null} [rows] the bundled table when not given
   * @returns {Record<string, Rec>}
   */
  function loadStandards(rows) {
    var source = rows || (GWT.data && GWT.data.whoGuidelines);
    if (!source) return {};
    if (!rows && _standardsCache) return _standardsCache;
    /** @type {Record<string, Rec>} */
    var table = {};
    source.forEach(function (row) {
      var entry = {
        parameter: row.parameter,
        unit: row.unit || '',
        who_health: parseLimit(row.who_health_gv),
        who_aesthetic: parseLimit(row.who_aesthetic),
        sl_standard: parseLimit(row.sl_standard),
        /* where the national value came from: "provisional" means it has not
         * been checked against the Sierra Leone Standards Bureau
         * specification - a WHO figure carried across, or one adopted from
         * regional practice */
        sl_source: (row.sl_source || '').trim(),
        category: row.category || '',
        note: row.note || '',
      };
      entry.sl_provisional = !!entry.sl_standard && entry.sl_source === 'provisional';
      table[normaliseParameter(entry.parameter)] = entry;
    });
    if (!rows) _standardsCache = table;
    return table;
  }

  /* Said wherever a national verdict is shown, while any national value is
   * still provisional. A compliance failure against an unconfirmed limit is a
   * prompt to check the specification, not a finding to put to a regulator. */
  var PROVISIONAL_NATIONAL_NOTE = 'The national column in the standards table ' +
    'is provisional: its values are WHO guideline figures carried across, or ' +
    'limits adopted from regional practice, and have not been confirmed ' +
    'against the Sierra Leone Standards Bureau drinking water specification. ' +
    'Confirm the figures before treating a national exceedance as a ' +
    'compliance finding.';

  /**
   * @param {Record<string, Rec>} [table]
   * @returns {string[]}
   */
  function provisionalNationalParameters(table) {
    var entries = table || loadStandards();
    return Object.keys(entries).map(function (key) { return entries[key]; })
      .filter(function (entry) { return entry.sl_provisional; })
      .map(function (entry) { return entry.parameter; })
      .sort();
  }

  /* --- ionic balance -------------------------------------------------------
   * 100 x (sum cations - sum anions) / (sum cations + sum anions) in meq/L.
   * Within 5% is normal laboratory practice, 5-10% is flagged for review, and
   * more than 10% means an unreliable analysis or a missing major ion.
   */

  /* Molar masses, g/mol, to three decimals: the figures the ionic balance and
   * the hazard index already used, and calcium carbonate's 100.087, on which
   * the corrosivity indices' 2.497 from calcium to CaCO3 rests (standards.py
   * MOLAR_MASS). */
  var MOLAR_MASS = {
    N: 14.007, NO3: 62.004, NO2: 46.005, Ca: 40.078, Mg: 24.305,
    CaCO3: 100.087, HCO3: 61.017, CO3: 60.009,
  };
  /* The basis an entry's values are written on, where its name does not say:
   * calcium is reported as the element, so "mg/L as Ca" is its own scale. */
  /** @type {Record<string, string>} */
  var NATIVE_BASIS = { calcium: 'ca', magnesium: 'mg', bicarbonate: 'hco3',
    carbonate: 'co3' };
  /* What puts a value stated on one chemical basis onto the basis its entry
   * is written on, and that basis as a remark names it: a ratio of molar
   * masses, so a conversion rather than an assumption (standards.py
   * _BASIS_FACTORS). Calcium and magnesium as CaCO3 used to be taken at face
   * value, 2.5 and 4.1 times the element, and a balanced analysis was
   * flagged as an unreliable one. Nothing is put onto the entries for
   * nitrogen: every name that reaches one states nitrogen, so a unit as the
   * ion contradicts it and is refused. */
  /** @type {Record<string, [number, string]>} */
  var BASIS_FACTORS = {
    'nitrate (as no3)|n': [MOLAR_MASS.NO3 / MOLAR_MASS.N, 'NO3'],
    'nitrite (as no2)|n': [MOLAR_MASS.NO2 / MOLAR_MASS.N, 'NO2'],
    'calcium|caco3': [MOLAR_MASS.Ca / MOLAR_MASS.CaCO3, 'Ca'],
    'magnesium|caco3': [MOLAR_MASS.Mg / MOLAR_MASS.CaCO3, 'Mg'],
    'bicarbonate|caco3': [2 * MOLAR_MASS.HCO3 / MOLAR_MASS.CaCO3, 'HCO3'],
    'carbonate|caco3': [MOLAR_MASS.CO3 / MOLAR_MASS.CaCO3, 'CO3'],
  };
  /* The entries a value reported as nitrogen is graded on, and the ion's
   * entry, factor and formula that put it on the ion's scale. The row is
   * graded against the as-N guideline; the charge balance, the hazard index
   * and the water quality index are written for the ion, and read it there
   * (standards.py AS_NITROGEN). */
  /** @type {Record<string, [string, number, string]>} */
  var AS_NITROGEN = {
    'nitrate (as n)': ['nitrate (as no3)', MOLAR_MASS.NO3 / MOLAR_MASS.N, 'NO3'],
    'nitrite (as n)': ['nitrite (as no2)', MOLAR_MASS.NO2 / MOLAR_MASS.N, 'NO2'],
  };

  /* the key the indices read a result under: the ion's, for nitrogen */
  function indexKey(key) {
    return own(AS_NITROGEN, key) ? AS_NITROGEN[key][0] : key;
  }

  /** [factor, basis]: what puts the unit's basis on the entry's, for the
   * remark and the flag of a row toGuidelineUnit converted; null where no
   * factor is known (standards.py basis_conversion).
   * @param {*} reportedUnit
   * @param {Rec} entry a standards-table entry
   * @returns {[number, string]|null}
   */
  function basisConversion(reportedUnit, entry) {
    var source = parseUnit(String(reportedUnit || ''));
    if (!source || !source.basis) return null;
    var key = normaliseParameter(entry.parameter) + '|' + source.basis;
    return own(BASIS_FACTORS, key) ? BASIS_FACTORS[key] : null;
  }

  var CATION_MEQ = {
    calcium: 2 / 40.078,
    magnesium: 2 / 24.305,
    sodium: 1 / 22.990,
    potassium: 1 / 39.098,
    iron: 2 / 55.845,
    manganese: 2 / 54.938,
  };
  var ANION_MEQ = {
    chloride: 1 / 35.453,
    sulfate: 2 / 96.06,
    bicarbonate: 1 / 61.017,
    carbonate: 2 / 60.009,
    'nitrate (as no3)': 1 / 62.004,
    fluoride: 1 / 18.998,
  };
  var REQUIRED_CATIONS = ['calcium', 'magnesium', 'sodium'];
  /* sulfate is one of the three major anions: without it the balance came
   * out 15% short and was reported as an unreliable analysis */
  var REQUIRED_ANIONS = ['chloride', 'bicarbonate', 'sulfate'];

  /* A result below the detection limit counts as zero; a result with no value
   * at all counts as not measured. */
  /** Every measured result on the standards table's scale, keyed by
   * normalised parameter name. groundwater/quality/standards.py
   * canonical_values(). A result whose unit cannot be reconciled with its
   * guideline is LEFT OUT rather than passed through raw: the aggregate
   * indices built on these numbers - the quality index, the hazard index,
   * the ionic balance, the corrosivity indices - all assume mg/L, and a
   * sample reported in ug/L quietly produced a hazard index a thousand
   * times too high and an "unsuitable for drinking" rating for clean water.
   * @param {QualitySample} sample
   * @param {Rec[]|null} [standardsRows]
   * @returns {Record<string, number>}
   */
  function canonicalValues(sample, standardsRows) {
    var table = loadStandards(standardsRows);
    /** @type {Record<string, number>} */
    var values = {};
    /** @type {Record<string, number>} */
    var asNitrogen = {};
    (sample.results || []).forEach(function (result) {
      if (result.value === null || result.value === undefined) return;
      var key = normaliseParameter(result.parameter);
      var entry = table[key];
      if (!entry) {
        /* No guideline entry, so no declared scale to convert onto, and
         * nothing downstream has a limit for it either. */
        values[key] = Number(result.value);
        return;
      }
      var converted = toGuidelineUnit(Number(result.value), result.unit, entry,
        result.parameter);
      if (converted.value === null) return;
      if (own(AS_NITROGEN, key)) {
        /* Nitrate and nitrite reported as nitrogen go on the ion's scale,
         * under the ion's key: the meq factor, the reference dose and the
         * water quality index's exclusion are written for the ion. */
        asNitrogen[AS_NITROGEN[key][0]] = converted.value * AS_NITROGEN[key][1];
        return;
      }
      values[key] = converted.value;
    });
    /* a certificate that reports both forms is not counted twice */
    Object.keys(asNitrogen).forEach(function (ion) {
      if (!own(values, ion)) values[ion] = asNitrogen[ion];
    });
    return values;
  }

  /**
   * @param {QualitySample} sample
   * @param {string} key
   * @returns {number|null}
   */
  function sampleValue(sample, key) {
    var canonical = canonicalValues(sample);
    if (Object.prototype.hasOwnProperty.call(canonical, key)) return canonical[key];
    var results = sample.results || [];
    for (var i = 0; i < results.length; i++) {
      if (indexKey(normaliseParameter(results[i].parameter)) === key) {
        if (results[i].value !== null && results[i].value !== undefined) {
          /* present but not convertible: refuse it rather than use the raw
           * number on an unknown scale */
          return null;
        }
        return results[i].below_detection ? 0.0 : null;
      }
    }
    return null;
  }

  /* What the balance needs, in the order a certificate lists them. */
  var ION_LABELS = {
    calcium: 'calcium', magnesium: 'magnesium', sodium: 'sodium',
    potassium: 'potassium', chloride: 'chloride', sulfate: 'sulfate',
    bicarbonate: 'bicarbonate (or alkalinity)',
  };

  /* The major ions the balance needs and the analysis does not carry.
   *
   * The balance is the one check that says whether a certificate's own
   * numbers hang together, and it was skipped in silence whenever a major
   * ion was missing: the report simply had no charge-balance line, which
   * reads as "the analysis balanced" rather than "nobody could tell". */
  function ionicBalanceGap(sample) {
    var missing = [];
    REQUIRED_CATIONS.forEach(function (key) {
      if (sampleValue(sample, key) === null) {
        missing.push(ION_LABELS[key] || key);
      }
    });
    REQUIRED_ANIONS.forEach(function (key) {
      if (sampleValue(sample, key) !== null) return;
      if (key === 'bicarbonate' && sampleValue(sample, 'alkalinity') !== null) return;
      missing.push(ION_LABELS[key] || key);
    });
    return missing;
  }

  /** @param {QualitySample} sample */
  function ionicBalance(sample) {
    var cations = /** @type {Record<string, number>} */ ({}),
      anions = /** @type {Record<string, number>} */ ({});
    Object.keys(CATION_MEQ).forEach(function (key) {
      var v = sampleValue(sample, key);
      if (v !== null) cations[key] = v * CATION_MEQ[key];
    });
    var usedAlk = false;
    Object.keys(ANION_MEQ).forEach(function (key) {
      var v = sampleValue(sample, key);
      if (v !== null) anions[key] = v * ANION_MEQ[key];
    });
    if (!('bicarbonate' in anions)) {
      var alk = sampleValue(sample, 'alkalinity');
      if (alk !== null) {
        /* alkalinity as CaCO3 -> bicarbonate equivalent: meq = mg/L / 50.04 */
        anions.bicarbonate = alk / 50.04;
        usedAlk = true;
      }
    }
    var haveCat = REQUIRED_CATIONS.every(function (k) { return k in cations; });
    var haveAn = REQUIRED_ANIONS.every(function (k) { return k in anions; });
    if (!haveCat || !haveAn) return null;

    var totalCat = 0, totalAn = 0;
    Object.keys(cations).forEach(function (k) { totalCat += cations[k]; });
    Object.keys(anions).forEach(function (k) { totalAn += anions[k]; });
    if (totalCat + totalAn <= 0) return null;
    var error = 100.0 * (totalCat - totalAn) / (totalCat + totalAn);

    var flag = null;
    var signed = (error >= 0 ? '+' : '') + pyFixed(error, 1);
    if (Math.abs(error) > 10) {
      flag = {
        level: 'error', code: 'ionic_balance',
        message: 'Charge balance error ' + signed + '% exceeds 10%; the ' +
          'analysis is unreliable or a major ion is missing.',
      };
    } else if (Math.abs(error) > 5) {
      flag = {
        level: 'warning', code: 'ionic_balance',
        message: 'Charge balance error ' + signed + '% is between 5% and 10%; ' +
          'review the laboratory analysis.',
      };
    }
    return {
      sum_cations_meq: totalCat, sum_anions_meq: totalAn, error_percent: error,
      cations_meq: cations, anions_meq: anions,
      used_alkalinity_for_bicarbonate: usedAlk, flag: flag,
    };
  }

  /* --- water quality index and health risk --------------------------------- */

  var INTAKE_L_PER_DAY = 2.0;
  var BODY_WEIGHT_KG = 70.0;

  /* oral reference doses, mg/kg/day (EPA IRIS / WHO) */
  var RFD = {
    arsenic: 3.0e-4, fluoride: 0.06, 'nitrate (as no3)': 1.6,
    'nitrite (as no2)': 0.1, manganese: 0.14, lead: 3.5e-3, cadmium: 5.0e-4,
    'chromium (total)': 3.0e-3, uranium: 3.0e-3, nickel: 0.02, copper: 0.04,
    zinc: 0.3, barium: 0.2, selenium: 5.0e-3, antimony: 4.0e-4,
  };
  var CANCER_SLOPE = { arsenic: 1.5 };

  /* The IRIS reference doses for nitrate and nitrite are expressed as
   * nitrogen, but the toolkit records the whole ion. Convert before dividing,
   * else the hazard quotient is overstated by the mass ratio. */
  /* A result reported as nitrogen reaches here on the ion's scale, under the
   * ion's key (canonicalValues), so it is scored once and on the same
   * footing, and is kept out of the quality index as the ion is. */
  var AS_NITROGEN_FACTOR = {
    'nitrate (as no3)': MOLAR_MASS.NO3 / MOLAR_MASS.N,
    'nitrite (as no2)': MOLAR_MASS.NO2 / MOLAR_MASS.N,
  };

  /* The reference doses and index weights below are all mg/L figures, so
   * the values have to be on that scale before they are used. */
  function measuredValues(sample, standardsRows) {
    return canonicalValues(sample, standardsRows);
  }

  function wqiRating(value) {
    if (value <= 50) return 'Excellent';
    if (value <= 100) return 'Good';
    if (value <= 200) return 'Poor';
    if (value <= 300) return 'Very poor';
    return 'Unsuitable for drinking';
  }

  /**
   * @param {QualitySample} sample
   * @param {Rec[]|null} [standardsRows]
   */
  function computeWqi(sample, standardsRows) {
    var table = loadStandards(standardsRows);
    var values = measuredValues(sample, standardsRows);
    var weightSum = 0, weightedQ = 0, contributors = [], n = 0;
    Object.keys(values).forEach(function (key) {
      var entry = table[key];
      if (!entry || entry.category === 'microbiological') return;
      /* Health-based trace toxicants have tiny standards, so 1/s weighting and
       * the value/s sub-index let a single one dominate and drown out the
       * general chemistry this index summarises. They are reported through the
       * separate Hazard Index instead. */
      if (key in RFD) return;
      var limit = entry.who_health || entry.who_aesthetic || entry.sl_standard;
      if (!limit || !limit.maximum || limit.maximum <= 0) return;
      var si = limit.maximum, qi;
      if (key === 'ph') {
        var denom = si - 7.0;
        qi = denom ? 100.0 * Math.abs(values[key] - 7.0) / denom : 0.0;
      } else {
        qi = 100.0 * values[key] / si;
      }
      var wi = 1.0 / si;
      weightSum += wi;
      weightedQ += wi * qi;
      contributors.push([entry.parameter, wi * qi]);
      n += 1;
    });
    if (n < 3 || weightSum <= 0) return null;
    var wqi = weightedQ / weightSum;
    contributors.sort(function (a, b) { return b[1] - a[1]; });
    return {
      value: pyRound(wqi, 1),
      rating: wqiRating(wqi),
      n_parameters: n,
      top_contributors: contributors.slice(0, 3).map(function (kv) {
        return [kv[0], pyRound(kv[1] / weightSum, 1)];
      }),
    };
  }

  /** @param {QualitySample} sample */
  function assessHealthRisk(sample) {
    var values = measuredValues(sample);
    var hq = {}, intakeFactor = INTAKE_L_PER_DAY / BODY_WEIGHT_KG;
    Object.keys(RFD).forEach(function (key) {
      if (!(key in values) || RFD[key] <= 0) return;
      var conc = values[key];
      var factor = AS_NITROGEN_FACTOR[key];
      if (factor) conc = conc / factor;
      hq[key] = (conc * intakeFactor) / RFD[key];
    });
    var keys = Object.keys(hq);
    if (!keys.length) return null;
    var hazardIndex = keys.reduce(function (a, k) { return a + hq[k]; }, 0);
    var cancerRisk = null;
    if ('arsenic' in values) {
      cancerRisk = values.arsenic * intakeFactor * CANCER_SLOPE.arsenic;
    }
    var flags = [];
    if (hazardIndex >= 1.0) {
      var worst = keys.reduce(function (a, b) { return hq[a] >= hq[b] ? a : b; });
      flags.push({
        level: 'warning', code: 'hazard_index',
        message: 'Non-carcinogenic Hazard Index ' + pyFixed(hazardIndex, 1) +
          ' is at or above 1 (dominated by ' + worst + '); chronic ingestion ' +
          'poses a potential health concern.',
      });
    }
    if (cancerRisk !== null && cancerRisk > 1e-4) {
      flags.push({
        level: 'warning', code: 'cancer_risk',
        message: 'Estimated lifetime arsenic cancer risk ' + expo(cancerRisk, 1) +
          ' exceeds the 1e-4 screening level.',
      });
    }
    var rating = hazardIndex < 1.0 ? 'Acceptable (Hazard Index below 1)'
      : (hazardIndex < 4.0 ? 'Elevated (Hazard Index at or above 1)'
                           : 'High (Hazard Index at or above 4)');
    var sortedHq = {};
    keys.sort(function (a, b) { return hq[b] - hq[a]; }).forEach(function (k) {
      sortedHq[k] = pyRound(hq[k], 2);
    });
    return {
      hazard_index: pyRound(hazardIndex, 2), hazard_quotients: sortedHq,
      cancer_risk: cancerRisk, rating: rating, flags: flags,
    };
  }

  /* --- corrosivity ---------------------------------------------------------
   * Soft, low-alkalinity, low-pH water from crystalline basement aquifers is
   * chemically aggressive and corrodes galvanised iron and mild-steel rising
   * mains, a leading cause of premature handpump failure across West Africa.
   * The water can be aggressive even with the pH inside 6.5-8.5, so a pH check
   * alone is not enough.
   */

  var LS_MEQ = {
    chloride: 1 / 35.453, sulfate: 2 / 96.06,
    bicarbonate: 1 / 61.017, carbonate: 2 / 60.009,
  };

  /**
   * @param {number} rsi
   * @returns {[string, boolean]}
   */
  function classifyRsi(rsi) {
    if (rsi < 6.0) return ['Scale-forming', false];
    if (rsi <= 7.0) return ['Balanced (near CaCO3 equilibrium)', false];
    if (rsi <= 8.0) return ['Corrosive', true];
    return ['Strongly corrosive', true];
  }

  /* The pH to one decimal, or to as many as the range sentence needs
   * (corrosivity.py _ph_text). Rounded to one decimal, 6.46 printed as "6.5
   * is below the 6.5 to 8.5 acceptability range" and 8.54 as "8.5 is above"
   * it. pyFixed, not toFixed: Python's "%.1f" sends a tie to the even digit,
   * so a pH reported as 6.25 prints as 6.2 in both engines. */
  function phText(ph) {
    for (var places = 1; places <= 4; places++) {
      var text = pyFixed(ph, places);
      var shown = Number(text);
      if ((shown !== 6.5 && shown !== 8.5) || (ph >= 6.5 && ph <= 8.5)) return text;
    }
    return formatG(ph);
  }

  /** @param {QualitySample} sample */
  function assessCorrosivity(sample) {
    /** @type {Rec} */
    var assessment = {
      lsi: null, rsi: null, aggressive_index: null, larson_skold: null,
      classification: 'Insufficient data', is_aggressive: false,
      verdict: '', materials_note: '', assumptions: [], flags: [],
    };
    var assumptions = assessment.assumptions;

    var ph = sampleValue(sample, 'ph');
    var calcium = sampleValue(sample, 'calcium');
    var alkalinity = sampleValue(sample, 'alkalinity');
    var tds = sampleValue(sample, 'tds');
    var ec = sampleValue(sample, 'electrical conductivity');
    var temp = sampleValue(sample, 'temperature');

    if (tds === null || tds <= 0) {
      if (ec && ec > 0) {
        tds = 0.64 * ec;
        assumptions.push('TDS estimated as 0.64 x EC = ' + pyFixed(tds, 0) +
          ' mg/L (TDS not reported).');
      } else {
        tds = 250.0;
        assumptions.push('TDS assumed 250 mg/L (neither TDS nor EC reported).');
      }
    }
    if (temp === null || temp <= 0) {
      /* "not reported" was said of a temperature written as "27 oC", which
       * was reported in a unit that could not be read */
      var unread = temp === null && (sample.results || []).some(function (r) {
        return normaliseParameter(r.parameter) === 'temperature' &&
          r.value !== null && r.value !== undefined;
      });
      temp = 25.0;
      assumptions.push(phrase(unread ? 'quality.temperature_unreadable'
        : 'quality.temperature_not_reported'));
    }

    if (ph === null || calcium === null || alkalinity === null ||
        calcium <= 0 || alkalinity <= 0) {
      assessment.verdict = 'Corrosivity could not be assessed: pH, calcium and ' +
        'alkalinity are all required. Supply them to obtain a materials ' +
        'recommendation.';
      return assessment;
    }

    /* calcium hardness as CaCO3 (Ca mg/L x 100.09/40.08) */
    var caHardness = calcium * 2.497;
    var log10 = function (v) { return Math.log(v) / Math.LN10; };

    /* Langelier: pHs = (9.3 + A + B) - (C + D) */
    var a = (log10(tds) - 1.0) / 10.0;
    var b = -13.12 * log10(temp + 273.15) + 34.55;
    var c = log10(caHardness) - 0.4;
    var d = log10(alkalinity);
    var phS = (9.3 + a + b) - (c + d);
    var lsi = ph - phS;
    var rsi = 2 * phS - ph;
    var ai = ph + log10(alkalinity * caHardness);

    assessment.lsi = pyRound(lsi, 2);
    assessment.rsi = pyRound(rsi, 2);
    assessment.aggressive_index = pyRound(ai, 2);

    /* Larson-Skold (optional): (Cl + SO4) / (HCO3 + CO3) in meq/L */
    var chloride = sampleValue(sample, 'chloride');
    var sulfate = sampleValue(sample, 'sulfate');
    var bicarbonate = sampleValue(sample, 'bicarbonate');
    var carbonate = sampleValue(sample, 'carbonate');
    var hco3Meq = bicarbonate === null
      ? alkalinity / 50.04
      : bicarbonate * LS_MEQ.bicarbonate;
    var co3Meq = (carbonate || 0.0) * LS_MEQ.carbonate;
    if (chloride !== null && sulfate !== null && (hco3Meq + co3Meq) > 0) {
      assessment.larson_skold = pyRound(
        (chloride * LS_MEQ.chloride + sulfate * LS_MEQ.sulfate) / (hco3Meq + co3Meq), 2);
    }

    var classified = classifyRsi(rsi);
    var classification = classified[0], aggressive = classified[1];
    if (lsi < -0.5) aggressive = true;
    if (assessment.aggressive_index !== null && assessment.aggressive_index < 10) {
      aggressive = true;
    }
    /* Keep the class label consistent with the flag and verdict: when the
     * LSI/AI corroboration promotes borderline water to aggressive, the RSI
     * class must not still read "Balanced" beside an "aggressive" verdict. */
    if (aggressive && ['Corrosive', 'Strongly corrosive'].indexOf(classification) < 0) {
      classification = 'Corrosive';
    }
    assessment.classification = classification;
    assessment.is_aggressive = aggressive;

    var signedLsi = (lsi >= 0 ? '+' : '') + pyFixed(lsi, 1);
    if (aggressive) {
      /* The pH sentence used to say "within the acceptability range" for a
       * sample the same report flagged at 5.9. It now says what the pH is. */
      var phNote;
      if (ph < 6.5) {
        phNote = 'The pH of ' + phText(ph) + ' is below the 6.5 to 8.5 ' +
          'acceptability range, which adds to the attack on metal; soft, ' +
          'low-alkalinity basement groundwater is aggressive even at a pH ' +
          'inside that range.';
      } else if (ph > 8.5) {
        phNote = 'The pH of ' + phText(ph) + ' is above the 6.5 to 8.5 ' +
          'acceptability range; the aggressiveness comes from the low calcium ' +
          'and alkalinity.';
      } else {
        phNote = 'The pH of ' + phText(ph) + ' is within the 6.5 to 8.5 ' +
          'acceptability range, and the water is aggressive all the same, ' +
          'which is typical of soft basement groundwater.';
      }
      assessment.verdict = 'The water is chemically aggressive (Ryznar index ' +
        pyFixed(rsi, 1) + ', Langelier index ' + signedLsi + '). It will corrode ' +
        'metal fittings. ' + phNote;
      assessment.materials_note = 'Specify uPVC or stainless steel (grade 304 or ' +
        '316) for the rising main and pump components, and avoid galvanised iron ' +
        'and mild steel, which corrode rapidly in this water and are a leading ' +
        'cause of premature pump failure. Inspect the rising main and the wetted ' +
        'metal parts of the pump for corrosion at each service.';
      if (assessment.larson_skold !== null && assessment.larson_skold > 0.8) {
        assessment.materials_note += ' The Larson-Skold ratio (' +
          pyFixed(assessment.larson_skold, 1) + ') is elevated, so chloride and ' +
          'sulfate add to the attack on steel.';
      }
      assessment.flags.push({
        level: 'warning', code: 'aggressive_water',
        message: 'Water is chemically aggressive; specify uPVC or stainless ' +
          'rising main and pump components.',
      });
    } else if (classification === 'Scale-forming') {
      assessment.verdict = 'The water tends to deposit calcium carbonate scale ' +
        '(Ryznar index ' + pyFixed(rsi, 1) + ', Langelier index ' + signedLsi + ').';
      assessment.materials_note = 'Monitor the screen and pump for encrustation ' +
        'and de-scale as needed; corrosion of metal parts is a lesser concern.';
    } else {
      assessment.verdict = 'The water is close to calcium carbonate equilibrium ' +
        '(Ryznar index ' + pyFixed(rsi, 1) + ', Langelier index ' + signedLsi +
        '); neither strong corrosion nor scaling is expected.';
      assessment.materials_note = 'Standard materials are acceptable; inspect ' +
        'fittings for corrosion during routine maintenance.';
    }
    return assessment;
  }

  /* --- full sample assessment ----------------------------------------------
   * groundwater/quality/assess.py. Fail-closed: a drinking water verdict is
   * something a village acts on, so "suitable" is said only when the work
   * can be shown. Values are converted onto the guideline's own unit before
   * comparison, a "below detection" result proves compliance only when the
   * detection limit is under the limit, an unrecognised determinand is an
   * open question rather than a clean bill, and a sample with nothing
   * evaluable in it is indeterminate. Silence is not a pass.
   */

  var STATUS_ORDER = ['exceeds_health', 'exceeds_national', 'exceeds_aesthetic',
    'indeterminate', 'within_limits', 'below_detection', 'no_guideline',
    'not_measured'];

  var WQ_STATUS_LABELS = {
    within_limits: 'Complies',
    exceeds_health: 'EXCEEDS HEALTH GUIDELINE',
    exceeds_national: 'Exceeds national/adopted limit',
    exceeds_aesthetic: 'Exceeds acceptability value',
    indeterminate: 'NOT EVALUABLE',
    below_detection: 'Below detection',
    no_guideline: 'No guideline value',
    not_measured: 'Not measured',
  };

  /* Worst first. indeterminate sits above aesthetic because "usable for
   * drinking" is a claim and an open question defeats a claim; it sits below
   * the two failures because a demonstrated exceedance is a finding, and
   * uncertainty elsewhere does not soften it. */
  var VERDICT_ORDER = ['health_fail', 'national_fail', 'indeterminate',
    'aesthetic', 'pass'];

  var VERDICT_SHORT = {
    health_fail: 'Treat before use',
    national_fail: 'Fails national limit',
    indeterminate: 'Not proven safe',
    aesthetic: 'Aesthetic only',
    pass: 'Safe',
  };
  var VERDICT_LONG = {
    health_fail: 'Treat before use',
    national_fail: 'Fails the national standard',
    indeterminate: 'Not proven safe - incomplete or unevaluable results',
    aesthetic: 'Aesthetic issues only',
    pass: 'Safe to drink',
  };
  var VERDICT_TONE = {
    health_fail: 'bad', national_fail: 'bad', indeterminate: 'info',
    aesthetic: 'warn', pass: 'ok',
  };

  /* The health panel a "suitable for drinking" verdict requires. E. coli is
   * the direct indicator of faecal contamination; arsenic and fluoride are
   * the geogenic risks that make otherwise clear, pleasant groundwater unsafe
   * over years; nitrate is the latrine and agricultural one. */
  var ESSENTIAL_HEALTH_PARAMETERS = ['e. coli', 'arsenic', 'fluoride',
    'nitrate (as no3)'];

  var INDETERMINATE_REASONS = {
    unit_unreadable: 'the reported unit could not be read',
    unit_mismatch: 'the reported unit measures something other than the guideline',
    detection_limit_above_guideline:
      'the detection limit is above the limit being checked',
    detection_limit_unknown: 'the detection limit was not reported',
    unknown_parameter: 'the parameter is not in the standards table',
    unit_basis_conflict:
      'the unit names a different chemical basis from the parameter',
    value_unreadable: 'the reported result could not be read',
    detected_not_quantified:
      'the laboratory reported only a lower bound, which is inside the limit',
  };

  var GRADED_STATUSES = ['exceeds_health', 'exceeds_national',
    'exceeds_aesthetic', 'within_limits', 'below_detection'];

  function isGraded(row) {
    return row.evaluable && GRADED_STATUSES.indexOf(row.status) >= 0;
  }

  /* "(as NO3)", and a unit with its basis, "(mg/L as NO3)" */
  var PARAMETER_BASIS_RE = /\((?:[^()]*\s)?as\s+([^()]+?)\s*\)/;

  /* "Nitrate (as NO3)" -> "no3"; "as NO3-N" is nitrogen, as a unit's basis is */
  function parameterBasis(parameter) {
    var m = PARAMETER_BASIS_RE.exec(String(parameter || '').toLowerCase()
      .replace(DASHES_RE, '-'));
    if (!m) return '';
    var basis = m[1].replace(/ /g, '');
    return NITROGEN_BASIS_RE.test(basis) ? 'n' : basis;
  }

  /* The basis a laboratory's name for a determinand states: what a bracket
   * states after "as", or nitrogen for a name that resolves to an entry for
   * nitrogen ("Nitrate-N", "Nitrate (NO3-N)", "Nitrate (mg N/L)"). Read from
   * "as" alone, "Nitrate-N" stated no basis, so in "mg/L as NO3" it was
   * converted onto nitrogen and passed (standards.py _written_basis). */
  function writtenBasis(parameter) {
    return parameterBasis(parameter) ||
      (own(AS_NITROGEN, normaliseParameter(parameter)) ? 'n' : '');
  }

  /* The ions whose nitrogen each entry may be reported as: "Nitrite" in
   * "mg/L as NO3-N" names one determinand and another's nitrogen
   * (standards.py _NITROGEN_IONS). */
  /** @type {Record<string, string[]>} */
  var NITROGEN_IONS = {
    'nitrate (as no3)': ['no3'], 'nitrate (as n)': ['no3'],
    'nitrite (as no2)': ['no2'], 'nitrite (as n)': ['no2'],
    'ammonia (as n)': ['nh3', 'nh4'],
  };

  function limitMaximums(entry) {
    var out = [];
    [entry.who_health, entry.sl_standard, entry.who_aesthetic].forEach(
      function (limit) {
        if (limit && limit.maximum !== null && limit.maximum !== undefined) {
          out.push(limit.maximum);
        }
      });
    return out;
  }

  /* Put a reported value on the guideline's scale. Returns
   * {value, reason}; value null means the number must NOT be compared.
   * `parameter` is the name as the laboratory wrote it: a basis it states and
   * the unit contradicts is refused, whichever of them is the entry's own
   * ("Nitrate (as NO3)" in "mg/L as N", "Nitrate-N" in "mg/L as NO3",
   * "Calcium (mg/L as CaCO3)" in "mg/L as Ca"), as is a unit naming another
   * ion's nitrogen ("Nitrite" in "mg/L as NO3-N"), and "Nitrate" in "mg/L as
   * N" is converted; without it the entry's own name speaks for the sheet
   * (standards.py to_standard_unit). */
  function toGuidelineUnit(value, reportedUnit, entry, parameter) {
    var reported = String(reportedUnit || '').trim();
    var guideline = String(entry.unit || '').trim();

    /* "-", "n/a" and friends normalise away to nothing: they are how a sheet
     * writes "no unit here", so they take the no-unit path rather than the
     * unreadable one. */
    if (reported && !normaliseUnit(reported)) reported = '';

    if (!reported) return { value: Number(value), reason: 'unit_assumed' };
    if (!guideline) return { value: Number(value), reason: '' };
    if (normaliseUnit(reported) === normaliseUnit(guideline)) {
      /* Written the same way: same scale, whether or not this engine has
       * ever heard of the unit. Keeps a newly added guideline unit from
       * making every sample indeterminate. */
      return { value: Number(value), reason: '' };
    }

    var source = parseUnit(reported);
    var target = parseUnit(guideline);

    if (target && target.dimension === 'ph') {
      /* pH is the one absolute scale here with no rival, so a sheet carrying
       * "mg/L" beside a pH of 7.2 is a template artefact. */
      if (!source || source.dimension !== 'ph') {
        return { value: Number(value), reason: 'unit_assumed' };
      }
      return { value: Number(value), reason: '' };
    }

    if (!source || !target) return { value: null, reason: 'unit_unreadable' };
    if (!unitsComparable(source, target)) {
      return { value: null, reason: 'unit_mismatch' };
    }
    var converted = convertUnit(value, reported, guideline);
    if (converted === null) return { value: null, reason: 'unit_mismatch' };
    if (source.basis && !target.basis) {
      /* The unit names a chemical reference the guideline's unit does not.
       * The parameter name often carries it instead: "Nitrate (as NO3)"
       * reported in "mg/L as N" is a different number by a factor of 4.4,
       * and grading it at face value passed a sample the guideline fails. */
      var key = normaliseParameter(entry.parameter);
      var species = nitrogenSpecies(reported);
      if (species && own(NITROGEN_IONS, key) && NITROGEN_IONS[key].indexOf(species) < 0) {
        /* "Nitrite" in "mg/L as NO3-N": another ion's nitrogen */
        return { value: null, reason: 'unit_basis_conflict' };
      }
      var written = writtenBasis(parameter === undefined || parameter === null
        ? entry.parameter : parameter);
      if (written && written !== source.basis) {
        /* the name and the unit state different bases, whichever of them is
         * the entry's own: "Nitrate-N" in "mg/L as NO3", and "Calcium (mg/L
         * as CaCO3)" in "mg/L as Ca" */
        return { value: null, reason: 'unit_basis_conflict' };
      }
      var native = parameterBasis(entry.parameter) ||
        (own(NATIVE_BASIS, key) ? NATIVE_BASIS[key] : '');
      if (source.basis === native) return { value: converted, reason: '' };
      var factor = basisConversion(reported, entry);
      if (factor) return { value: converted * factor[0], reason: 'unit_basis_converted' };
      if (native) return { value: null, reason: 'unit_basis_conflict' };
      /* Nothing states the guideline's basis, so the reading is taken but it
       * is worth an analyst's eye: an 'as CaCO3' figure is about 2.5 times
       * the same concentration expressed as the element. */
      return { value: converted, reason: 'unit_basis_assumed' };
    } else if (target.basis && !source.basis) {
      return { value: converted, reason: 'unit_basis_assumed' };
    }
    return { value: converted, reason: '' };
  }

  /* The limit hierarchy: [status, key of the limit that set it]
   * (assess.py _classify). exceeds(limit) says whether a limit is crossed:
   * a measured value asks limitExceededBy, a lower bound whether it already
   * reaches the limit. One hierarchy serves both, so a ">1.0" iron is graded
   * as a measured iron is, rather than by rules of its own. */
  function classifyLimits(entry, exceeds) {
    var isMicro = String(entry.category || '').trim().toLowerCase() === 'microbiological';
    var isFaecal = String(entry.parameter || '').trim().toLowerCase() === 'e. coli';
    if (entry.who_health && exceeds(entry.who_health)) {
      return ['exceeds_health', 'who_health'];
    }
    if (isMicro && ((entry.sl_standard && exceeds(entry.sl_standard)) ||
        (entry.who_aesthetic && exceeds(entry.who_aesthetic)))) {
      /* A microbiological indicator is never an aesthetic matter, even when
       * its limit is carried in the national column. E. coli is the faecal
       * indicator and any detection is a health exceedance. Total coliforms
       * are not: WHO sets no health-based guideline for them and they
       * indicate ingress or an unprotected wellhead, not faecal
       * contamination, so they are a national-limit failure that calls for
       * disinfection and a sanitary inspection. Three reports used to call a
       * sample with E. coli 0 "faecal contamination" on total coliforms. */
      return [isFaecal ? 'exceeds_health' : 'exceeds_national', 'microbiological'];
    }
    if (entry.sl_standard && exceeds(entry.sl_standard)) {
      /* With a WHO health value the national limit is the stricter one, and
       * failing it is a compliance failure, not a matter of taste. Without
       * one the national limit is an acceptability limit (iron staining,
       * chloride taste, turbidity). */
      return [entry.who_health ? 'exceeds_national' : 'exceeds_aesthetic', 'sl_standard'];
    }
    if (entry.who_aesthetic && exceeds(entry.who_aesthetic)) {
      return ['exceeds_aesthetic', 'who_aesthetic'];
    }
    if (!(entry.who_health || entry.who_aesthetic || entry.sl_standard)) {
      return ['no_guideline', ''];
    }
    return ['within_limits', ''];
  }

  /* What a remark adds after a national acceptability limit. The WHO figure
   * is what the national one was carried across from, and naming it is the
   * only way a reader can tell a limit somebody set from a limit this
   * toolkit assumed. "Which is provisional" is said only of a value the
   * table in use marks provisional: a table whose national column names its
   * specification was told its confirmed limits were provisional. */
  function acceptabilityNote(entry) {
    var provisional = entry.sl_provisional ? ', which is provisional' : '';
    var whoNote = entry.who_aesthetic
      ? '; the WHO acceptability value is ' + limitText(entry.who_aesthetic)
      : '; WHO sets no value for this determinand';
    return provisional + whoNote;
  }

  function gradeRow(row, entry, value, unitNote) {
    var graded = classifyLimits(entry, function (limit) {
      return limitExceededBy(limit, value);
    });
    var status = graded[0], basis = graded[1];
    row.status = status;
    if (basis === 'who_health') {
      row.remark = 'exceeds the WHO health based guideline (' +
        limitText(entry.who_health) + ')' + unitNote;
    } else if (basis === 'microbiological') {
      var micro = entry.sl_standard || entry.who_aesthetic;
      if (status === 'exceeds_health') {
        row.remark = 'faecal indicator detected above the limit (' +
          limitText(micro) + '); a health concern, not aesthetic' + unitNote;
      } else {
        row.remark = 'detected above the national limit (' + limitText(micro) +
          '); an indicator of ingress or inadequate wellhead protection, not ' +
          'of faecal contamination in itself, and WHO sets no health based ' +
          'guideline for it' + unitNote;
      }
    } else if (basis === 'sl_standard' && status === 'exceeds_national') {
      row.remark = 'exceeds the national standard limit (' +
        limitText(entry.sl_standard) + '), which is stricter than the ' +
        'WHO health based guideline (' + limitText(entry.who_health) + ')' +
        unitNote;
    } else if (basis === 'sl_standard') {
      /* No WHO health value exists for this parameter, so the national limit
       * is an acceptability one, and a provisional one - a WHO or regional
       * figure carried across - is called provisional rather than reported
       * as a legal failure the toolkit cannot establish. */
      row.remark = 'exceeds the national acceptability limit (' +
        limitText(entry.sl_standard) + ')' + acceptabilityNote(entry) + unitNote;
    } else if (basis === 'who_aesthetic') {
      row.remark = 'exceeds the WHO acceptability value (' +
        limitText(entry.who_aesthetic) + ')' + unitNote;
    } else if (status === 'no_guideline') {
      row.remark = entry.note || 'no guideline value';
    } else {
      row.remark = unitNote.trim();
    }
  }

  /* A "< X" result proves compliance only when X is under the limit. */
  function assessBelowDetection(row, result, entry, limits) {
    var dlText = (result.detection_limit === null ||
      result.detection_limit === undefined) ? null : Number(result.detection_limit);
    if (!limits.length) {
      row.status = 'below_detection';
      row.remark = dlText === null ? 'below detection limit'
        : 'below detection limit (' + formatG(dlText) + ')';
      return row;
    }
    var strictest = Math.min.apply(null, limits);
    var microbiological = entry.category === 'microbiological';
    if (microbiological && dlText === null) {
      /* "Absent", "ND", "not detected": the count found nothing in the
       * sample, which for a guideline of "not detectable in any 100 mL
       * sample" is the guideline being met, not an unknown */
      row.status = 'below_detection';
      row.remark = 'reported not detected; the guideline is met provided the ' +
        'laboratory examined a 100 mL sample';
      return row;
    }
    if (dlText === null) {
      row.status = 'indeterminate';
      row.evaluable = false;
      row.reason = 'detection_limit_unknown';
      row.remark = 'reported below the detection limit, but the limit itself ' +
        'was not reported, so compliance with ' + formatG(strictest) + ' ' +
        entry.unit + ' cannot be shown. Ask the laboratory for the detection limit.';
      return row;
    }
    var converted = toGuidelineUnit(dlText, result.unit, entry, result.parameter);
    if (converted.value === null) {
      row.status = 'indeterminate';
      row.evaluable = false;
      row.reason = converted.reason;
      row.remark = 'reported below a detection limit of ' + formatG(dlText) +
        " '" + (result.unit || '') + "', which cannot be compared with the " +
        "guideline in '" + entry.unit + "': " +
        INDETERMINATE_REASONS[converted.reason] + '.';
      return row;
    }
    /* The limit as the remark gives it. One put on the guideline's basis
     * says so, as a measured value does: "0.1 mg/L as N" read "0.442664
     * mg/L" (assess.py _assess_below_detection). */
    row.basis_reason = basisReason(converted.reason);
    var shown = formatG(converted.value) + ' ' + entry.unit;
    if (converted.reason === 'unit_basis_converted') {
      shown = formatG(dlText) + ' ' + (result.unit || '') + ' = ' +
        formatG(converted.value) + ' ' + wqScale(result.unit, entry, converted.reason);
    }
    if (microbiological && converted.value <= 1.0) {
      /* a membrane-filtration count cannot resolve below one colony per
       * volume filtered, so "<1 CFU/100 mL" is exactly what "not detectable
       * in any 100 mL sample" looks like on a certificate */
      row.status = 'below_detection';
      row.remark = 'not detected in a 100 mL sample (reported as <' +
        formatG(converted.value) + ' ' + entry.unit + ')';
      return row;
    }
    /* "<0.1" nitrate as N says which basis the sheet used, as "0.1" does */
    var nitrogen = asNitrogenNote(entry, converted.value, converted.reason);
    if (converted.value > strictest) {
      row.status = 'indeterminate';
      row.evaluable = false;
      row.reason = 'detection_limit_above_guideline';
      row.remark = 'below a detection limit of ' + shown +
        (nitrogen ? ' (' + nitrogen + ')' : '') + ', which is above the limit of ' +
        formatG(strictest) + ' ' + entry.unit + '. The method cannot see the ' +
        'guideline value, so the result does not show compliance; re-test ' +
        'with a more sensitive method.';
      return row;
    }
    row.status = 'below_detection';
    row.remark = 'below detection limit (' + shown + '), which is at or under ' +
      'the limit of ' + formatG(strictest) + ' ' + entry.unit;
    return withNitrogenNote(row, entry, converted.value, converted.reason);
  }

  /* the reasons a unit keeps a value off the table's scale */
  var UNIT_REFUSALS = ['unit_unreadable', 'unit_mismatch', 'unit_basis_conflict'];

  function hasLimit(entry) {
    return !!(entry.who_health || entry.who_aesthetic || entry.sl_standard);
  }

  /* The guideline's unit as a remark names it, with the basis a conversion
   * put the value on: "mg/L as Ca" for calcium reported as CaCO3 (assess.py
   * _scale). */
  function wqScale(reportedUnit, entry, reason) {
    if (reason === 'unit_basis_converted') {
      var basis = basisConversion(reportedUnit, entry);
      if (basis) return entry.unit + ' as ' + basis[1];
    }
    return entry.unit;
  }

  /* What a nitrate or nitrite row reported as nitrogen adds to its remark
   * (assess.py _as_nitrogen_note): it is held to the guideline for nitrogen,
   * and the remark says which basis the sheet used and gives the ion's
   * figure. A value converted onto nitrogen from the ion says so in its unit
   * note instead. */
  function asNitrogenNote(entry, converted, reason) {
    var key = normaliseParameter(entry.parameter);
    if (!own(AS_NITROGEN, key) || reason === 'unit_basis_converted') return '';
    return phrase('quality.as_nitrogen', { value: converted, unit: entry.unit,
      ion_value: converted * AS_NITROGEN[key][1], ion: AS_NITROGEN[key][2] });
  }

  /* the reasons a unit's chemical basis gives (assess.py _BASIS_REASONS) */
  var BASIS_REASONS = ['unit_basis_converted', 'unit_basis_assumed'];

  /* the reason where it is one a unit's chemical basis gives, else '' */
  function basisReason(reason) {
    return BASIS_REASONS.indexOf(reason) >= 0 ? reason : '';
  }

  /* the row, its remark saying which basis the sheet used (assess.py
   * _with_nitrogen_note) */
  function withNitrogenNote(row, entry, converted, reason) {
    var nitrogen = asNitrogenNote(entry, converted, reason);
    if (nitrogen) row.remark = row.remark ? row.remark + '; ' + nitrogen : nitrogen;
    return row;
  }

  /* A determinand with no limit whose unit cannot be put on the table's
   * scale (assess.py _no_guideline_unit): its unit decides nothing, and a
   * temperature written as "27 oC" made the sample "not proven safe". */
  function noGuidelineUnit(row, entry, result, reason, stated) {
    row.status = 'no_guideline';
    row.reason = reason;
    var note = phrase('quality.no_guideline_unit', {
      note: entry.note || (stated ? 'No guideline value' : 'no guideline value'),
      unit: String(result.unit || ''), why: INDETERMINATE_REASONS[reason] });
    row.remark = stated ? stated + '. ' + note : note;
    return row;
  }

  /* How a remark says which unit a number was read in (assess.py _unit_note). */
  function wqUnitNote(reported, unit, converted, reason, guidelineUnit) {
    if (reason === 'unit_assumed') {
      return unit
        ? ' (read as ' + guidelineUnit + "; the reported unit was '" + unit + "')"
        : ' (read as ' + guidelineUnit + '; no unit was reported)';
    }
    if (converted !== reported) {
      return ' (' + formatG(reported) + ' ' + unit + ' = ' + formatG(converted) +
        ' ' + guidelineUnit + ')';
    }
    return '';
  }

  /* a lower bound as a remark words it */
  function statedBound(result) {
    var bound = Number(result.greater_than);
    if (bound === 0 && !result.greater_than_inclusive) {
      return 'detected, count not quantified';
    }
    return (result.greater_than_inclusive ? 'at least ' : 'more than ') + formatG(bound);
  }

  /* The reason on a row whose lower bound is over one limit and under a
   * stricter one: ">1.5" copper is over the 1 mg/L acceptability value, and
   * whether it is also over the 2 mg/L health guideline is not known. The
   * exceedance it demonstrates is its status; the one it cannot rule out
   * keeps the sample out of "suitable". */
  var STRICTER_LIMIT_UNRESOLVED = 'stricter_limit_unresolved';

  /* how a remark names the limit classifyLimits says decided a row */
  var LIMIT_NAMES = {
    who_health: 'the WHO health based guideline',
    microbiological: 'the national limit',
    sl_standard: 'the national standard limit',
    who_aesthetic: 'the WHO acceptability value',
  };

  function decidingLimit(entry, basis) {
    if (basis === 'microbiological') return entry.sl_standard || entry.who_aesthetic;
    return basis ? entry[basis] : null;
  }

  /* A result the laboratory saw and did not put a number to.
   *
   * "TNTC", "Present" and "Positive" are a count above zero; ">50" is more
   * than 50 and ">=50" at least 50. All of them used to read as "not
   * measured", so a sample with E. coli 0 and total coliforms TNTC was graded
   * Safe, and a ">50" count was graded as exactly 50 - inside the limit
   * whenever the limit is 50.
   *
   * The bound is put on the guideline's scale and then graded through the
   * same limit hierarchy as a measured value. It used to be compared as
   * written, so lead ">5 ug/L" (0.005 mg/L) was a health exceedance where a
   * measured 7 ug/L complied; and every limit it crossed got the coliform
   * wording, so iron ">1.0" was a national failure put down to ingress at the
   * wellhead where a measured 1.5 was an acceptability one. */
  function assessUnquantified(row, result, entry) {
    var reported = Number(result.greater_than);
    var stated = statedBound(result);
    var inclusive = !!result.greater_than_inclusive;
    var converted = toGuidelineUnit(reported, result.unit, entry, result.parameter);
    var microbiological = String(entry.category || '').trim().toLowerCase() ===
      'microbiological';
    if (converted.value === null && reported === 0 && !inclusive && microbiological) {
      /* "Present" or "TNTC" is a count above zero, and zero is zero on every
       * count scale, so the unit decides nothing. Refused on it, an E. coli
       * "Present" in a unit this engine could not read made the sample "not
       * proven safe" where "Absent" in the same unit passed. A number in
       * such a unit is still refused: grading only the bound is a choice
       * (QUESTIONS.md item 24). */
      stated += ' (' + phrase('quality.zero_any_unit', { unit: String(result.unit || ''),
        why: INDETERMINATE_REASONS[converted.reason] }) + ')';
      converted = { value: 0.0, reason: '' };
    } else if (converted.value === null) {
      if (!hasLimit(entry)) {
        return noGuidelineUnit(row, entry, result, converted.reason, stated);
      }
      row.status = 'indeterminate';
      row.evaluable = false;
      row.reason = converted.reason;
      row.remark = 'reported as ' + stated + " in '" + (result.unit || '') +
        "' but the guideline is in '" + entry.unit + "': " +
        INDETERMINATE_REASONS[converted.reason] + '. The value was not ' +
        'compared against any limit.';
      return row;
    } else {
      stated += wqUnitNote(reported, result.unit || '', converted.value,
        converted.reason, wqScale(result.unit, entry, converted.reason));
      row.basis_reason = basisReason(converted.reason);
    }
    /* ">20" nitrate as N says which basis the sheet used, as "20" does */
    return withNitrogenNote(gradeBound(row, entry,
      /** @type {number} */ (converted.value), inclusive, stated),
    entry, converted.value, converted.reason);
  }

  /* A lower bound on the guideline's scale, graded (assess.py _grade_bound). */
  function gradeBound(row, entry, bound, inclusive, stated) {

    /* The true value is above the bound, or at it for ">=", so a limit is
     * crossed only when the bound already reaches it: ">50" exceeds 50,
     * ">=50" may equal it. */
    function certainlyOver(limit) {
      if (limit.maximum === null || limit.maximum === undefined) return false;
      return bound > limit.maximum || (bound === limit.maximum && !inclusive);
    }

    var graded = classifyLimits(entry, certainlyOver);
    var status = graded[0], basis = graded[1];
    /* the status the true value would have if it were as large as it may be */
    var worst = classifyLimits(entry, function (limit) {
      return limit.maximum !== null && limit.maximum !== undefined;
    });
    row.status = status;
    row.evaluable = true;
    row.reason = 'detected_not_quantified';
    if (status === 'no_guideline') {
      row.remark = stated + '. ' + (entry.note || 'No guideline value');
      return row;
    }
    if (status === 'within_limits') {
      if (worst[0] === 'within_limits') {
        row.remark = stated;
        return row;
      }
      /* The bound is inside every limit, so the result is an open question
       * rather than a pass: the true value is somewhere above it. */
      row.status = 'indeterminate';
      row.evaluable = false;
      row.remark = stated + '; the laboratory did not quantify it, so it ' +
        'cannot be shown to meet the limit';
      return row;
    }

    var limit = limitText(decidingLimit(entry, basis));
    if (basis === 'who_health') {
      row.remark = stated + ', which is above the WHO health based guideline (' +
        limit + '); the laboratory did not quantify it';
    } else if (basis === 'microbiological' && status === 'exceeds_health') {
      row.remark = 'faecal indicator ' + stated + ', above the limit (' + limit +
        '); a health concern, not aesthetic';
    } else if (basis === 'microbiological') {
      row.remark = stated + ', above the national limit (' + limit + '); an ' +
        'indicator of ingress or inadequate wellhead protection, not of faecal ' +
        'contamination in itself, and WHO sets no health based guideline for it';
    } else if (basis === 'sl_standard' && status === 'exceeds_national') {
      row.remark = stated + ', above the national standard limit (' + limit +
        '), which is stricter than the WHO health based guideline (' +
        limitText(entry.who_health) + '); the laboratory did not quantify it';
    } else if (basis === 'sl_standard') {
      row.remark = stated + ', above the national acceptability limit (' + limit +
        ')' + acceptabilityNote(entry) + '; the laboratory did not quantify it';
    } else {
      row.remark = stated + ', above the WHO acceptability value (' + limit +
        '); the laboratory did not quantify it';
    }
    if (status !== worst[0]) {
      /* Over one limit and under a stricter one: the exceedance it shows
       * stands, and the one it cannot rule out keeps the sample open. */
      row.reason = STRICTER_LIMIT_UNRESOLVED;
      row.remark += '. Whether it also exceeds ' + LIMIT_NAMES[worst[1]] + ' (' +
        limitText(decidingLimit(entry, worst[1])) + ') is not known';
    }
    return row;
  }

  /* What a pathogen row says about the limit it is held to. */
  var PATHOGEN_NOTE = 'a faecal pathogen, which drinking water must carry none ' +
    'of. WHO sets no guideline value for it because the faecal indicator E. ' +
    'coli is the routine check';

  /* A faecal pathogen named on the certificate, graded by whether it was
   * found (assess.py _assess_pathogen). "Salmonella: Present" was an unknown
   * determinand: not evaluable, so it kept the sample from "suitable", but
   * not a failure either, so the verdict asked for units and detection
   * limits while the laboratory had reported Salmonella in the water.
   * Any count or lower bound is a detection and a health failure; nothing
   * found, or nothing at one organism per volume examined, is the
   * requirement met. A coarser detection limit cannot show absence. */
  function assessPathogen(row, result) {
    function found(stated) {
      row.status = 'exceeds_health';
      row.remark = stated + ': ' + PATHOGEN_NOTE + '; a health concern, whatever the count';
      return row;
    }
    if (result.value !== null && result.value !== undefined) {
      if (Number(result.value) > 0) return found('detected');
      row.status = 'within_limits';
      row.remark = 'none counted: ' + PATHOGEN_NOTE;
      return row;
    }
    if (result.greater_than !== null && result.greater_than !== undefined) {
      return found(statedBound(result));
    }
    var dl = result.detection_limit;
    if (dl !== null && dl !== undefined && Number(dl) > 1.0) {
      row.status = 'indeterminate';
      row.evaluable = false;
      row.reason = 'detection_limit_above_guideline';
      row.remark = 'reported below a detection limit of ' + formatG(Number(dl)) +
        (result.unit ? ' ' + result.unit : '') + ', which cannot show that it ' +
        'is absent: ' + PATHOGEN_NOTE + '. Ask the laboratory whether it was ' +
        'found in the volume examined.';
      return row;
    }
    row.status = 'below_detection';
    row.remark = 'not detected: ' + PATHOGEN_NOTE;
    return row;
  }

  function assessResult(result, entry) {
    var guidelineUnit = entry ? (entry.unit || '') : '';
    var missing = result.value === null || result.value === undefined;
    var unquantified = missing && result.greater_than !== null &&
      result.greater_than !== undefined;
    var unreadable = missing && !!result.unreadable;
    /** @type {Rec} */
    var row = {
      parameter: result.parameter,
      value: missing ? null : Number(result.value),
      unit: result.unit || guidelineUnit,
      below_detection: !!result.below_detection,
      who_health: entry && entry.who_health ? limitText(entry.who_health) : '',
      who_aesthetic: entry && entry.who_aesthetic ? limitText(entry.who_aesthetic) : '',
      sl_standard: entry && entry.sl_standard ? limitText(entry.sl_standard) : '',
      status: 'not_measured',
      remark: 'no value reported',
      guideline_unit: guidelineUnit,
      value_in_guideline_unit: null,
      detection_limit: (result.detection_limit === null ||
        result.detection_limit === undefined) ? null : Number(result.detection_limit),
      evaluable: true,
      reason: '',
      /* the lower bound of a result the laboratory did not quantify, in the
       * reported unit: a table printing only the value showed "TNTC" and
       * ">50" as a dash */
      greater_than: unquantified ? Number(result.greater_than) : null,
      greater_than_inclusive: unquantified && !!result.greater_than_inclusive,
      /* whether the national value was provisional in the table in use */
      sl_provisional: !!(entry && entry.sl_provisional),
      /* what the unit's chemical basis did to a value, a bound or a
       * detection limit: 'unit_basis_converted', 'unit_basis_assumed' or ''
       * (assess.py ParameterAssessment.basis_reason) */
      basis_reason: '',
    };

    if (missing && !result.below_detection && !unquantified && !unreadable) {
      return row;
    }

    var pathogen = !entry && !!faecalPathogen(result.parameter);
    if (!entry && !pathogen) {
      /* An unrecognised determinand is an open question, not a clean bill,
       * and a detection of one is no less of one: "Salmonella: Present" was
       * read as not measured and left the sample suitable for drinking. */
      row.status = 'no_guideline';
      row.reason = 'unknown_parameter';
      row.evaluable = false;
      row.remark = 'parameter not in the standards table, so it was not ' +
        'checked against any limit';
      if (unquantified) row.remark = statedBound(result) + '; ' + row.remark;
      return row;
    }

    if (unreadable) {
      row.status = 'indeterminate';
      row.evaluable = false;
      row.reason = 'value_unreadable';
      row.remark = "reported as '" + result.unreadable + "', which could not be " +
        'read as a measurement, a detection limit or a lower bound, so it was ' +
        'not compared against any limit. Confirm the result with the laboratory.';
      return row;
    }

    if (pathogen) return assessPathogen(row, result);
    if (unquantified) return assessUnquantified(row, result, entry);

    var limits = limitMaximums(entry);
    if (result.below_detection && missing) {
      return assessBelowDetection(row, result, entry, limits);
    }

    var converted = toGuidelineUnit(Number(result.value), result.unit, entry,
      result.parameter);
    if (converted.value === null) {
      if (!hasLimit(entry)) return noGuidelineUnit(row, entry, result, converted.reason, '');
      row.status = 'indeterminate';
      row.evaluable = false;
      row.reason = converted.reason;
      row.remark = "reported in '" + (result.unit || '') + "' but the " +
        "guideline is in '" + guidelineUnit + "': " +
        INDETERMINATE_REASONS[converted.reason] + '. The value was not ' +
        'compared against any limit.';
      return row;
    }

    row.value_in_guideline_unit = converted.value;
    row.reason = converted.reason;
    row.basis_reason = basisReason(converted.reason);
    gradeRow(row, entry, converted.value, wqUnitNote(Number(result.value),
      result.unit || '', converted.value, converted.reason,
      wqScale(result.unit, entry, converted.reason)));
    return withNitrogenNote(row, entry, converted.value, converted.reason);
  }

  /** How a result the laboratory did not quantify reads in a table: ">50",
   * "≥50", or "detected" for a count seen and not numbered; '' for any
   * other row (assess.py unquantified_text).
   * @param {Rec} row a row of assessSample's table
   * @returns {string}
   */
  function unquantifiedText(row) {
    if ((row.value !== null && row.value !== undefined) ||
        row.greater_than === null || row.greater_than === undefined) {
      return '';
    }
    if (row.greater_than === 0 && !row.greater_than_inclusive) return 'detected';
    return (row.greater_than_inclusive ? '≥' : '>') + formatG(row.greater_than);
  }

  var ESSENTIAL_EQUIVALENTS = { 'nitrate (as no3)': ['nitrate (as n)'] };

  function missingEssential(rows, table) {
    var graded = {};
    rows.forEach(function (row) {
      if (isGraded(row)) graded[normaliseParameter(row.parameter)] = true;
    });
    var missing = [];
    ESSENTIAL_HEALTH_PARAMETERS.forEach(function (key) {
      if (graded[key]) return;
      /* a laboratory that reports nitrate as nitrogen has measured the nitrate */
      var alternatives = ESSENTIAL_EQUIVALENTS[key] || [];
      if (alternatives.some(function (alt) { return graded[alt]; })) return;
      var entry = table[key];
      missing.push(entry ? entry.parameter : key);
    });
    return missing;
  }

  /* The combined index uses the unit-converted concentrations, so a result
   * reported in ug/L is not silently added as though it were mg/L. */
  /* A component reported below detection is taken at its detection limit,
   * and `bounded` says so. That reading is deliberately the pessimistic one:
   * "< 3 mg/L nitrite" beside 49 mg/L nitrate cannot rule out a combined
   * index of 1.98, and treating the unknown as zero turned a sample that
   * might fail the rule into one that passed it silently. */
  function nitrateNitriteIndex(rows, table) {
    /* Each ion is divided by the guideline on the basis its own row is
     * reported on. Only the "as NO3" and "as NO2" rows were looked for, so a
     * laboratory reporting both as nitrogen (10 and 0.8 mg/L as N, an index
     * of 1.76) was never checked against the rule at all. */
    function component(keys) {
      for (var k = 0; k < keys.length; k++) {
        var key = keys[k];
        var entry = table[key];
        var gv = entry && entry.who_health ? entry.who_health.maximum : null;
        for (var i = 0; i < rows.length; i++) {
          var row = rows[i];
          if (normaliseParameter(row.parameter) !== key) continue;
          if (row.value_in_guideline_unit !== null &&
              row.value_in_guideline_unit !== undefined) {
            return [Number(row.value_in_guideline_unit), gv, false];
          }
          if (row.below_detection && entry &&
              row.detection_limit !== null && row.detection_limit !== undefined) {
            var dl = toGuidelineUnit(Number(row.detection_limit), row.unit, entry,
              row.parameter);
            if (dl.value !== null) return [Number(dl.value), gv, true];
          }
        }
      }
      return [null, null, false];
    }
    var a = component(['nitrate (as no3)', 'nitrate (as n)']);
    var b = component(['nitrite (as no2)', 'nitrite (as n)']);
    if (a[0] === null || b[0] === null || !a[1] || !b[1]) return null;
    return { ratio: a[0] / a[1] + b[0] / b[1], no3: a[0], no2: b[0],
      gv3: a[1], gv2: b[1], bounded: a[2] || b[2] };
  }

  /**
   * @param {QualitySample} sample
   * @param {Rec[]|null} [standardsRows]
   * @returns {QualityAssessment}
   */
  function assessSample(sample, standardsRows) {
    var table = loadStandards(standardsRows);
    var rows = [], flags = (sample.flags || []).slice();

    (sample.results || []).forEach(function (result) {
      var entry = table[normaliseParameter(result.parameter)] || null;
      var row = assessResult(result, entry);
      rows.push(row);

      if (row.reason === 'unknown_parameter') {
        flags.push({
          level: 'warning', code: 'unknown_parameter',
          message: "No guideline entry for '" + result.parameter + "'; it was " +
            'not checked against any limit and keeps the sample out of a ' +
            "'suitable for drinking' verdict. Add it to the standards CSV if " +
            'a limit applies.',
        });
      } else if (row.reason === 'unit_assumed') {
        flags.push({
          level: 'info', code: 'unit_not_reported',
          message: "'" + result.parameter + "' carries no usable unit" +
            (result.unit ? " ('" + result.unit + "')" : '') +
            '; it was read as ' + row.guideline_unit +
            '. Confirm against the laboratory certificate.',
        });
      } else if (row.status === 'no_guideline' && UNIT_REFUSALS.indexOf(row.reason) >= 0) {
        flags.push({
          level: 'warning', code: 'value_not_used',
          message: phrase('quality.value_not_used', {
            parameter: String(result.parameter), unit: String(result.unit || ''),
            why: INDETERMINATE_REASONS[row.reason] }),
        });
      } else if (row.status === 'indeterminate') {
        flags.push({
          level: 'error', code: 'indeterminate_' + row.reason,
          message: "'" + result.parameter + "' could not be assessed: " + row.remark,
        });
      } else if (row.reason === STRICTER_LIMIT_UNRESOLVED) {
        flags.push({
          level: 'warning', code: STRICTER_LIMIT_UNRESOLVED,
          message: "'" + result.parameter + "' could not be graded in full: " +
            row.remark + '.',
        });
      }
      /* what the unit's basis did to a measured value, a bound or a
       * detection limit, whatever else the row says */
      var basis = row.basis_reason === 'unit_basis_converted'
        ? basisConversion(result.unit, table[normaliseParameter(result.parameter)]) : null;
      if (row.basis_reason === 'unit_basis_assumed') {
        flags.push({
          level: 'warning', code: 'unit_basis_assumed',
          message: "'" + result.parameter + "' is reported in '" +
            (result.unit || '') + "' but the guideline is written in '" +
            row.guideline_unit + "'. The values were taken as the same basis; " +
            "confirm with the laboratory, since an 'as CaCO3' figure is about " +
            '2.5 times the same concentration expressed as the element.',
        });
      } else if (basis) {
        flags.push({
          level: 'info', code: 'unit_basis_converted',
          message: phrase('quality.unit_basis_converted', {
            parameter: String(result.parameter), unit: String(result.unit || ''),
            guideline: row.guideline_unit, basis: basis[1], factor: basis[0] }),
        });
      }
    });

    /* WHO combined nitrate + nitrite rule: the sum of the ratio of each to its
     * own guideline value must not exceed 1. A sample can pass both individual
     * checks yet fail this, so it is applied only when neither is individually
     * in exceedance. */
    var combined = nitrateNitriteIndex(rows, table);
    if (combined && combined.ratio > 1.0 &&
        combined.no3 <= combined.gv3 && combined.no2 <= combined.gv2) {
      /* A bounded index is an upper bound, not a measurement: it says the
       * rule MAY be breached, which is a question rather than a finding. */
      var bounded = !!combined.bounded;
      rows.push({
        parameter: 'Nitrate + nitrite (combined)',
        value: pyRound(combined.ratio, 2), unit: 'ratio', below_detection: false,
        who_health: '<= 1', who_aesthetic: '', sl_standard: '',
        status: bounded ? 'indeterminate' : 'exceeds_health',
        remark: bounded
          ? 'An upper bound on the combined index (' + formatG(combined.no3) +
            '/' + formatG(combined.gv3) + ' + ' + formatG(combined.no2) + '/' +
            formatG(combined.gv2) + ' = ' + pyFixed(combined.ratio, 2) +
            ') exceeds 1, taking the below-detection component at its ' +
            'detection limit. The WHO combined nitrate and nitrite limit ' +
            'cannot be shown to be met; ask the laboratory for a lower ' +
            'detection limit.'
          : 'The combined index (' + formatG(combined.no3) + '/' +
            formatG(combined.gv3) + ' + ' + formatG(combined.no2) + '/' +
            formatG(combined.gv2) + ' = ' + pyFixed(combined.ratio, 2) +
            ') exceeds 1; the WHO combined nitrate and nitrite limit is not ' +
            'met even though each is within its own guideline value.',
        guideline_unit: 'ratio',
        value_in_guideline_unit: bounded ? null : pyRound(combined.ratio, 2),
        detection_limit: null, evaluable: !bounded,
        reason: bounded ? 'detection_limit_above_guideline' : '',
        greater_than: null, greater_than_inclusive: false, sl_provisional: false,
        basis_reason: '',
      });
      flags.push({
        level: 'warning',
        code: bounded ? 'nitrate_nitrite_combined_unproven'
          : 'nitrate_nitrite_combined',
        message: bounded
          ? 'The combined nitrate + nitrite index cannot be shown to meet the ' +
            'WHO limit: one component is below detection and its detection ' +
            'limit is high enough that the sum may exceed 1.'
          : 'Combined nitrate + nitrite index exceeds 1 (WHO); treat as a ' +
            'health exceedance.',
      });
    }

    var missing = missingEssential(rows, table);
    if (missing.length) {
      flags.push({
        level: 'warning', code: 'incomplete_health_panel',
        message: 'No evaluable result for ' + missing.join(', ') + '. The ' +
          'sample cannot show the water is safe to drink until the health ' +
          'panel is complete.',
      });
    }
    var anyEvaluable = rows.some(function (r) {
      return r.evaluable && r.status !== 'not_measured';
    });
    if (!anyEvaluable) {
      flags.push({
        level: 'error', code: 'nothing_evaluable',
        message: 'No result in this sample could be graded against a guideline ' +
          'value, so no suitability verdict can be given.',
      });
    }

    var ionic = ionicBalance(sample);
    if (ionic && ionic.flag) {
      flags.push(ionic.flag);
    } else if (!ionic) {
      var ionGap = ionicBalanceGap(sample);
      if (ionGap.length) {
        flags.push({
          level: 'warning',
          code: 'ionic_balance_not_checked',
          message: 'The charge balance could not be computed: the analysis ' +
            'carries no ' + pluralNoun(ionGap.length, 'value') + ' for ' +
            ionGap.join(', ') + '. Ask the laboratory for the major ions if ' +
            'the analysis is to be relied on.',
          context: '',
        });
      }
    }
    var corrosivity = assessCorrosivity(sample);
    flags = flags.concat(corrosivity.flags);
    var wqi = computeWqi(sample, standardsRows);
    var healthRisk = assessHealthRisk(sample);
    if (healthRisk) flags = flags.concat(healthRisk.flags);

    var assessment = {
      sample: sample, rows: rows, ionic: ionic, corrosivity: corrosivity,
      wqi: wqi, health_risk: healthRisk, flags: flags,
      missing_essential: missing,
    };
    assessment.health_exceedances = rows.filter(function (r) {
      return r.status === 'exceeds_health';
    });
    assessment.national_exceedances = rows.filter(function (r) {
      return r.status === 'exceeds_national';
    });
    /* National exceedances are deliberately NOT included here. A national
     * limit is law; folding it in reported a compliance failure as a matter
     * of taste and let a breached supply show a 100% pass rate. */
    assessment.aesthetic_exceedances = rows.filter(function (r) {
      return r.status === 'exceeds_aesthetic';
    });
    assessment.all_exceedances = assessment.health_exceedances
      .concat(assessment.national_exceedances)
      .concat(assessment.aesthetic_exceedances);
    assessment.indeterminate_rows = rows.filter(function (r) {
      return r.status === 'indeterminate';
    });
    assessment.unknown_parameters = rows.filter(function (r) {
      return r.reason === 'unknown_parameter';
    });
    assessment.evaluated_rows = rows.filter(isGraded);
    assessment.uncertainties = qualityUncertainties(assessment);
    assessment.verdict_state = qualityVerdictState(assessment);
    assessment.is_potable = assessment.verdict_state === 'health_fail' ||
      assessment.verdict_state === 'national_fail' ? false
      : (assessment.verdict_state === 'indeterminate' ? null : true);
    assessment.verdict = qualityVerdict(assessment);
    return assessment;
  }

  /** Every reason this sample cannot support a "suitable" verdict. Empty means
   * nothing is unresolved.
   * @param {QualityAssessment} assessment
   * @returns {string[]}
   */
  function qualityUncertainties(assessment) {
    var reasons = [];
    if (!assessment.rows.length) {
      reasons.push('the sample carries no laboratory results');
    } else if (!assessment.evaluated_rows.length) {
      reasons.push('no result in the sample could be graded against a ' +
        'guideline value');
    }
    assessment.indeterminate_rows.forEach(function (row) {
      var why = INDETERMINATE_REASONS[row.reason] || 'it could not be evaluated';
      reasons.push(row.parameter + ' could not be assessed: ' + why);
    });
    assessment.rows.forEach(function (row) {
      if (row.reason === STRICTER_LIMIT_UNRESOLVED) {
        reasons.push(row.parameter + ' was not quantified, so a stricter limit ' +
          'than the one it exceeds cannot be ruled out');
      }
    });
    assessment.unknown_parameters.forEach(function (row) {
      reasons.push(row.parameter + ' has no entry in the standards table, so ' +
        'it was not checked against any limit');
    });
    if ((assessment.missing_essential || []).length) {
      reasons.push('the health panel is incomplete: no evaluable result for ' +
        assessment.missing_essential.join(', '));
    }
    return reasons;
  }

  /**
   * @param {QualityAssessment} assessment
   * @returns {string}
   */
  function qualityVerdictState(assessment) {
    if (assessment.health_exceedances.length) return 'health_fail';
    if (assessment.national_exceedances.length) return 'national_fail';
    if (assessment.uncertainties.length) return 'indeterminate';
    if (assessment.aesthetic_exceedances.length) return 'aesthetic';
    return 'pass';
  }

  /** One-line suitability statement for the reports.
   * @param {QualityAssessment} assessment
   * @returns {string}
   */
  function qualityVerdict(assessment) {
    var state = assessment.verdict_state || qualityVerdictState(assessment);
    var health = assessment.health_exceedances;
    var national = assessment.national_exceedances;
    var acceptability = assessment.aesthetic_exceedances;
    function names(list) {
      return list.map(function (r) { return r.parameter; }).join(', ');
    }
    if (state === 'health_fail') {
      return 'The water does not meet the health based guideline ' +
        pluralNoun(health.length, 'value') + ' for: ' + names(health) +
        '. Treatment or an alternative source is required before ' +
        'the water is used for drinking.';
    }
    if (state === 'national_fail') {
      var extra = acceptability.length
        ? ' Acceptability limits are also exceeded for: ' +
          names(acceptability) + '.'
        : '';
      var action = ' Treatment is required before the supply can be accepted ' +
        'against the national standard; check whether the limit exceeded is a ' +
        'health or an acceptability limit.';
      if ((assessment.uncertainties || []).length) {
        /* The national failure outranks the open questions, but it does not
         * answer them: "meets the WHO health based guideline values" was said
         * of an arsenic result nobody could grade. */
        return 'The water does not comply with the national standard ' +
          pluralNoun(national.length, 'limit') + ' for: ' + names(national) +
          '.' + extra + ' It has not been shown to meet the WHO health based ' +
          'guideline values: ' + assessment.uncertainties.join('; ') + '.' + action;
      }
      return 'The water meets the WHO health based guideline values, but does ' +
        'not comply with the national standard ' +
        pluralNoun(national.length, 'limit') + ' for: ' + names(national) +
        '.' + extra + action;
    }
    if (state === 'indeterminate') {
      var also = acceptability.length
        ? ' Acceptability limits are exceeded for: ' + names(acceptability) + '.'
        : '';
      return 'The water cannot be declared suitable for drinking on these ' +
        'results: ' + (assessment.uncertainties || []).join('; ') + '.' + also +
        ' Resolve the outstanding parameters - re-sample, or ask the laboratory ' +
        'for the units and detection limits used - before the supply is signed off.';
    }
    if (state === 'aesthetic') {
      return 'The water meets all health based guideline values. Acceptability ' +
        '(aesthetic) limits are exceeded for: ' + names(acceptability) + '. The ' +
        'water is usable for drinking, although taste, odour or staining ' +
        'complaints may arise; simple treatment is advisable.';
    }
    return 'All measured parameters comply with the WHO guideline values and ' +
      'the national standard limits applied. The water is suitable for drinking ' +
      'on the basis of the parameters tested.';
  }

  /* --- Piper and Stiff geometry --------------------------------------------
   * Returned as plain coordinates so the chart module can draw them and the
   * report module can rasterise the same numbers.
   */

  var SQ3 = Math.sqrt(3.0);

  /** Barycentric (a bottom-left, b bottom-right, c top) to xy.
   * @param {number} a bottom left
   * @param {number} b bottom right
   * @param {number} c top
   * @param {number[]} origin [x, y]
   * @param {number} size
   * @returns {{x: number, y: number}|null}
   */
  function ternaryXy(a, b, c, origin, size) {
    var total = a + b + c;
    if (total <= 0) return null;
    a /= total; b /= total; c /= total;
    return {
      x: origin[0] + (b + 0.5 * c) * size,
      y: origin[1] + (SQ3 / 2.0) * c * size,
    };
  }

  /** The three Piper points for one sample: cation triangle, anion triangle and
   * the diamond, the latter being the intersection of the +60 degree line
   * through the cation point and the -60 degree line through the anion point.
   * @param {QualitySample} sample
   * @param {{size: number, gap: number}} [geometry]
   */
  function piperPoints(sample, geometry) {
    var g = geometry || { size: 1.0, gap: 0.18 };
    var size = g.size, gap = g.gap;
    var catOrigin = [0, 0], anOrigin = [size + gap, 0];
    var ionic = ionicBalance(sample);
    if (!ionic) return null;
    var cat = ionic.cations_meq, an = ionic.anions_meq;
    var ca = cat.calcium || 0, mg = cat.magnesium || 0;
    var nak = (cat.sodium || 0) + (cat.potassium || 0);
    var cl = an.chloride || 0, so4 = an.sulfate || 0;
    var hco3 = (an.bicarbonate || 0) + (an.carbonate || 0);

    var pCat = ternaryXy(ca, nak, mg, catOrigin, size);
    var pAn = ternaryXy(hco3, cl, so4, anOrigin, size);
    if (!pCat || !pAn) return null;
    var xd = 0.5 * (pCat.x + pAn.x) + (pAn.y - pCat.y) / (2.0 * SQ3);
    var yd = pCat.y + SQ3 * (xd - pCat.x);
    return {
      cation: pCat, anion: pAn, diamond: { x: xd, y: yd },
      fractions: {
        ca: ca, mg: mg, nak: nak, cl: cl, so4: so4, hco3: hco3,
      },
      facies: piperFacies(ca, mg, nak, cl, so4, hco3),
    };
  }

  /** The dominant-ion name a hydrogeologist would write in the report.
   * @param {number} ca
   * @param {number} mg
   * @param {number} nak
   * @param {number} cl
   * @param {number} so4
   * @param {number} hco3
   * @returns {string}
   */
  function piperFacies(ca, mg, nak, cl, so4, hco3) {
    var catTotal = ca + mg + nak, anTotal = cl + so4 + hco3;
    if (catTotal <= 0 || anTotal <= 0) return '';
    var cations = /** @type {Array<[string, number]>} */ ([['Ca', ca], ['Mg', mg], ['Na+K', nak]])
      .sort(function (a, b) { return b[1] - a[1]; });
    var anions = /** @type {Array<[string, number]>} */ ([['Cl', cl], ['SO4', so4], ['HCO3', hco3]])
      .sort(function (a, b) { return b[1] - a[1]; });
    var catName = cations[0][1] / catTotal >= 0.5 ? cations[0][0] : 'mixed';
    var anName = anions[0][1] / anTotal >= 0.5 ? anions[0][0] : 'mixed';
    if (catName === 'mixed' && anName === 'mixed') return 'mixed water type';
    return catName + '-' + anName + ' water type';
  }

  /** groundwater/quality/diagrams.py facies_of. The Piper diagram used to be
   * the whole of a section headed "Hydrochemical Facies", with nothing said
   * about what it showed, so the sentence is built here, beside the geometry
   * the diagram is drawn from, and the report only prints it. Null without a
   * complete major-ion analysis, exactly as the Python returns None.
   * @param {QualitySample} sample
   */
  function faciesOf(sample) {
    var ionic = ionicBalance(sample);
    if (!ionic) return null;
    var cat = ionic.cations_meq, an = ionic.anions_meq;
    var ca = cat.calcium || 0, mg = cat.magnesium || 0;
    var nak = (cat.sodium || 0) + (cat.potassium || 0);
    var hco3 = (an.bicarbonate || 0) + (an.carbonate || 0);
    var cl = an.chloride || 0, so4 = an.sulfate || 0;
    var catTotal = ca + mg + nak, anTotal = hco3 + cl + so4;
    if (catTotal <= 0 || anTotal <= 0) return null;

    /* Pairs, not an object: the order is the order the percentages are read
     * out in, and it is also what settles a dead heat, because Python's
     * max() over a dict keeps the first key of a tie and an object rebuilt
     * from its keys would not promise that. */
    var cations = [['Ca', ca / catTotal], ['Mg', mg / catTotal],
      ['Na+K', nak / catTotal]];
    var anions = [['HCO3', hco3 / anTotal], ['Cl', cl / anTotal],
      ['SO4', so4 / anTotal]];

    function lead(pairs) {
      var best = pairs[0];
      for (var i = 1; i < pairs.length; i++) {
        if (pairs[i][1] > best[1]) best = pairs[i];
      }
      return best;
    }
    /* pyFixed, not toFixed: Python's "%.0f" sends a tie to the even digit,
     * so an ion sitting on exactly 12.5 percent prints as 12 in both engines. */
    function pct(pairs) {
      return pairs.map(function (p) {
        return p[0] + ' ' + pyFixed(p[1] * 100, 0) + '%';
      }).join(', ');
    }
    function fractions(pairs) {
      var out = {};
      pairs.forEach(function (p) { out[p[0]] = p[1]; });
      return out;
    }

    var leadCat = lead(cations), leadAn = lead(anions);
    var catName = leadCat[1] >= 0.5 ? leadCat[0] : 'mixed-cation';
    var anName = leadAn[1] >= 0.5 ? leadAn[0] : 'mixed-anion';
    var facies = catName + '-' + anName;

    var meaning;
    if (anName === 'HCO3' && (catName === 'Ca' || catName === 'Mg')) {
      meaning = 'a fresh, recently recharged water of the kind weathering of ' +
        'silicate rock gives; typical of shallow basement groundwater';
    } else if (anName === 'HCO3' && catName === 'Na+K') {
      meaning = 'a bicarbonate water in which sodium and potassium have ' +
        'replaced calcium, which points to longer contact with the rock or ' +
        'to ion exchange in a clayey weathered zone';
    } else if (anName === 'HCO3') {
      /* No cation holds half the total, so sodium and potassium hold less
       * than half and calcium and magnesium together hold more. Dr Timbo's
       * water (Ca 40%, Mg 26%, Na+K 34%) was said to be one in which sodium
       * had replaced calcium. */
      meaning = 'a bicarbonate water with no single dominant cation, in which ' +
        'calcium and magnesium together still outweigh sodium and potassium; ' +
        'a fresh water of the kind weathering of silicate rock gives, with ' +
        'the sodium share pointing to feldspar weathering or some ion ' +
        'exchange along the flow path';
    } else if (anName === 'Cl' && catName === 'Na+K') {
      meaning = 'a sodium chloride water, which in this setting points to ' +
        'salinity from the coast, an estuary or evaporation rather than to ' +
        'rock weathering';
    } else if (anName === 'Cl' && (catName === 'Ca' || catName === 'Mg')) {
      /* it has a dominant ion pair, and was called a water without one */
      meaning = 'a ' + (catName === 'Ca' ? 'calcium' : 'magnesium') +
        ' chloride water, which is unusual in fresh basement groundwater; it ' +
        'can point to saline water exchanging with the aquifer or to ' +
        'pollution, and is worth checking against the sample\'s provenance';
    } else if (anName === 'Cl') {
      meaning = 'a chloride water with no single dominant cation, which points ' +
        'to salinity or pollution mixed into the groundwater rather than to ' +
        'rock weathering alone';
    } else if (anName === 'SO4') {
      meaning = 'a sulfate water, which is unusual in basement ground and ' +
        'worth checking against the sample\'s provenance';
    } else if (catName === 'mixed-cation') {
      meaning = 'a mixed water with no single dominant ion pair';
    } else {
      meaning = 'a water with no single dominant anion, of mixed origin or in ' +
        'transition between types';
    }

    return {
      facies: facies,
      cations: fractions(cations),
      anions: fractions(anions),
      sentence: 'The water is a ' + facies + ' type (' + pct(cations) + '; ' +
        pct(anions) + ', in milliequivalent percent): ' + meaning + '.',
    };
  }

  /** Stiff polygon: Na+K / Ca / Mg on the left, Cl / HCO3 / SO4 on the right.
   * @param {QualitySample} sample
   */
  function stiffRows(sample) {
    var ionic = ionicBalance(sample);
    if (!ionic) return null;
    var cat = ionic.cations_meq, an = ionic.anions_meq;
    return [
      { left: (cat.sodium || 0) + (cat.potassium || 0), right: an.chloride || 0,
        leftLabel: 'Na+K', rightLabel: 'Cl' },
      { left: cat.calcium || 0, right: (an.bicarbonate || 0) + (an.carbonate || 0),
        leftLabel: 'Ca', rightLabel: 'HCO3' },
      { left: cat.magnesium || 0, right: an.sulfate || 0,
        leftLabel: 'Mg', rightLabel: 'SO4' },
    ];
  }

  Object.assign(C, {
    parseLimit: parseLimit, limitExceededBy: limitExceededBy, limitText: limitText,
    normaliseParameter: normaliseParameter, loadStandards: loadStandards,
    faecalPathogen: faecalPathogen,
    PROVISIONAL_NATIONAL_NOTE: PROVISIONAL_NATIONAL_NOTE,
    provisionalNationalParameters: provisionalNationalParameters,
    sampleValue: sampleValue, canonicalValues: canonicalValues,
    ionicBalance: ionicBalance,
    computeWqi: computeWqi, assessHealthRisk: assessHealthRisk,
    assessCorrosivity: assessCorrosivity, assessSample: assessSample,
    qualityVerdict: qualityVerdict, STATUS_ORDER: STATUS_ORDER,
    qualityVerdictState: qualityVerdictState,
    qualityUncertainties: qualityUncertainties,
    unquantifiedText: unquantifiedText, readQualityCell: readQualityCell,
    STRICTER_LIMIT_UNRESOLVED: STRICTER_LIMIT_UNRESOLVED,
    WQ_STATUS_LABELS: WQ_STATUS_LABELS, VERDICT_ORDER: VERDICT_ORDER,
    VERDICT_SHORT: VERDICT_SHORT, VERDICT_LONG: VERDICT_LONG,
    VERDICT_TONE: VERDICT_TONE,
    ESSENTIAL_HEALTH_PARAMETERS: ESSENTIAL_HEALTH_PARAMETERS,
    ternaryXy: ternaryXy, piperPoints: piperPoints, piperFacies: piperFacies,
    faciesOf: faciesOf, stiffRows: stiffRows,
  });
