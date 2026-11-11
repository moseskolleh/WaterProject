
  /* ------------------------------------------------------------ choropleth */

  /* `spec.classes` is a fixed scale: [{kind, max_people_per_point, label,
   * colour}], the table the Python engine reads too. Without one the classes
   * were five quantiles recomputed from whatever was on this map, so the same
   * chiefdom changed colour between the district view and the chiefdom view
   * and neither key said what a colour meant. A map that cannot be compared
   * with another map of the same country is not much of a map. */
  function choropleth(spec) {
    var features = spec.features || [];
    var fixed = spec.classes && spec.classes.length ? spec.classes : null;
    var values = features.map(spec.value).filter(function (v) {
      return typeof v === 'number' && isFinite(v);
    });
    var breaks = spec.breaks || (fixed ? fixedBreaks(fixed)
      : quantileBreaks(values, 5));
    var pal = paperPalette();
    /* One colour per class, sampled across the whole ramp. Slicing a fixed
     * window off it gave fewer colours than classes as soon as the breaks
     * were supplied rather than computed, and the top classes then shared a
     * colour while the legend still listed them apart. */
    var classes = breaks.length + 1;
    var ramp = [];
    if (fixed) {
      ramp = fixed.filter(function (c) { return c.kind === 'class'; })
        .map(function (c) { return c.colour; });
    } else {
      for (var c = 0; c < classes; c++) {
        var t = classes === 1 ? 0.5 : c / (classes - 1);
        ramp.push(pal.seq[Math.round(t * (pal.seq.length - 1))]);
      }
    }
    var noSource = fixed ? classColour(fixed, 'no_source') : '#D8D4CB';
    var noData = fixed ? classColour(fixed, 'no_data') : '#D8D4CB';

    var legendItems = [];
    if (spec.legend !== false && breaks.length) {
      ramp.forEach(function (colour, i) {
        var band = fixed ? fixed.filter(function (c) {
          return c.kind === 'class';
        })[i] : null;
        var lo = i === 0 ? null : breaks[i - 1];
        var hi = i < breaks.length ? breaks[i] : null;
        legendItems.push({
          colour: colour,
          label: band ? band.label
            : (lo === null ? 'under ' + S.sig(hi, 3)
              : (hi === null ? S.sig(lo, 3) + ' and over'
                : S.sig(lo, 3) + ' to ' + S.sig(hi, 3))),
        });
      });
      /* An area with no functional source at all is the worst case, not a
       * missing one - it ranks first by definition. Both were the same grey,
       * so the areas most in need looked exactly like the areas nothing is
       * known about. */
      if (fixed && features.some(function (f) { return isNoSource(spec.value(f)); })) {
        legendItems.push({ colour: noSource, label: classLabel(fixed, 'no_source') });
      }
      if (features.some(function (f) { return isNoData(spec.value(f)); })) {
        legendItems.push({
          colour: noData,
          label: fixed ? classLabel(fixed, 'no_data') : 'no figure recorded',
        });
      }
    }

    var canvas = mapCanvas(spec, legendItems, features);
    /* plot_coverage_choropleth paints sea and neighbouring land before the
     * areas (regional.py:1170), as the portfolio map does. The browser's
     * coverage map drew the country on blank paper, so the Atlantic and a
     * country with no figures looked the same. */
    clipToFrame(canvas);
    seaAndNeighbours(canvas, spec.outline || [], MAP_LAND,
      foreignLandFeatures(canvas.project.visibleBox()));
    features.forEach(function (feature) {
      var v = spec.value(feature);
      var cls = classify(v, breaks);
      var fill;
      if (isNoData(v)) fill = noData;
      else if (isNoSource(v)) fill = noSource;
      else fill = ramp[Math.min(cls, ramp.length - 1)];
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        'fill-rule': 'evenodd',
        fill: fill,
        stroke: canvas.palette.surface, 'stroke-width': 0.8,
        'aria-label': (spec.name ? spec.name(feature) : '') +
          (v === null || v === undefined ? '' : ': ' + S.sig(v, 3)),
      }, [svgEl('title', {
        text: (spec.name ? spec.name(feature) : '') +
          (v === null || v === undefined ? '' : ': ' + S.sig(v, 3)),
      })]));
    });
    drawMapPoints(canvas, spec.points);
    return canvas.finish();
  }

  /* The two out-of-ramp cases, told apart the same way the Python engine tells
   * them apart: nothing known at all, versus a mapped area with no working
   * source in it. */
  function isNoData(v) {
    return v === null || v === undefined || typeof v !== 'number' || isNaN(v);
  }

  function isNoSource(v) {
    return typeof v === 'number' && !isNaN(v) && !isFinite(v);
  }

  function classColour(classes, kind) {
    var hit = classes.filter(function (c) { return c.kind === kind; })[0];
    return hit ? hit.colour : '#D8D4CB';
  }

  function classLabel(classes, kind) {
    var hit = classes.filter(function (c) { return c.kind === kind; })[0];
    return hit ? hit.label : kind;
  }

  function fixedBreaks(classes) {
    return classes.filter(function (c) {
      return c.kind === 'class' && c.max_people_per_point !== '' &&
        c.max_people_per_point !== null && c.max_people_per_point !== undefined;
    }).map(function (c) { return Number(c.max_people_per_point); });
  }

  function quantileBreaks(values, n) {
    var xs = values.slice().sort(function (a, b) { return a - b; });
    if (xs.length < n) return xs.slice(1);
    var out = [];
    for (var i = 1; i < n; i++) {
      out.push(xs[Math.floor(i * xs.length / n)]);
    }
    return out.filter(function (v, i, a) { return i === 0 || v !== a[i - 1]; });
  }

  function classify(value, breaks) {
    if (value === null || value === undefined || !isFinite(value)) return null;
    for (var i = 0; i < breaks.length; i++) {
      if (value < breaks[i]) return i;
    }
    return breaks.length;
  }
