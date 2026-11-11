
  /* ------------------------------------------------------------ palette */

  /* A figure bound for a .docx is painted for paper, not for the screen it
   * was built on.
   *
   * Every chart takes its colours from the live CSS tokens at the moment it
   * is constructed, and the app's default theme is dark, so a client opening
   * a report got maps, sections and borehole drawings rasterised white on
   * black. The fallbacks below are the stylesheet's own light values, so a
   * chart built while this flag is set is a chart built for print, whatever
   * the reader of the app is looking at. Set it around the figure building,
   * not around the rasterising: the colours are already in the SVG by then.
   *
   * It is a count, not a switch. Each build turns it on and off again in its
   * own `finally`, and builds overlap - two report cards clicked one after
   * the other run at once - so a switch was turned off by whichever build
   * finished first while the other was still drawing, and that one's
   * remaining figures went into its document on the dark ground. The print
   * palette holds until the last build that asked for it is done. */
  var printDepth = 0;

  function usePrintPalette(on) {
    printDepth = on ? printDepth + 1 : Math.max(0, printDepth - 1);
  }

  function token(name, fallback) {
    if (printDepth > 0) return fallback;
    if (typeof getComputedStyle === 'undefined') return fallback;
    var value = getComputedStyle(document.documentElement)
      .getPropertyValue('--' + name);
    return (value || '').trim() || fallback;
  }

  /* The palette a map of boundaries is drawn with.
   *
   * Such a map is read against paper: its land, its sea and its unit
   * colours are light fills, the same on screen as in the report, and they
   * do not change with the theme. Drawn with the dark theme's ink and
   * surface round them, it was a light slab cut into a dark card, with its
   * place names in pale ink and a dark halo on a pale ground. So in the
   * dark theme the whole map is painted as the report paints it, with the
   * print palette, and the page lays it on the card as a sheet of paper
   * (svg.sheet-paper in gwt.css). In the light theme, and in a report, it
   * is the palette every other figure has. */
  function paperPalette() {
    var live = palette();
    if (printDepth > 0 || !(relativeLuminance(live.surface) < 0.5)) return live;
    printDepth += 1;
    try {
      return palette();
    } finally {
      printDepth -= 1;
    }
  }

  var CAT_FALLBACK = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100',
    '#e87ba4', '#008300', '#4a3aa7', '#e34948'];
  var SEQ_FALLBACK = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5',
    '#256abf', '#184f95', '#0d366b'];

  function palette() {
    return {
      surface: token('viz-surface', '#FFFFFF'),
      grid: token('viz-grid', '#e1e0d9'),
      axis: token('viz-axis', '#c3c2b7'),
      muted: token('viz-muted', '#898781'),
      ink: token('ink', '#152220'),
      inkSoft: token('ink-soft', '#4A5B56'),
      accent: token('accent', '#155D92'),
      accentSoft: token('accent-soft', '#86b6ef'),
      secondary: token('secondary', '#C15A2A'),
      neutral: token('neutral', '#4D4D4D'),
      /* The fallbacks are the stylesheet's own values, one per slot. A single
       * fallback for the whole family collapsed every series to one colour
       * anywhere the tokens could not be read - which is exactly where a
       * figure is rasterised for a report. */
      cat: CAT_FALLBACK.map(function (fallback, i) {
        return token('cat-' + (i + 1), fallback);
      }),
      seq: SEQ_FALLBACK.map(function (fallback, i) {
        return token('seq-' + (i + 1), fallback);
      }),
      good: token('status-good', '#0ca30c'),
      warning: token('status-warning', '#fab219'),
      serious: token('status-serious', '#ec835a'),
      critical: token('status-critical', '#d03b3b'),
    };
  }
