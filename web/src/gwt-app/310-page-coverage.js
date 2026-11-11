
  /* --- coverage gap --------------------------------------------------------- */

  var COVERAGE_LIMIT = 200000;

  PAGES.coverage = function () {
    var level = store.get('coverage.level', 'district');
    var points = derived.waterPoints || [];
    var nodes = [
      pageHead('Coverage gap', 'Where the next borehole does the most good: ' +
        'population per functional water point, by district or by chiefdom, ' +
        'joining the 2015 census with the water point inventory.'),
      card('Resolution', [
        el('div.chips', [
          el('button.chip' + (level === 'district' ? '.active' : ''), {
            type: 'button', onclick: function () { store.set('coverage.level', 'district'); render(); },
          }, 'District'),
          el('button.chip' + (level === 'chiefdom' ? '.active' : ''), {
            type: 'button', onclick: function () { store.set('coverage.level', 'chiefdom'); render(); },
          }, 'Chiefdom'),
        ]),
        waterPointSourceNote() || el('p.muted',
          'Coverage needs a national or regional water point inventory. Fetch ' +
          'one from WPdx+, or upload a CSV export on the Water points page.'),
        el('div.btn-row', [
          button('Fetch national water points', function (event) {
            /* a bounding box around the country's centre; the cap is high
             * because a national pull - plus the box's Guinea and Liberia
             * fringe, which the chiefdom join discards - is tens of thousands
             * of points */
            lookUpWaterPoints(event.target, {
              lat: 8.46, lon: -11.79, radiusM: 300000.0, limit: COVERAGE_LIMIT,
              clip: false,
              label: 'live WPdx+, national',
            });
          }),
          button('Water points page', function () { goto('waterpoints'); },
            { variant: 'ghost' }),
          points.length ? button('Clear', function () {
            derived.waterPoints = null; derived.waterPointsSource = null;
            derived.waterPointsCapped = false; derived.waterPointsRadius = null;
            derived.waterPointsCentre = null; derived.waterPointsSkipped = null; render();
          }, { variant: 'ghost' }) : null,
        ]),
        derived.waterPointsCapped ? el('div.callout.callout-warn', el('p',
          'The national pull hit the ' + S.thousands(COVERAGE_LIMIT) +
          '-row cap, so the ranking may be partial. Prefer a filtered WPdx CSV ' +
          'export for a complete, reproducible analysis.')) : null,
      ]),
    ];
    if (!points.length) return nodes;

    var polys = polygons();
    var chiefdomDistrict = C.loadChiefdomDistrict();
    var rows, features, valueFor, nameFor, title;

    /* One page, one population. The map and the ranking below used the 2015
     * census while the planning view a card further down projected it forward,
     * so the same chiefdom appeared twice on one screen with two different
     * numbers of people in it and nothing saying which was which. The census
     * is a decade old; the figure anybody quotes should be for the year they
     * are planning in, and it should say so. The rate is uniform, so this
     * moves the magnitudes rather than the ranking - which is exactly why the
     * unlabelled version was so easy to read straight past. */
    var coverageYear = Math.max(
      store.get('coverage.year', new Date().getFullYear()), C.CENSUS_YEAR);
    var coverageRate = store.get('coverage.rate',
      Math.round(C.DEFAULT_GROWTH_RATE * 10000) / 100) / 100;

    var areaPopulation, censusPopulation, grouped, unplaced;
    if (level === 'district') {
      var counted = C.countPointsByDistrict(points, polys, chiefdomDistrict);
      censusPopulation = C.loadDistrictPopulation();
      var districtProjection = C.projectPopulation(
        censusPopulation, coverageYear, { rate: coverageRate });
      areaPopulation = districtProjection.projected;
      var projection = districtProjection.projection;
      grouped = C.groupPointsByDistrict(points, polys, chiefdomDistrict).grouped;
      rows = C.coverageRows(areaPopulation, counted.counts);
      unplaced = counted.unassigned;
      var byDistrict = {};
      rows.forEach(function (r) { byDistrict[r.name] = r.people_per_point; });
      features = (mapLayers().chiefdomBoundaries || {}).features || [];
      /* null is an area nothing is known about; Infinity is a mapped area with
       * no functional source in it, which is the worst case rather than a
       * missing one. They were both null, so the areas most in need were the
       * same grey as the areas nobody has a figure for. */
      valueFor = function (feature) {
        var name = (feature.properties || {}).name;
        var district = chiefdomDistrict[name];
        if (!(district in byDistrict)) return null;
        var v = byDistrict[district];
        return v === null || v === undefined ? Infinity : v;
      };
      nameFor = function (feature) { return (feature.properties || {}).name; };
      title = 'People per functional water point, by district (' +
        coverageYear + ')';
    } else {
      var pop = C.chiefdomPopulation();
      var counts = C.countPointsByChiefdom(points, polys);
      censusPopulation = pop.population;
      var chiefdomProjection = C.projectPopulation(
        censusPopulation, coverageYear, { rate: coverageRate });
      areaPopulation = chiefdomProjection.projected;
      projection = chiefdomProjection.projection;
      grouped = C.groupPointsByChiefdom(points, polys).grouped;
      rows = C.chiefdomCoverageRows(areaPopulation, counts.counts, chiefdomDistrict);
      unplaced = counts.unassigned;
      var byChiefdom = {};
      rows.forEach(function (r) { byChiefdom[r.name] = r.people_per_point; });
      features = (mapLayers().chiefdomBoundaries || {}).features || [];
      valueFor = function (feature) {
        var name = (feature.properties || {}).name;
        if (!(name in byChiefdom)) return null;
        var v = byChiefdom[name];
        return v === null || v === undefined ? Infinity : v;
      };
      nameFor = function (feature) { return (feature.properties || {}).name; };
      title = 'People per functional water point, by chiefdom (' +
        coverageYear + ')';
    }

    var stats = C.coverageStats(rows);
    nodes.push(card('Headline', [
      S.statRow([
        S.stat('Areas', String(stats.n_areas)),
        S.stat('With no functional source', String(stats.n_no_source),
          'ranked worst by definition'),
        S.stat('Worst measurable', stats.worst_served_people_per_point
          ? S.thousands(Math.round(stats.worst_served_people_per_point)) : '—',
          stats.worst_served_area || ''),
        S.stat('National average', stats.national_people_per_point
          ? S.thousands(Math.round(stats.national_people_per_point)) : '—',
          'people per functional point'),
      ]),
      charts.figure(charts.choropleth({
        features: features, value: valueFor, name: nameFor,
        title: title, legendTitle: 'people per functional water point',
        classes: C.loadServiceClasses(),
        outline: nationalOutline(mapLayers()),
        width: 640, height: 600,
      }), title, { filename: 'coverage_' + level }),
      el('p.muted', projection.note),
      el('p.muted', C.POPULATION_CREDIT + ' ' + C.WPDX_CREDIT),
    ]));

    /* the census figures, not the projected ones: planningCard projects them
     * itself from the same year and rate, and projecting twice would compound */
    nodes.push(planningCard(censusPopulation, grouped, level));

    var rankedColumns = [
      { key: 'rank', label: 'Rank', align: 'right' },
      { key: 'name', label: level === 'district' ? 'District' : 'Chiefdom' },
      level === 'chiefdom' ? { key: 'district', label: 'District' } : null,
      { key: 'population', label: 'Population ' + coverageYear, align: 'right',
        format: function (v) { return S.thousands(Math.round(v)); } },
      { key: 'water_points', label: 'Mapped points', align: 'right' },
      { key: 'functional_points', label: 'Functional', align: 'right' },
      { key: 'people_per_point', label: 'People per point', align: 'right',
        format: function (v) {
          return v === null ? 'no functional source' : S.thousands(Math.round(v));
        } },
    ].filter(Boolean);

    nodes.push(card('Ranked need', [
      S.table(rankedColumns, rows.slice(0, TABLE_ROWS_SHOWN), {
        rowClass: function (row) {
          return row.functional_points === 0 ? 'row-bad'
            : (row.rank <= 5 ? 'row-warn' : '');
        },
      }),
      tableTail(rows, rankedColumns, 'coverage_' + level + '.csv'),
      /* A point that lands inside no chiefdom is left out of every area's
       * ratio, so the ranking above is computed as though it were not there,
       * and the areas it belonged to rank worse than the data supports.
       * Border and offshore points have always done this and the boundary
       * review now holds geometry back on purpose, which makes more of them.
       * The Streamlit app has always said how many went; this page ranked the
       * country without them and said nothing, so the same inventory read as
       * more complete here than it was. */
      unplaced && unplaced.length ? el('p.muted',
        S.thousands(unplaced.length) + ' water ' +
        S.plural(unplaced.length, 'point') + ' fell outside every chiefdom ' +
        'polygon (border, offshore, or geometry held back by the boundary ' +
        'review) and ' + (unplaced.length === 1 ? 'was' : 'were') +
        ' not counted in any area above.') : null,
    ].filter(Boolean)));
    nodes.push(allocationCard(rows, level));
    return nodes;
  };

  /* Where to drill next, within a budget (PLAN.md step 6.1). The boreholes
   * are priced as the Costing page prices its borehole, sampled once more
   * with the depth held at the estimate's and no dry hole drawn: the range
   * of models and the odds at the survey's first-ranked point belong to one
   * site, and the allocation gives every area its own odds. Kept with the
   * estimate it belongs to, so a page drawn again does not sample it again. */
  var allocationCostHeld = new WeakMap();

  function allocationCost() {
    var estimate = derived.estimate;
    if (!estimate || !derived.costInputs) return null;
    var cfg = config();
    var settings = cfg.cost_range.seed + '|' + cfg.cost_range.samples;
    var held = allocationCostHeld.get(estimate);
    if (held && held.settings === settings) return held.cost;
    var cost = C.sampleCost(derived.costInputs, derived.costRates,
      Object.assign({}, costingOptions(), { config: cfg }));
    allocationCostHeld.set(estimate, { settings: settings, cost: cost });
    return cost;
  }

  /* The areas of the ranking above, at the population of the year planned
   * for, chosen between for the budget typed. The budget and the access
   * costs are kept with the year and the growth rate. */
  function allocationCard(rows, level) {
    var heading = C.phrase('allocation.heading');
    var cost = allocationCost();
    if (!cost) {
      return card(heading, [
        el('p', C.phrase('allocation.no_estimate')),
        el('div.btn-row', button('Costing & BoQ', function () { goto('costing'); },
          { variant: 'ghost' })),
      ]);
    }
    var budget = store.get('coverage.budget', null);
    var accessKey = 'coverage.access_' + level;
    var access = store.get(accessKey, {}) || {};
    var nodes = [
      el('div.field-row', [
        field(C.phrase('allocation.col_budget'), S.numberInput(budget, function (v) {
          store.set('coverage.budget', v === null || v === undefined ? null : Number(v));
          render();
        }, { min: 0, step: 10000 })),
      ]),
    ];
    if (!(typeof budget === 'number' && budget > 0)) {
      nodes.push(el('p.muted', C.phrase('allocation.no_budget')));
      return card(heading, nodes);
    }
    var chosen;
    try {
      chosen = C.allocate(rows, budget, cost, { level: level, access: access, config: config() });
    } catch (e) {
      nodes.push(el('div.callout.callout-bad', el('p', String(e && e.message || e))));
      return card(heading, nodes);
    }
    var text = C.allocationText(chosen);
    nodes.push(el('p.muted', text[0]));
    nodes.push(el('div.callout', el('p', text[1])));
    text.slice(2).forEach(function (line) { nodes.push(el('p', line)); });
    var header = C.allocationHeader(chosen);
    var table = C.allocationRows(chosen).map(function (cells, i) {
      return { cells: cells, id: chosen.candidates[i].id, chosen: chosen.candidates[i].chosen };
    });
    var columns = header.map(function (label, k) {
      return { key: function (row) { return row.cells[k]; }, label: label };
    });
    /* an access cost per area, per attempt; blank, the default, is none */
    columns.push({ label: C.phrase('allocation.col_access'), key: function (row) {
      return S.numberInput(Object.prototype.hasOwnProperty.call(access, row.id) ? access[row.id] : null,
        function (v) {
          var next = Object.assign({}, store.get(accessKey, {}) || {});
          if (v === null || v === undefined || !(Number(v) > 0)) delete next[row.id];
          else next[row.id] = Number(v);
          store.set(accessKey, next);
          render();
        }, { min: 0, step: 100 });
    } });
    nodes.push(S.table(columns, table.slice(0, TABLE_ROWS_SHOWN), {
      rowClass: function (row) { return row.chosen ? 'row-ok' : ''; },
    }));
    C.allocationBasisText(chosen).forEach(function (line) { nodes.push(el('p.muted', line)); });
    var hidden = table.length - Math.min(table.length, TABLE_ROWS_SHOWN);
    nodes.push(el('div.btn-row', [
      el('p.muted', hidden ? 'Showing ' + TABLE_ROWS_SHOWN + ' of ' + S.thousands(table.length) +
        '. The ' + S.thousands(hidden) + ' not shown come after these; download the table for all of them.'
        : 'Showing all ' + S.thousands(table.length) + '.'),
      button(C.phrase('allocation.download'), function () {
        S.download(C.phrase('allocation.csv_name'), C.allocationCsv(chosen), 'text/csv');
      }, { variant: 'ghost' }),
    ]));
    return card(heading, nodes);
  }

  /* A long table is cut short on screen so the page stays readable, which is
   * fine until nobody says so. This is the ranking that decides where to drill
   * next: 166 chiefdoms shown as 60 looks like the whole country, and the
   * areas that fall off the end are by definition the ones already doing
   * worst. Say how many are not shown, and hand over the whole set as a file
   * so the cut is a display choice rather than a limit on the answer. */
  var TABLE_ROWS_SHOWN = 60;

  function tableTail(rows, columns, filename) {
    if (!rows.length) return null;
    var hidden = rows.length - Math.min(rows.length, TABLE_ROWS_SHOWN);
    return el('div.btn-row', [
      hidden ? el('p.muted', 'Showing ' + TABLE_ROWS_SHOWN + ' of ' +
        S.thousands(rows.length) + '. The ' + S.thousands(hidden) +
        ' not shown rank below these; download the table for all of them.')
        : el('p.muted', 'Showing all ' + S.thousands(rows.length) + '.'),
      button('Download table (.csv)', function () {
        S.download(filename, S.toCsv(rows.map(function (row) {
          var out = {};
          columns.forEach(function (col) { out[col.label] = row[col.key]; });
          return out;
        }), columns.map(function (col) { return col.label; })), 'text/csv');
      }, { variant: 'ghost' }),
    ].filter(Boolean));
  }

  /* The census is a decade old and the survey behind each point is older
   * than it looks. Both halves of "people per functional point" are staler
   * than the phrase suggests, so both are made visible here rather than
   * folded into a figure that reads as current. */
  function planningCard(population, grouped, level) {
    var thisYear = new Date().getFullYear();
    var year = Math.max(store.get('coverage.year', thisYear), C.CENSUS_YEAR);
    var ratePercent = store.get('coverage.rate',
      Math.round(C.DEFAULT_GROWTH_RATE * 10000) / 100);
    var out = C.planningRows(population, grouped || {},
      { asOfYear: year, rate: ratePercent / 100 });
    var stats = C.planningStats(out.rows, out.projection);
    var unit = level === 'district' ? 'district' : 'chiefdom';

    var nodes = [
      el('div.field-row', [
        field('Plan for year', S.numberInput(year, function (v) {
          store.set('coverage.year', Math.max(Number(v) || thisYear,
            C.CENSUS_YEAR));
          render();
        }, { min: C.CENSUS_YEAR, max: 2050, step: 1 }),
        'A people-per-point figure without a year attached is a wrong ' +
        'number nobody notices'),
        field('Annual population growth (%)',
          S.numberInput(ratePercent, function (v) {
            store.set('coverage.rate', v === null || v === undefined
              ? Math.round(C.DEFAULT_GROWTH_RATE * 10000) / 100 : Number(v));
            render();
          }, { min: 0, max: 10, step: 0.1 }),
        'The default is the rate implied by the 2004 and 2015 census totals'),
      ]),
      el('p.muted', out.projection.note),
      S.statRow([
        S.stat('Population ' + year, S.thousands(Math.round(stats.population)),
          '+' + S.thousands(Math.round(stats.population -
            stats.census_population)) + ' since the census'),
        S.stat('People per point', stats.national_people_per_point
          ? S.thousands(Math.round(stats.national_people_per_point)) : '—',
        'over every functional point'),
        S.stat('...recent surveys only', stats.national_people_per_recent_point
          ? S.thousands(Math.round(stats.national_people_per_recent_point)) : '—',
        'the gap is the size of the assumption'),
      ]),
    ];
    if (stats.n_stale_areas) {
      nodes.push(el('div.callout.callout-warn', el('p',
        stats.n_stale_areas + ' ' + S.plural(stats.n_stale_areas, unit) +
        (stats.n_stale_areas === 1 ? ' rests' : ' rest') + ' on surveys more than ' +
        C.AGEING_YEARS + ' years old: ' +
        stats.stale_areas.slice(0, 8).join(', ') +
        (stats.n_stale_areas > 8 ? '…' : '') +
        (stats.n_stale_areas === 1
          ? '. Its coverage figures describe the year it was surveyed, not this one.'
          : '. Their coverage figures describe the year they were surveyed, ' +
            'not this one.'))));
    }
    if (!stats.n_seasonality_recorded) {
      nodes.push(el('div.callout', el('p', 'None of these ' +
        S.thousands(stats.n_seasonality_unknown) + ' functional points ' +
        'records how many months of the year it yields water, so dry-season ' +
        'service cannot be separated from wet-season service. Silence is not ' +
        'a year-round supply.')));
    } else {
      nodes.push(el('p.muted', S.thousands(stats.n_seasonality_recorded) +
        ' points record their seasonality and ' +
        S.thousands(stats.n_seasonality_unknown) + ' do not, so the ' +
        'dry-season columns below are a band between counting the ' +
        'unrecorded ones and not counting them.'));
    }
    var planningColumns = [
      { key: 'rank', label: 'Rank', align: 'right' },
      { key: 'name', label: level === 'district' ? 'District' : 'Chiefdom' },
      { key: 'population', label: 'Population ' + year, align: 'right',
        format: function (v) { return S.thousands(Math.round(v)); } },
      { key: 'functional_points', label: 'Functional', align: 'right' },
      { key: 'recent_functional_points', label: 'Surveyed lately',
        align: 'right' },
      { key: 'people_per_point', label: 'People per point', align: 'right',
        format: function (v) {
          return v === null ? 'no functional source' : S.thousands(Math.round(v));
        } },
      { key: 'people_per_recent_point', label: '…recent only', align: 'right',
        format: function (v) {
          return v === null ? '—' : S.thousands(Math.round(v));
        } },
      { key: 'freshness', label: 'Survey',
        format: function (v) { return v.label; } },
      { key: 'seasonal', label: 'Year-round / seasonal',
        format: function (v) {
          return v.n_year_round + ' / ' + v.n_seasonal +
            (v.n_unknown ? ' (' + v.n_unknown + ' unasked)' : '');
        } },
      { key: 'seasonal', label: 'Dry-season people / point', align: 'right',
        format: function (v) { return C.seasonalBandText(v); } },
    ];
    nodes.push(S.table(planningColumns, out.rows.slice(0, TABLE_ROWS_SHOWN), {
      rowClass: function (row) {
        return row.freshness.state === 'stale' ? 'row-warn' : '';
      },
    }));
    /* the freshness and seasonality columns are objects, so they are flattened
     * to the same words the table shows rather than exported as [object Object] */
    nodes.push(tableTail(out.rows.map(function (row) {
      return Object.assign({}, row, {
        freshness: row.freshness ? row.freshness.label : '',
        seasonal: row.seasonal ? C.seasonalBandText(row.seasonal) : '',
      });
    }), planningColumns.filter(function (col) {
      return col.label !== 'Year-round / seasonal';
    }), 'coverage_planning_' + level + '.csv'));
    return card('Planning view: how current is this?', nodes.filter(Boolean));
  }
