
  /* ============================================================ allocation
   * groundwater/allocation.py (PLAN.md step 6.1). Where to drill next within
   * a budget: the areas of the coverage-gap ranking, each with its unserved
   * people (its population less allocation.people_per_borehole for each
   * functional mapped point), the boreholes they justify, the prior odds on
   * the ground covering most of it (areaGround, read at a grid of points)
   * and the expected cost of a working borehole there at those odds, access
   * included; the boreholes chosen to serve the most people within the
   * budget, exactly by dynamic programming over the people served for at
   * most allocation.exact_max_items candidate boreholes, greedily by people
   * per dollar with the linear-programming bound for more. The grid, the ray
   * casting, the sums and the comparisons are Python's, operation for
   * operation, so parity holds the choice to the bit. */

  var ALLOCATION_LEVELS = ['district', 'chiefdom'];
  /* the most entries the exact choice's tables may hold: EXACT_MAX_CELLS */
  var ALLOCATION_MAX_CELLS = 50000000;

  /** _geometry.point_in_ring, operation for operation: each edge from one
   * vertex to the next, crossed where it straddles the point's latitude to
   * the right of it. pointInRing walks the edges the other way round and
   * works the crossing from the other end, which can differ in the last bit.
   * @param {number} lon
   * @param {number} lat
   * @param {number[][]} ring
   * @returns {boolean} */
  function ringHolds(lon, lat, ring) {
    var inside = false;
    for (var k = 0; k + 1 < ring.length; k++) {
      var ya = ring[k][1], yb = ring[k + 1][1];
      if ((ya > lat) !== (yb > lat)) {
        var xa = ring[k][0], xb = ring[k + 1][0];
        if (lon < xa + (lat - ya) * (xb - xa) / (yb - ya)) inside = !inside;
      }
    }
    return inside;
  }

  /* a ring's bounding box: ring_bbox */
  function allocationBox(ring) {
    var box = [Infinity, Infinity, -Infinity, -Infinity];
    for (var k = 0; k < ring.length; k++) {
      if (ring[k][0] < box[0]) box[0] = ring[k][0];
      if (ring[k][1] < box[1]) box[1] = ring[k][1];
      if (ring[k][0] > box[2]) box[2] = ring[k][0];
      if (ring[k][1] > box[3]) box[3] = ring[k][1];
    }
    return box;
  }

  /* inside the ring and none of its holes, a point outside its bounding box
   * untested: _holds */
  function allocationHolds(lon, lat, ring, holes, box) {
    if (lon < box[0] || lon > box[2] || lat < box[1] || lat > box[3]) return false;
    if (!ringHolds(lon, lat, ring)) return false;
    for (var h = 0; h < holes.length; h++) {
      if (ringHolds(lon, lat, holes[h])) return false;
    }
    return true;
  }

  /* a map layer's polygons, part by part in the layer's order, each with the
   * code it is read by (the BGS class's "code", the USGS unit's "glg") */
  function allocationUnits(layer, key) {
    var out = [];
    ((layer || {}).features || []).forEach(function (feature) {
      var geometry = feature.geometry || {};
      var code = String((feature.properties || {})[key] || '') || null;
      var parts = geometry.type === 'MultiPolygon' ? geometry.coordinates
        : [geometry.coordinates || []];
      (parts || []).forEach(function (part) {
        if (!part || !part.length) return;
        out.push({ code: code, ring: part[0], holes: part.slice(1), box: allocationBox(part[0]) });
      });
    });
    return out;
  }

  /* the code on the first unit that holds the point, or null: _first_unit */
  function allocationFirstUnit(lon, lat, units) {
    for (var u = 0; u < units.length; u++) {
      if (allocationHolds(lon, lat, units[u].ring, units[u].holes, units[u].box)) return units[u].code;
    }
    return null;
  }

  /** the [key, count] counted most of some (at least one), a tie to the key
   * first in alphabetical order and null after every name: _most
   * @param {Array<Array<*>>} counts
   * @returns {Array<*>} */
  function allocationMost(counts) {
    var best = counts[0];
    counts.forEach(function (entry) {
      if (entry[1] !== best[1]) { if (entry[1] > best[1]) best = entry; return; }
      if (entry[0] === null) return;
      if (best[0] === null || codePointCompare(entry[0], best[0]) < 0) best = entry;
    });
    return best;
  }

  function allocationCount(counts, key) {
    for (var i = 0; i < counts.length; i++) {
      if (counts[i][0] === key) { counts[i][1] += 1; return; }
    }
    counts.push([key, 1]);
  }

  /* whether the prior table has a row of its own for the class: _has_prior */
  function allocationHasPrior(code) {
    return oddsTables().prior.some(function (/** @type {Rec} */ r) {
      return r.bgs_code === code && r.status !== 'fallback';
    });
  }

  /** The ground covering most of the area some chiefdom polygons make up,
   * read at a grid by grid grid of points over their bounding box:
   * allocation.area_ground.
   * @param {string} name
   * @param {Polygon[]} polys as loadPolygons reads them
   * @param {Rec[]} aquifers the BGS units, part by part, as the layer orders them
   * @param {Rec[]} units the USGS units likewise
   * @param {number} grid points on a side
   * @returns {Rec} */
  function areaGround(name, polys, aquifers, units, grid) {
    var rings = [];
    polys.forEach(function (poly) {
      poly.rings.forEach(function (/** @type {number[][]} */ ring) { if (ring.length) rings.push(ring); });
    });
    var none = { area: name, samples: 0, bgs_code: null, glg: null, class_samples: 0, unit_samples: 0 };
    if (!rings.length) return none;
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    rings.forEach(function (ring) {
      var b = allocationBox(ring);
      x0 = Math.min(x0, b[0]); y0 = Math.min(y0, b[1]);
      x1 = Math.max(x1, b[2]); y1 = Math.max(y1, b[3]);
    });
    var parts = [];
    polys.forEach(function (poly) {
      poly.rings.forEach(function (/** @type {number[][]} */ ring, /** @type {number} */ i) {
        if (ring.length) parts.push({ ring: ring, holes: poly.holes[i] || [], box: allocationBox(ring) });
      });
    });
    var codes = [], glgs = [];
    for (var j = 0; j < grid; j++) {
      var lat = y0 + (j + 0.5) * (y1 - y0) / grid;
      for (var i = 0; i < grid; i++) {
        var lon = x0 + (i + 0.5) * (x1 - x0) / grid;
        var inside = false;
        for (var p = 0; p < parts.length && !inside; p++) {
          inside = allocationHolds(lon, lat, parts[p].ring, parts[p].holes, parts[p].box);
        }
        if (!inside) continue;
        codes.push(allocationFirstUnit(lon, lat, aquifers));
        glgs.push(allocationFirstUnit(lon, lat, units));
      }
    }
    var byClass = [];
    codes.forEach(function (code) {
      if (code !== null && allocationHasPrior(code)) allocationCount(byClass, code);
    });
    if (!byClass.length) return Object.assign(none, { samples: codes.length });
    var top = allocationMost(byClass);
    var byUnit = [];
    codes.forEach(function (code, k) { if (code === top[0]) allocationCount(byUnit, glgs[k]); });
    var unit = allocationMost(byUnit);
    return { area: name, samples: codes.length, bgs_code: top[0], glg: unit[0],
      class_samples: top[1], unit_samples: unit[1] };
  }

  /* worked out once a page: the layers do not change */
  /** @type {Record<string, Record<string, Rec>>} */
  var allocationGroundsHeld = {};

  function allocationWhole(value, name, least) {
    if (typeof value !== 'number' || !isFinite(value) || value !== Math.floor(value) || value < least) {
      throw new Error(name + ' must be a whole number of at least ' + least + ', not ' + String(value));
    }
    return value;
  }

  function allocationFigure(value, name) {
    if (typeof value !== 'number' || !isFinite(value)) {
      throw new Error(name + ' must be a finite number, not ' + String(value));
    }
    return value;
  }

  /** The ground of every district or chiefdom on the bundled layers, a
   * district being the chiefdoms the crosswalk puts in it: area_grounds. The
   * map layers (gwt-geo.js) must be loaded.
   * @param {string} level "district" or "chiefdom"
   * @param {Config} [config]
   * @returns {Record<string, Rec>} */
  function areaGrounds(level, config) {
    if (ALLOCATION_LEVELS.indexOf(level) < 0) {
      throw new Error('the resolution must be district or chiefdom, not ' + String(level));
    }
    var cfg = config || defaultConfig();
    var grid = allocationWhole(cfg.allocation.ground_grid, 'allocation.ground_grid', 1);
    var key = level + '|' + grid;
    if (!allocationGroundsHeld[key]) {
      var layers = geoLayers();
      if (!layers) throw new Error('The map layers (gwt-geo.js) are not loaded.');
      var polys = loadPolygons(layers.chiefdomBoundaries);
      var aquifers = allocationUnits(layers.hydrogeology, 'code');
      var units = allocationUnits(layers.geology, 'glg');
      var crosswalk = loadChiefdomDistrict();
      /** @type {Record<string, Polygon[]>} */
      var groups = {};
      /** @type {string[]} */
      var order = [];
      polys.forEach(function (poly) {
        var area = level === 'chiefdom' ? poly.name
          : (Object.prototype.hasOwnProperty.call(crosswalk, poly.name) ? crosswalk[poly.name] : '');
        if (!area) return;
        if (!Object.prototype.hasOwnProperty.call(groups, area)) { groups[area] = []; order.push(area); }
        groups[area].push(poly);
      });
      /** @type {Record<string, Rec>} */
      var held = {};
      order.forEach(function (area) { held[area] = areaGround(area, groups[area], aquifers, units, grid); });
      allocationGroundsHeld[key] = held;
    }
    return Object.assign({}, allocationGroundsHeld[key]);
  }

  /* the people the k-th borehole of an area serves (1 for the first) */
  function allocationServed(unserved, per, k) {
    return Math.min(per, unserved - per * (k - 1));
  }

  function allocationField(row, name) {
    return row === null || row === undefined ? undefined : row[name];
  }

  /* the cost distribution's figures, refused where they cannot be costs:
   * _cost_figures */
  function allocationCostFigures(cost) {
    var mean = allocationFigure(allocationField(cost, 'mean'), 'the mean cost of a borehole');
    var dry = allocationFigure(allocationField(cost, 'dry_mean'), 'the mean cost of a dry attempt');
    if (!(mean > 0.0) || dry < 0.0) {
      throw new Error('a completed borehole must cost more than nothing, and a dry attempt ' +
        'nothing or more');
    }
    return { mean: mean, dry: dry,
      samples: allocationWhole(allocationField(cost, 'samples'), "the cost's samples", 1),
      seed: allocationWhole(allocationField(cost, 'seed'), "the cost's seed", 0),
      depth: allocationFigure(allocationField(cost, 'depth_m'), "the cost's depth") };
  }

  function allocationCandidates(rows, level, mean, dry, access, cfg, grounds) {
    var per = cfg.allocation.people_per_borehole;
    var out = [];
    /** @type {Record<string, boolean>} */
    var seen = {};
    /* a few kinds of ground between them all, so each is looked up once */
    /** @type {Record<string, Rec>} */
    var priors = {};
    (rows || []).forEach(function (/** @type {Rec} */ row) {
      var name = allocationField(row, 'name');
      if (typeof name !== 'string' || !name) {
        throw new Error('an area of the ranking has no name: ' + String(name));
      }
      if (Object.prototype.hasOwnProperty.call(seen, name)) {
        throw new Error('the area ' + name + ' is in the ranking twice');
      }
      seen[name] = true;
      var population = allocationFigure(allocationField(row, 'population'), 'the population of ' + name);
      var functional = allocationWhole(allocationField(row, 'functional_points'),
        'the functional points of ' + name, 0);
      var short = population - per * functional;
      var unserved = short > 0.0 ? Math.floor(short) : 0;
      var boreholes = Math.ceil(unserved / per);
      var typed = Object.prototype.hasOwnProperty.call(access, name) ? access[name] : 0.0;
      var accessUsd = allocationFigure(typed, 'the access cost of ' + name);
      if (accessUsd < 0.0) {
        throw new Error('the access cost of ' + name + ' must be nothing or more, not ' + String(typed));
      }
      var ground = Object.prototype.hasOwnProperty.call(grounds, name) ? grounds[name] : null;
      var odds = null, costUsd = null;
      if (ground && ground.bgs_code !== null) {
        var key = JSON.stringify([ground.bgs_code, ground.glg]);
        if (!Object.prototype.hasOwnProperty.call(priors, key)) {
          priors[key] = priorOdds(ground.bgs_code, ground.glg, cfg);
        }
        odds = priors[key];
        if (odds.matched === 'fallback') odds = null;
      }
      if (odds) {
        var p = odds.probability;
        /* to the cent, as Python works it out: the odds take logarithms the
         * engines need not round alike */
        costUsd = pyRound(mean + dry * ((1.0 - p) / p) + accessUsd / p, 2);
      }
      out.push({ id: name, district: level === 'district' ? '' : String(allocationField(row, 'district') || ''),
        population: population, functional_points: functional, unserved: unserved,
        boreholes: boreholes, ground: ground, odds: odds, access_usd: accessUsd, cost_usd: costUsd,
        chosen: 0, chosen_usd: 0.0, people: 0, reason: '' });
    });
    /* by code point, as Python sorts them */
    out.sort(function (a, b) { return codePointCompare(a.id, b.id); });
    return out;
  }

  function allocationEligible(c) { return c.unserved > 0 && c.cost_usd !== null; }

  /* the set serving the most people within the budget, the cheapest of
   * those, ties to earlier items: _exact */
  function allocationExact(items, budget) {
    var total = 0;
    items.forEach(function (it) { total += it.people; });
    var dp = new Float64Array(total + 1).fill(Infinity);
    dp[0] = 0.0;
    var takes = [];
    items.forEach(function (it) {
      var w = it.people, c = it.cost;
      var take = new Uint8Array(total + 1);
      for (var v = total; v >= w; v--) {
        var cand = dp[v - w] + c;
        if (cand < dp[v]) { dp[v] = cand; take[v] = 1; }
      }
      takes.push(take);
    });
    var best = 0;
    for (var v = 0; v <= total; v++) if (dp[v] <= budget) best = v;
    var spent = dp[best];
    var chosen = [];
    for (var i = items.length - 1; i >= 0; i--) {
      var w = items[i].people;
      if (best >= w && takes[i][best]) { chosen.push(i); best -= w; }
    }
    return { chosen: chosen, spent: spent };
  }

  /** Choose where to drill within a budget: allocation.allocate.
   * @param {Rec[]} rows the coverage-gap ranking's rows: name, district, population, functional_points
   * @param {number} budgetUsd
   * @param {Rec} cost what sampleCost returns for the Costing page's borehole
   * @param {Rec} options level ("district" or "chiefdom"); access, US$ per attempt by area;
   *   config; grounds in place of areaGrounds(level), for a test
   * @returns {Rec} */
  function allocate(rows, budgetUsd, cost, options) {
    var opts = options || {};
    var level = opts.level;
    if (ALLOCATION_LEVELS.indexOf(level) < 0) {
      throw new Error('the resolution must be district or chiefdom, not ' + String(level));
    }
    var cfg = opts.config || defaultConfig();
    var budget = allocationFigure(budgetUsd, 'the budget');
    if (!(budget > 0.0)) throw new Error('the budget must be more than nothing, not ' + String(budgetUsd));
    var per = allocationWhole(cfg.allocation.people_per_borehole, 'allocation.people_per_borehole', 1);
    var limit = allocationWhole(cfg.allocation.exact_max_items, 'allocation.exact_max_items', 0);
    var grid = allocationWhole(cfg.allocation.ground_grid, 'allocation.ground_grid', 1);
    if (limit * limit * per > ALLOCATION_MAX_CELLS) {
      throw new Error('allocation.exact_max_items squared times allocation.people_per_borehole is ' +
        costUsd(limit * limit * per) + '; the exact choice keeps a table that large, and takes at most ' +
        costUsd(ALLOCATION_MAX_CELLS));
    }
    var figures = allocationCostFigures(cost);
    var grounds = opts.grounds || areaGrounds(level, cfg);
    var candidates = allocationCandidates(rows, level, figures.mean, figures.dry, opts.access || {}, cfg,
      grounds);

    var items = [];
    candidates.forEach(function (cand, ci) {
      if (!allocationEligible(cand)) return;
      var c = cand.cost_usd;
      var most = Math.min(cand.boreholes, Math.floor(budget / c));
      for (var k = 1; k <= most; k++) {
        items.push({ ci: ci, k: k, people: allocationServed(cand.unserved, per, k), cost: c });
      }
    });
    var order = items.map(function (_it, i) { return i; });
    order.sort(function (a, b) {
      var ra = items[a].people / items[a].cost, rb = items[b].people / items[b].cost;
      return (rb - ra) || (items[a].ci - items[b].ci) || (items[a].k - items[b].k);
    });
    var method, picked;
    if (items.length <= limit) {
      method = 'exact';
      picked = items.length ? allocationExact(items, budget) : { chosen: [], spent: 0.0 };
    } else {
      method = 'greedy';
      var spentSoFar = 0.0, greedy = [];
      order.forEach(function (i) {
        if (spentSoFar + items[i].cost <= budget) { spentSoFar += items[i].cost; greedy.push(i); }
      });
      picked = { chosen: greedy, spent: spentSoFar };
    }
    /* the linear-programming bound: _bound */
    var bound = 0.0;
    if (items.length) {
      var lpSpent = 0.0;
      for (var b = 0; b < order.length; b++) {
        var it = items[order[b]];
        if (lpSpent + it.cost <= budget) { lpSpent += it.cost; bound += it.people; }
        else { bound += it.people * ((budget - lpSpent) / it.cost); break; }
      }
    }
    picked.chosen.forEach(function (/** @type {number} */ i) { candidates[items[i].ci].chosen += 1; });
    var spent = picked.spent, left = budget - spent;
    var least = null, people = 0, boreholes = 0, attempts = 0.0;
    candidates.forEach(function (cand) {
      if (!cand.chosen) return;
      var c = cand.cost_usd;
      cand.chosen_usd = c * cand.chosen;
      cand.people = Math.min(per * cand.chosen, cand.unserved);
      var ratio = 1000.0 * allocationServed(cand.unserved, per, cand.chosen) / c;
      least = least === null || ratio < least ? ratio : least;
      people += cand.people;
      boreholes += cand.chosen;
      attempts += cand.chosen / cand.odds.probability;
    });
    candidates.forEach(function (cand) {
      if (cand.unserved <= 0) cand.reason = 'unserved';
      else if (cand.cost_usd === null) cand.reason = 'odds';
      else if (cand.chosen === cand.boreholes) cand.reason = 'all';
      else if (cand.chosen) cand.reason = 'part';
      else if (least !== null && 1000.0 * allocationServed(cand.unserved, per, 1) / cand.cost_usd < least) {
        cand.reason = 'value';
      } else cand.reason = 'budget';
    });
    var marginal = null;
    candidates.forEach(function (cand) {
      if (!allocationEligible(cand) || cand.chosen >= cand.boreholes) return;
      var c = cand.cost_usd, w = allocationServed(cand.unserved, per, cand.chosen + 1);
      if (marginal === null || w / c > marginal.people / marginal.cost_usd) {
        marginal = { area: cand.id, cost_usd: c, people: w, usd_per_person: c / w, more_usd: c - left };
      }
    });
    var cheapest = null;
    candidates.forEach(function (cand) {
      if (allocationEligible(cand) && (cheapest === null || cand.cost_usd < cheapest.cost_usd)) cheapest = cand;
    });
    function group(cand) {
      if (cand.chosen) return 0;
      if (allocationEligible(cand)) return 1;
      return cand.reason === 'odds' ? 2 : 3;
    }
    function firstRatio(cand) {
      return group(cand) < 2 ? allocationServed(cand.unserved, per, 1) / cand.cost_usd : 0.0;
    }
    var ordered = candidates.slice().sort(function (a, b) {
      return (group(a) - group(b)) || (firstRatio(b) - firstRatio(a)) || codePointCompare(a.id, b.id);
    });
    var basis = '';
    loadServiceClasses().some(function (band) {
      if (band.kind === 'class' && band.max_people_per_point === per) { basis = band.basis; return true; }
      return false;
    });
    return {
      level: level, budget_usd: budget, people_per_borehole: per, exact_max_items: limit,
      ground_grid: grid, method: method, items: items.length, candidates: ordered,
      boreholes: boreholes, areas: candidates.filter(function (c) { return c.chosen; }).length,
      cost_usd: spent, left_usd: left, people: people, attempts: attempts, bound: Math.floor(bound),
      marginal: marginal,
      mean_usd: figures.mean, dry_usd: figures.dry, cost_samples: figures.samples,
      cost_seed: figures.seed, depth_m: figures.depth,
      calibration: setName(inForce(cfg)), people_basis: basis, least_ratio: least,
      access_areas: candidates.filter(function (c) { return c.access_usd > 0.0; }).length,
      cheapest: cheapest,
    };
  }

  /** The choice in sentences, the basis apart: allocation_text.
   * @param {Rec} a what allocate returns
   * @returns {string[]} */
  function allocationText(a) {
    var out = [phrase('allocation.lead', { per: a.people_per_borehole })];
    if (a.cheapest === null) {
      out.push(phrase('allocation.headline_no_candidates'));
    } else if (!a.boreholes) {
      out.push(phrase('allocation.headline_none', { budget: costUsd(a.budget_usd),
        area: a.cheapest.id, cheapest: costUsd(Number(a.cheapest.cost_usd || 0.0)) }));
    } else {
      out.push(phrase('allocation.headline', { budget: costUsd(a.budget_usd), n: a.boreholes,
        areas: a.areas, people: costUsd(a.people), cost: costUsd(a.cost_usd),
        attempts: a.attempts, left: costUsd(a.left_usd) }));
    }
    if (a.items) {
      if (a.method === 'exact') {
        out.push(phrase('allocation.method_exact', { items: costUsd(a.items), n: a.items,
          limit: a.exact_max_items }));
      } else {
        var gap = a.bound - a.people;
        out.push(phrase('allocation.method_greedy', { items: costUsd(a.items),
          limit: a.exact_max_items }));
        if (gap > 0) {
          out.push(phrase('allocation.greedy_gap', { bound: costUsd(a.bound), gap: costUsd(gap),
            share: rangeShare(gap / a.bound) }));
        } else {
          out.push(phrase('allocation.greedy_best', { bound: costUsd(a.bound) }));
        }
      }
    }
    if (a.cheapest !== null) {
      var m = a.marginal;
      if (m === null) {
        out.push(phrase('allocation.marginal_none'));
      } else {
        out.push(phrase('allocation.marginal', { area: m.area, cost: costUsd(m.cost_usd),
          people: costUsd(m.people), per_person: costUsd(m.usd_per_person), more: costUsd(m.more_usd) }));
      }
    }
    out.push(phrase('allocation.coarse'));
    out.push(a.access_areas ? phrase('allocation.access_some', { n: a.access_areas })
      : phrase('allocation.access_none'));
    return out;
  }

  /** What the people, the ground and the cost of a borehole rest on:
   * allocation_basis_text.
   * @param {Rec} a what allocate returns
   * @returns {string[]} */
  function allocationBasisText(a) {
    var out = [];
    out.push(a.people_basis
      ? phrase('allocation.basis_people', { per: a.people_per_borehole, basis: a.people_basis })
      : phrase('allocation.basis_people_set', { per: a.people_per_borehole }));
    out.push(phrase('allocation.basis_ground', { grid: a.ground_grid, calibration: a.calibration }));
    out.push(phrase('allocation.basis_cost', { mean: costUsd(a.mean_usd), dry: costUsd(a.dry_usd),
      n: costUsd(a.cost_samples), seed: a.cost_seed, depth: a.depth_m }));
    return out;
  }

  /** The table's header: allocation_header.
   * @param {Rec} a what allocate returns
   * @returns {string[]} */
  function allocationHeader(a) {
    var cols = ['allocation.col_area'].concat(a.level === 'chiefdom' ? ['allocation.col_district'] : [], [
      'allocation.col_unserved', 'allocation.col_ground', 'allocation.col_odds', 'allocation.col_cost',
      'allocation.col_chosen', 'allocation.col_people', 'allocation.col_ratio', 'allocation.col_why']);
    return cols.map(function (c) { return phrase(c); });
  }

  function allocationGroundCell(cand) {
    var g = cand.ground;
    if (!g || g.bgs_code === null) return phrase('allocation.ground_none');
    var share = rangeShare(g.class_samples / g.samples);
    if (g.glg === null) return phrase('allocation.ground_cell_class', { code: g.bgs_code, share: share });
    return phrase('allocation.ground_cell', { code: g.bgs_code, glg: g.glg, share: share });
  }

  function allocationWhy(a, cand) {
    var per = a.people_per_borehole;
    if (cand.reason === 'unserved') {
      return phrase('allocation.why_unserved', { f: cand.functional_points, per: per });
    }
    if (cand.reason === 'odds') return phrase('allocation.why_odds');
    if (cand.reason === 'all') return phrase('allocation.why_all', { k: cand.chosen });
    if (cand.reason === 'part') {
      return phrase('allocation.why_part', { k: cand.chosen, n: cand.boreholes, left: costUsd(a.left_usd) });
    }
    if (cand.reason === 'value') {
      return phrase('allocation.why_value', {
        ratio: 1000.0 * allocationServed(cand.unserved, per, 1) / Number(cand.cost_usd || 1.0),
        least: Number(a.least_ratio || 0.0) });
    }
    return phrase('allocation.why_budget', { cost: costUsd(Number(cand.cost_usd || 0.0)),
      left: costUsd(a.left_usd) });
  }

  /** The table, one row for each area: allocation_rows.
   * @param {Rec} a what allocate returns
   * @returns {string[][]} */
  function allocationRows(a) {
    return a.candidates.map(function (/** @type {Rec} */ cand) {
      var eligible = allocationEligible(cand);
      return [cand.id].concat(a.level === 'chiefdom' ? [cand.district] : [], [
        costUsd(cand.unserved),
        allocationGroundCell(cand),
        cand.odds ? oddsShort(cand.odds) : '',
        cand.cost_usd !== null ? costUsd(cand.cost_usd) : '',
        eligible ? phrase('allocation.chosen_cell', { k: cand.chosen, n: cand.boreholes }) : '',
        costUsd(cand.people),
        eligible ? pyFixed(1000.0 * allocationServed(cand.unserved, a.people_per_borehole, 1) /
          cand.cost_usd, 1) : '',
        allocationWhy(a, cand),
      ]);
    });
  }

  function allocationCsvField(text) {
    return /[,"\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  /** The table as CSV, then a blank line and each sentence on a line of its
   * own: allocation_csv, byte for byte.
   * @param {Rec} a what allocate returns
   * @returns {string} */
  function allocationCsv(a) {
    var lines = [allocationHeader(a).map(allocationCsvField).join(',')];
    allocationRows(a).forEach(function (row) { lines.push(row.map(allocationCsvField).join(',')); });
    lines.push('');
    allocationText(a).concat(allocationBasisText(a)).forEach(function (t) {
      lines.push(allocationCsvField(t));
    });
    return lines.join('\n') + '\n';
  }

  Object.assign(C, {
    ALLOCATION_LEVELS: ALLOCATION_LEVELS, ALLOCATION_MAX_CELLS: ALLOCATION_MAX_CELLS,
    ringHolds: ringHolds, areaGround: areaGround, areaGrounds: areaGrounds, allocate: allocate,
    allocationText: allocationText, allocationBasisText: allocationBasisText,
    allocationHeader: allocationHeader, allocationRows: allocationRows,
    allocationCsv: allocationCsv,
  });
