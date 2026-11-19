
  /* =========================================================== desk study
   * groundwater/desk_study.py (PLAN.md step 4.4): what is known of a site
   * before anyone travels to it, as plain data both engines build the same
   * way, which the two document writers lay out. Every number is already
   * written as text, through the catalogue in data/text/desk_study.yaml and
   * the engines' shared formatters, so parity compares the content whole. */

  /* PLAN.md step 4.4's 5 km, and how many water points are listed. */
  var PORTFOLIO_RADIUS_M = 5000.0;
  var WATER_POINTS_LISTED = 15;
  /* how far the site may have moved since the terrain was analysed round it */
  var DESK_TERRAIN_SITE_TOLERANCE_M = 1.0;

  /** The ground under a position on the bundled maps: site_ground. Each
   * field is '' where the maps have nothing, or where there is no position.
   * @param {{lat: number, lon: number}|null} latlon
   * @param {string} [district]
   * @returns {{glg: string, unit: string, formation: string, lithology: string,
   *   bgs_code: string, aquifer: string, aquifer_geology: string}} */
  function siteGround(latlon, district) {
    var out = { glg: '', unit: '', formation: '', lithology: '', bgs_code: '', aquifer: '',
      aquifer_geology: '' };
    if (!latlon) return out;
    var unit = geologyUnitAt(latlon.lat, latlon.lon);
    if (unit) {
      var props = unit.properties || {};
      out.glg = String(own(props, 'glg') ? props.glg : '');
      out.unit = String(own(props, 'unit') ? props.unit : (own(props, 'glg') ? props.glg : 'unit'));
      var scope = unitDistrict(unit.geometry) || district || '';
      var row = lithologyFor(out.glg, scope);
      out.formation = row ? String(row.formation_name || '').trim() : '';
      out.lithology = describeLithology(out.glg, scope);
    }
    var aquifer = aquiferUnitAt(latlon.lat, latlon.lon);
    if (aquifer) {
      var aq = aquifer.properties || {};
      out.bgs_code = String(own(aq, 'code') ? aq.code : '');
      out.aquifer = String(own(aq, 'unit') ? aq.unit : 'unit');
      out.aquifer_geology = String(own(aq, 'geology') ? aq.geology : '');
    }
    return out;
  }

  function deskPosition(lat, lon) {
    return phrase('desk_study.position', { lat: lat, lon: Math.abs(lon) });
  }

  /** What a desk study says of an analysed terrain, small enough to keep:
   * desk_study_terrain.
   * @param {Rec} lineaments what lineamentCandidates returns
   * @param {Rec|null} plan what surveyPlan returns, or null
   * @param {ArrayLike<number>} lons
   * @param {ArrayLike<number>} lats
   * @param {Rec} captions the terrain, lineament and plan captions merged
   * @param {string} label what the files are
   * @returns {Rec} */
  function deskStudyTerrain(lineaments, plan, lons, lats, captions, label) {
    var found = lineaments.lineaments;
    var valleys = 0, km = 0.0;
    found.forEach(function (/** @type {Rec} */ item) {
      if (item.kind === 'valley') valleys += 1;
      km = km + item.length_m;
    });
    var totals = [];
    for (var b = 0; b < LIN_ROSE_BANDS; b++) totals.push(lineaments.roseValleyM[b] + lineaments.roseRidgeM[b]);
    var band = 0;
    for (b = 1; b < LIN_ROSE_BANDS; b++) if (totals[b] > totals[band]) band = b;
    /** @type {Rec} */
    var kept = {};
    ['relief', 'lineaments', 'rose', 'plan', 'plan_note'].forEach(function (key) {
      if (own(captions, key)) kept[key] = String(captions[key]);
    });
    /** @type {Rec} */
    var out = {
      label: label, site: null, candidates: found.length, valleys: valleys, ridges: found.length - valleys,
      km: km / 1000.0, band_low: band * 10.0, band_high: band * 10.0 + 10.0, band_km: totals[band] / 1000.0,
      near: null, basis: null, captions: kept, lines: [], soundings: [],
    };
    if (!plan) return out;
    out.site = [plan.site_lonlat[1], plan.site_lonlat[0]];
    out.near = plan.near.length;
    out.basis = plan.basis;
    plan.lines.forEach(function (/** @type {Rec} */ line) {
      var a = lineamentLonLat(plan, lons, lats, lineStation(line, line.first));
      var z = lineamentLonLat(plan, lons, lats, lineStation(line, line.last));
      out.lines.push([phrase('survey_plan.line_name', { line: line.id }), pyFixed(line.bearing_deg, 0),
        formatG(line.length_m), deskPosition(a[1], a[0]), deskPosition(z[1], z[0])]);
    });
    plan.soundings.forEach(function (/** @type {Rec} */ x) {
      var at = lineamentLonLat(plan, lons, lats, x.point);
      out.soundings.push([phrase('survey_plan.ves_name', { n: x.id }), String(x.line), pyFixed(x.at_m, 1),
        deskPosition(at[1], at[0]), surveySoundingText(plan, x)]);
    });
    return out;
  }

  /** One section of the desk study, as both writers lay it out.
   * @param {string} key
   * @param {string} heading
   * @returns {{key: string, heading: string, paragraphs: string[], tables: Rec[], figures: Rec[],
   *   bullets: string[]}} */
  function deskSection(key, heading) {
    return { key: key, heading: heading, paragraphs: [], tables: [], figures: [], bullets: [] };
  }

  /* the water points within the search radius, nearest first: _water_section */
  function deskWaterSection(latlon, waterPoints, radiusM) {
    var section = deskSection('water_points', phrase('desk_study.water_heading'));
    if (!latlon) {
      section.paragraphs.push(phrase('desk_study.water_no_position'));
      return { section: section, found: null };
    }
    if (waterPoints === null || waterPoints === undefined) {
      section.paragraphs.push(phrase('desk_study.water_not_loaded'));
      return { section: section, found: null };
    }
    /* the browser's reader already shows a point's technology where its
     * source is blank, as _water_rows does */
    var near = pointsWithin(waterPoints, latlon.lat, latlon.lon, radiusM);
    if (!near.length) {
      section.paragraphs.push(phrase('desk_study.water_none', { radius: radiusM }));
      return { section: section, found: { total: 0, working: 0, serving: 0, rehab: 0 } };
    }
    var working = 0, broken = 0, serving = 0, rehab = 0, nearest = null;
    near.forEach(function (/** @type {Rec} */ r) {
      if (r.functional === true) working += 1;
      if (r.functional === false) broken += 1;
      if (r.functional === true && r.improved && r.distance_m <= SERVICE_RADIUS_M) serving += 1;
      if (r.functional === false && r.improved && r.distance_m <= SERVICE_RADIUS_M) rehab += 1;
      if (nearest === null && r.functional === true && r.improved) nearest = r.distance_m;
    });
    var unknown = near.length - working - broken;
    var paragraphs = [phrase('desk_study.water_counts', { total: near.length, radius: radiusM,
      working: working, broken: broken, unknown: unknown })];
    if (serving) {
      paragraphs.push(phrase('desk_study.water_serving', { count: serving, radius: SERVICE_RADIUS_M }));
    } else if (nearest !== null) {
      paragraphs.push(phrase('desk_study.water_nearest', { distance: nearest }));
    } else {
      paragraphs.push(phrase('desk_study.water_no_working', { radius: radiusM }));
    }
    if (rehab) paragraphs.push(phrase('desk_study.water_rehab', { count: rehab, radius: SERVICE_RADIUS_M }));
    paragraphs.push(phrase('desk_study.water_depth'));
    function status(/** @type {Rec} */ r) {
      if (r.functional === true) return phrase('desk_study.water_working');
      if (r.functional === false) return phrase('desk_study.water_broken');
      return phrase('desk_study.water_unknown');
    }
    section.paragraphs = paragraphs;
    section.tables.push({
      caption: phrase('desk_study.water_caption', { radius: radiusM }),
      header: [phrase('desk_study.water_col_distance'), phrase('desk_study.water_col_status'),
        phrase('desk_study.water_col_source'), phrase('desk_study.water_col_installed')],
      rows: near.slice(0, WATER_POINTS_LISTED).map(function (/** @type {Rec} */ r) {
        return [fmtNum(r.distance_m), status(r), String(r.source || ''),
          r.installed === null || r.installed === undefined ? '' : String(r.installed)];
      }),
    });
    if (near.length > WATER_POINTS_LISTED) {
      section.paragraphs.push(phrase('desk_study.water_more', { count: near.length - WATER_POINTS_LISTED,
        radius: radiusM }));
    }
    return { section: section, found: { total: near.length, working: working, serving: serving, rehab: rehab } };
  }

  function deskWaterQuality(summary) {
    var read = summaryVerdictState(summary);
    var water = read[0] && own(VERDICT_SHORT, read[0]) ? String(VERDICT_SHORT[read[0]]) : '';
    return water && read[1] ? water + '*' : water;
  }

  /* the earlier projects within 5 km, nearest first: _projects_section */
  function deskProjectsSection(latlon, portfolio) {
    var km = PORTFOLIO_RADIUS_M / 1000.0;
    var section = deskSection('projects', phrase('desk_study.projects_heading', { km: km }));
    if (!latlon) {
      section.paragraphs.push(phrase('desk_study.projects_no_position'));
      return { section: section, found: null };
    }
    if (portfolio === null || portfolio === undefined) {
      section.paragraphs.push(phrase('desk_study.projects_not_loaded'));
      return { section: section, found: null };
    }
    var near = [], unplaced = 0;
    /** @type {string[]} */
    var degrees = [];
    portfolio.forEach(function (/** @type {Rec} */ summary) {
      var at = summaryLatLon(summary);
      if (!at) {
        /* a project whose boxes hold degrees is named, so that it can be
         * put right, rather than counted with those that record nothing */
        if (summaryHoldsDegrees(summary)) degrees.push(portfolioSiteLabel(summary));
        else unplaced += 1;
        return;
      }
      var distance = geodesicDistanceM(latlon.lat, latlon.lon, at.lat, at.lon);
      if (distance <= PORTFOLIO_RADIUS_M) near.push([distance, summary]);
    });
    near.sort(function (a, b) { return a[0] - b[0]; });
    if (!near.length) {
      section.paragraphs.push(phrase('desk_study.projects_none', { km: km }));
    } else {
      var statuses = near.map(function (item) { return classifyStatus(item[1]); });
      var successful = statuses.filter(function (x) { return x === 'successful'; }).length;
      var dry = statuses.filter(function (x) { return x === 'dry'; }).length;
      section.paragraphs.push(phrase('desk_study.projects_found', { count: near.length, km: km,
        drilled: successful + dry, successful: successful }));
      section.tables.push({
        caption: phrase('desk_study.projects_caption', { km: km }),
        header: [phrase('desk_study.projects_col_project'), phrase('desk_study.projects_col_distance'),
          phrase('desk_study.projects_col_status'), phrase('desk_study.projects_col_depth'),
          phrase('desk_study.projects_col_yield'), phrase('desk_study.projects_col_water')],
        rows: near.map(function (item, i) {
          var depth = summaryNum(item[1].total_depth_m), yieldM3h = summaryNum(item[1].safe_yield_m3_per_h);
          return [portfolioSiteLabel(item[1]), pyFixed(item[0] / 1000.0, 1), statusLabel(statuses[i]),
            depth ? pyFixed(depth, 1) : '', yieldM3h ? pyFixed(yieldM3h, 2) : '', deskWaterQuality(item[1])];
        }),
      });
    }
    if (degrees.length) {
      section.paragraphs.push(phrase('desk_study.projects_degrees', { count: degrees.length,
        names: andJoin(degrees) }));
    }
    if (unplaced) section.paragraphs.push(phrase('desk_study.projects_unplaced', { count: unplaced }));
    return { section: section, found: near.length };
  }

  /* the ground under the site, as a table of the two maps: _ground_section */
  function deskGroundSection(latlon, ground, odds) {
    var section = deskSection('ground', phrase('desk_study.ground_heading'));
    if (!latlon) {
      section.paragraphs.push(phrase('desk_study.ground_no_position'));
      return section;
    }
    section.paragraphs.push(phrase('desk_study.ground_lead'));
    var none = phrase('desk_study.ground_none');
    var geology = ground.glg
      ? [phrase('desk_study.ground_unit', { unit: ground.unit, code: ground.glg }), ground.lithology]
      : [none, ''];
    var aquifer;
    if (!ground.bgs_code) {
      aquifer = [none, ''];
    } else if (odds.matched !== 'fallback' && odds.yield_q1_l_per_s !== null &&
               odds.yield_q1_l_per_s !== undefined) {
      aquifer = [phrase('desk_study.ground_unit', { unit: ground.aquifer, code: ground.bgs_code }),
        phrase('desk_study.ground_yield', { q1: odds.yield_q1_l_per_s, q3: odds.yield_q3_l_per_s })];
    } else {
      aquifer = [phrase('desk_study.ground_unit', { unit: ground.aquifer, code: ground.bgs_code }),
        phrase('desk_study.ground_no_yield')];
    }
    section.tables.push({
      caption: phrase('desk_study.ground_caption'),
      header: [phrase('desk_study.ground_col_map'), phrase('desk_study.ground_col_unit'),
        phrase('desk_study.ground_col_meaning')],
      rows: [[phrase('desk_study.ground_map_geology')].concat(geology),
        [phrase('desk_study.ground_map_aquifer')].concat(aquifer)],
    });
    return section;
  }

  /* whether the terrain was analysed round this site: _terrain_usable */
  function deskTerrainUsable(terrain, latlon) {
    if (!terrain) return false;
    if (terrain.site === null || !latlon) return terrain.site === null && !latlon;
    return geodesicDistanceM(latlon.lat, latlon.lon, terrain.site[0], terrain.site[1]) <=
      DESK_TERRAIN_SITE_TOLERANCE_M;
  }

  function deskTerrainSection(terrain, usable) {
    var section = deskSection('terrain', phrase('desk_study.terrain_heading'));
    if (!terrain) {
      section.paragraphs.push(phrase('desk_study.terrain_none'));
      return section;
    }
    if (!usable) {
      section.paragraphs.push(phrase('desk_study.terrain_elsewhere'));
      return section;
    }
    var captions = terrain.captions;
    if (terrain.candidates) {
      var found = phrase('desk_study.terrain_found', { label: terrain.label, candidates: terrain.candidates,
        valleys: terrain.valleys, ridges: terrain.ridges, km: terrain.km, band_low: terrain.band_low,
        band_high: terrain.band_high, band_km: terrain.band_km });
      if (terrain.near) {
        found += ' ' + phrase('desk_study.terrain_near', { near: terrain.near, radius: SERVICE_RADIUS_M });
      } else if (terrain.near !== null) {
        found += ' ' + phrase('desk_study.terrain_near_none', { radius: SERVICE_RADIUS_M });
      }
      section.paragraphs.push(found);
    } else {
      section.paragraphs.push(phrase('desk_study.terrain_found_none', { label: terrain.label }));
    }
    var keys = terrain.candidates ? ['relief', 'lineaments', 'rose'] : ['relief', 'lineaments'];
    keys.forEach(function (key) {
      if (own(captions, key)) section.figures.push({ key: key, caption: captions[key] });
    });
    return section;
  }

  function deskPlanSection(terrain, usable) {
    var section = deskSection('plan', phrase('desk_study.plan_heading'));
    if (!terrain || !usable) {
      section.paragraphs.push(phrase('desk_study.plan_no_terrain'));
      return section;
    }
    var captions = terrain.captions;
    if (own(captions, 'plan')) section.paragraphs.push(captions.plan);
    if (terrain.lines.length) {
      section.figures.push({ key: 'plan', caption: own(captions, 'plan_note') ? captions.plan_note : '' });
      section.tables.push({
        caption: phrase('desk_study.plan_lines_caption'),
        header: [phrase('desk_study.plan_col_line'), phrase('desk_study.plan_col_bearing'),
          phrase('desk_study.plan_col_length'), phrase('desk_study.plan_col_start'),
          phrase('desk_study.plan_col_end')],
        rows: terrain.lines.map(function (row) { return row.slice(); }),
      });
    }
    if (terrain.soundings.length) {
      section.tables.push({
        caption: phrase('desk_study.plan_soundings_caption'),
        header: [phrase('desk_study.plan_col_sounding'), phrase('desk_study.plan_col_line'),
          phrase('desk_study.plan_col_along'), phrase('desk_study.plan_col_position'),
          phrase('desk_study.plan_col_where')],
        rows: terrain.soundings.map(function (row) { return row.slice(); }),
      });
    }
    return section;
  }

  /** Everything the desk study says, as plain data: desk_study_content.
   * `options` holds waterPoints (as parseWpdxRecords read them; null where
   * none were loaded), searchRadiusM (1000 m where not given), portfolio
   * (project summaries; null where none was loaded), terrain (what
   * deskStudyTerrain kept; null where none was analysed) and config.
   * @param {Rec|null} site the project's header block: its names
   * @param {string} where the place, as the terrain captions name it
   * @param {{lat: number, lon: number}|null} latlon the site's GPS position
   * @param {Rec} [options]
   * @returns {Rec} */
  function deskStudyContent(site, where, latlon, options) {
    var opts = options || {};
    var cfg = opts.config || defaultConfig();
    where = String(where || '').trim() || phrase('desk_study.where_unnamed');
    var radiusM = opts.searchRadiusM === undefined || opts.searchRadiusM === null
      ? DEFAULT_SEARCH_RADIUS_M : Number(opts.searchRadiusM);
    var terrain = opts.terrain || null;
    var names = site || {};
    var district = String(names.district || '');
    var ground = siteGround(latlon, district);
    var odds = priorOdds(ground.bgs_code || null, ground.glg || null, cfg);
    var usable = deskTerrainUsable(terrain, latlon);

    var rows = [];
    [['desk_study.site_community', 'community'], ['desk_study.site_chiefdom', 'chiefdom'],
      ['desk_study.site_district', 'district']].forEach(function (pair) {
      var value = String(names[pair[1]] || '').trim();
      if (value) rows.push([phrase(pair[0]), value]);
    });
    if (!latlon) {
      rows.push([phrase('desk_study.site_position'), phrase('desk_study.no_position')]);
    } else {
      var utm = geographicToUtm(latlon.lat, latlon.lon);
      rows.push([phrase('desk_study.site_position'), deskPosition(latlon.lat, latlon.lon)]);
      rows.push([phrase('desk_study.site_utm'), phrase('desk_study.utm', { zone: utm.zone,
        easting: utm.easting, northing: utm.northing })]);
    }

    var water = deskWaterSection(latlon, opts.waterPoints, radiusM);
    var counts = water.found;
    var projects = deskProjectsSection(latlon, opts.portfolio);
    var nearProjects = projects.found;

    var oddsSection = deskSection('odds', phrase('desk_study.odds_heading'));
    oddsSection.paragraphs = [oddsHeadline(odds), oddsBasisText(odds)[0], oddsPriorText(odds)];
    if (!latlon) oddsSection.paragraphs.push(phrase('desk_study.odds_no_position'));
    oddsSection.paragraphs.push(phrase('desk_study.odds_note'));

    var checks = [phrase('desk_study.check_ground')];
    if (!latlon) checks.push(phrase('desk_study.check_position'));
    if (counts && counts.serving) checks.push(phrase('desk_study.check_serving', { radius: SERVICE_RADIUS_M }));
    if (counts && counts.rehab) checks.push(phrase('desk_study.check_rehab'));
    if (usable && terrain.lines.length) {
      if (terrain.basis === 'candidates') checks.push(phrase('desk_study.check_candidates'));
      checks.push(phrase('desk_study.check_pegs'));
    }
    if (!terrain) checks.push(phrase('desk_study.check_terrain'));
    var checksSection = deskSection('checks', phrase('desk_study.checks_heading'));
    checksSection.bullets = checks;

    var summary = [];
    if (latlon) {
      var rock = ground.formation || ground.unit;
      if (ground.glg && ground.bgs_code) {
        summary.push(phrase('desk_study.summary_ground', { unit: rock, aquifer: ground.aquifer }));
      } else if (ground.glg) {
        summary.push(phrase('desk_study.summary_ground_partial', { unit: rock }));
      } else {
        summary.push(phrase('desk_study.summary_no_ground'));
      }
    }
    summary.push(oddsHeadline(odds));
    if (usable && terrain.site !== null) {
      if (terrain.basis === 'candidates') {
        summary.push(phrase('desk_study.summary_terrain', { candidates: terrain.candidates,
          lines: terrain.lines.length, soundings: terrain.soundings.length }));
      } else if (terrain.basis === 'strike') {
        summary.push(phrase('desk_study.summary_terrain_strike', { candidates: terrain.candidates,
          radius: SERVICE_RADIUS_M }));
      } else {
        summary.push(phrase('desk_study.summary_terrain_none', { candidates: terrain.candidates }));
      }
    }
    if (counts && counts.total) {
      summary.push(phrase('desk_study.summary_water', { total: counts.total, radius: radiusM,
        working: counts.working }));
    } else if (counts) {
      summary.push(phrase('desk_study.summary_water_none', { radius: radiusM }));
    }
    if (nearProjects) {
      summary.push(phrase('desk_study.summary_projects', { count: nearProjects, km: PORTFOLIO_RADIUS_M / 1000.0 }));
    } else if (nearProjects !== null) {
      summary.push(phrase('desk_study.summary_projects_none', { km: PORTFOLIO_RADIUS_M / 1000.0 }));
    }

    var citations = phraseTable('references.citations');
    return {
      title: phrase('desk_study.title', { where: where }),
      subtitle: phrase('desk_study.subtitle'),
      where: where,
      site_heading: phrase('desk_study.site_heading'),
      stamp: { title: phrase('desk_study.stamp_title'), lead: phrase('desk_study.stamp_lead') },
      summary: summary,
      site_rows: rows,
      sections: [deskGroundSection(latlon, ground, odds), deskTerrainSection(terrain, usable), water.section,
        projects.section, oddsSection, deskPlanSection(terrain, usable), checksSection],
      /* the maps the ground is read from, the guide the prior's yields come
       * from, and the inventory (citations.py _REFERENCES_FOR desk_study) */
      references: [citations.usgs_geology, citations.salwaco_geology, citations.bgs_atlas, citations.bgs_guide,
        citations.wpdx],
    };
  }

  Object.assign(C, {
    PORTFOLIO_RADIUS_M: PORTFOLIO_RADIUS_M, WATER_POINTS_LISTED: WATER_POINTS_LISTED,
    siteGround: siteGround, deskStudyTerrain: deskStudyTerrain, deskStudyContent: deskStudyContent,
  });
