
  /* ---------------------------------------------------------- colour ramps */

  /* matplotlib's colour ramps, as the anchors they are interpolated from.
   *
   * The Python names a colormap per figure and the browser has to arrive at
   * the same picture: a depth-to-bedrock map whose deep ground is pale beside
   * a matplotlib one whose deep ground is dark are two different findings to
   * anybody holding both reports. These are not theme colours and must not
   * come from palette() - they are the data scale itself, the thing the
   * colour bar is drawn from - which is why they are written out here the way
   * PROTECTIVE_CLASSES and GEOLOGY_COLOURS are.
   *
   * YlOrBr and GnBu are ColorBrewer's nine-colour ramps and these are their
   * exact anchors; terrain is matplotlib's own piecewise definition, kinks
   * and all; viridis is a 256-entry table sampled at seventeen points, which
   * holds it to under 5 of 255 on any channel. */
  var COLOUR_RAMPS = {
    viridis: {
      colours: ['#440154', '#48186A', '#472D7B', '#424086', '#3B528B',
        '#33638D', '#2C728E', '#26828E', '#21918C', '#1FA088', '#28AE80',
        '#3FBC73', '#5EC962', '#84D44B', '#ADDC30', '#D8E219', '#FDE725'],
    },
    YlOrBr: {
      colours: ['#FFFFE5', '#FFF7BC', '#FEE390', '#FEC34F', '#FE9829',
        '#EB6F14', '#CB4B02', '#983404', '#662506'],
    },
    GnBu: {
      colours: ['#F7FCF0', '#E0F3DB', '#CCEBC5', '#A7DDB5', '#7ACCC4',
        '#4DB2D3', '#2A8BBE', '#0867AB', '#084081'],
    },
    terrain: {
      colours: ['#333399', '#0099FF', '#00CC66', '#FFFF99', '#805C54', '#FFFFFF'],
      positions: [0, 0.15, 0.25, 0.5, 0.75, 1],
    },
    /* ColorBrewer's eleven-colour RdYlGn, which is matplotlib's own anchor
     * table for it. The suitability map is read as a traffic light - red is
     * a poor drilling target and green is a good one - so a browser ramp
     * that merely looked similar would put a peg the report calls moderate
     * in the green the reader takes for good. */
    RdYlGn: {
      colours: ['#A50026', '#D73027', '#F46D43', '#FDAE61', '#FEE08B',
        '#FFFFBF', '#D9EF8B', '#A6D96A', '#66BD63', '#1A9850', '#006837'],
    },
    /* terrain.py _land_cmap: terrain with its bathymetry cut off, so that
     * the coastal plain is not drawn as a lagoon. The Python builds it from
     * 256 colours of terrain taken from 0.25 to 1.0, so it is a slice of
     * terrain's own table rather than a ramp of its own, and rampColour
     * takes it the way matplotlib does: this ramp's entry first, then the
     * entry of terrain's table that entry was copied from. */
    terrain_land: { of: 'terrain', from: 0.25, to: 1.0 },
    /* ColorBrewer's eleven-colour BrBG, matplotlib's anchors. The curvature
     * maps draw it reversed, as BrBG_r: brown where the ground is convex or
     * spreads water, blue-green where it is concave or gathers it. */
    BrBG: {
      colours: ['#543005', '#8C510A', '#BF812D', '#DFC27D', '#F6E8C3',
        '#F5F5F5', '#C7EAE5', '#80CDC1', '#35978F', '#01665E', '#003C30'],
    },
    /* matplotlib's gray, for hillshade: entry i is grey level i */
    gray: { colours: ['#000000', '#FFFFFF'] },
  };

  function hexChannels(hex) {
    var m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(String(hex || '').trim());
    if (!m) return [0, 0, 0];
    return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
  }

  function mixHex(a, b, f) {
    var ca = hexChannels(a), cb = hexChannels(b), out = '#', i, v;
    for (i = 0; i < 3; i += 1) {
      v = Math.round(ca[i] + (cb[i] - ca[i]) * f);
      v = Math.max(0, Math.min(255, v));
      out += (v < 16 ? '0' : '') + v.toString(16).toUpperCase();
    }
    return out;
  }

  /* The ramp `name` at position `t`, clamped to its ends the way matplotlib
   * clamps a Normalize: a value under vmin takes the first colour on the bar
   * rather than dropping out of the figure. A name ending in _r is the ramp
   * reversed, as matplotlib names it. */
  function rampColour(name, t) {
    var reversed = !COLOUR_RAMPS[name] && /_r$/.test(name) && !!COLOUR_RAMPS[name.slice(0, -2)];
    var ramp = COLOUR_RAMPS[reversed ? name.slice(0, -2) : name] || COLOUR_RAMPS.viridis;
    var i;
    var x = (typeof t === 'number' && isFinite(t)) ? Math.max(0, Math.min(1, t)) : 0;
    /* matplotlib does not interpolate its ramps continuously: it builds a
     * 256-entry lookup table and picks entry min(floor(t * 256), 255), which
     * stands for position i/255. Skipping that step put the browser up to 5
     * of 255 off matplotlib on the steep leg of the terrain ramp, where a
     * bedrock elevation map changes from blue to green; mirroring it holds
     * every banded ramp here to one part in 255 of the Python's. A reversed
     * ramp's entry i is entry 255 - i of the ramp, not the ramp at 1 - t,
     * which lands one entry off wherever t * 256 is whole. */
    var entry = Math.min(Math.floor(x * 256), 255);
    if (reversed) entry = 255 - entry;
    if (ramp.of) {
      /* np.linspace(from, to, 256)[entry] as numpy works it out (entry *
       * step + from, with the last point set to `to`), then the entry of
       * the base ramp's table matplotlib picks for that value */
      var step = (ramp.to - ramp.from) / 255;
      var v = entry === 255 ? ramp.to : entry * step + ramp.from;
      entry = Math.min(Math.floor(v * 256), 255);
      ramp = COLOUR_RAMPS[ramp.of];
    }
    var cols = ramp.colours, n = cols.length;
    x = entry / 255;
    var pos = ramp.positions;
    if (!pos) {
      pos = [];
      for (i = 0; i < n; i += 1) pos.push(i / (n - 1));
    }
    for (i = 0; i < n - 1; i += 1) {
      if (x <= pos[i + 1] || i === n - 2) {
        var width = pos[i + 1] - pos[i];
        return mixHex(cols[i], cols[i + 1], width > 0 ? (x - pos[i]) / width : 0);
      }
    }
    return cols[n - 1];
  }

  /* ves/plots.py _rho_norm, applied: where one layer resistivity sits on the
   * log scale spanning the decades the drawn models occupy. The Python clamps
   * at the bottom of the scale - norm(max(rho, norm.vmin)) - so a layer under
   * the scale takes the darkest colour on the bar instead of a blank column. */
  function rhoRampColour(range, rho) {
    var lo = range[0], hi = range[1];
    var span = Math.log(hi) - Math.log(lo);
    var v = Math.max(Number(rho), lo);
    return rampColour('viridis', span > 0 ? (Math.log(v) - Math.log(lo)) / span : 0);
  }

  /* The white rule matplotlib draws along a layer boundary, along a contour
   * and around a reading. It is ink on a data-coloured fill rather than ink
   * on the page, so it is not a theme token: a token that followed the theme
   * would vanish into the dark end of the viridis ramp the moment the reader
   * switched to the dark theme, which is exactly where the boundary between a
   * 4 ohm-m clay and a 9 ohm-m clay has to stay visible. */
  var ON_RAMP_INK = '#FFFFFF';
