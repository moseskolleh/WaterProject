
  /* ------------------------------------------------------- text geometry
   *
   * There is no way to measure text before it is in the document, and the
   * figures are built detached so they can be rasterised without ever being
   * shown. These two functions are the estimate everything else lays out
   * against: they are deliberately a little generous, because a label with a
   * few spare pixels reads fine and a label three pixels too wide is clipped.
   */
  function textWidth(text, size) {
    var s = String(text === null || text === undefined ? '' : text);
    var w = 0;
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      /* i/l/j/t/f/r and punctuation are narrow; capitals and m/w are wide */
      if ('iljt.,:;\'`|!'.indexOf(s[i]) >= 0) w += 0.30;
      else if ('fr()[]{}/\\ '.indexOf(s[i]) >= 0) w += 0.38;
      else if ('mwMW@'.indexOf(s[i]) >= 0) w += 0.90;
      else if (c >= 65 && c <= 90) w += 0.68;
      else w += 0.545;
    }
    return w * (size || 10);
  }

  /* Break `text` into lines no wider than `maxWidth`. Words longer than the
   * line are broken rather than allowed to run past the edge. */
  function wrapText(text, maxWidth, size) {
    var words = String(text === null || text === undefined ? '' : text)
      .split(/\s+/).filter(Boolean);
    var lines = [], line = '';
    function flush() { if (line) { lines.push(line); line = ''; } }
    words.forEach(function (word) {
      var candidate = line ? line + ' ' + word : word;
      if (textWidth(candidate, size) <= maxWidth) { line = candidate; return; }
      flush();
      while (textWidth(word, size) > maxWidth && word.length > 1) {
        var cut = word.length;
        while (cut > 1 && textWidth(word.slice(0, cut) + '-', size) > maxWidth) cut -= 1;
        lines.push(word.slice(0, cut) + '-');
        word = word.slice(cut);
      }
      line = word;
    });
    flush();
    return lines.length ? lines : [''];
  }

  /* One line, shortened with an ellipsis only when it genuinely will not fit.
   * Nothing in these figures truncates mid-word without saying so. */
  function ellipsise(text, maxWidth, size) {
    var s = String(text === null || text === undefined ? '' : text);
    if (textWidth(s, size) <= maxWidth) return s;
    var cut = s.length;
    while (cut > 1 && textWidth(s.slice(0, cut) + '…', size) > maxWidth) cut -= 1;
    return s.slice(0, cut).replace(/[\s,;:.-]+$/, '') + '…';
  }

  /* Place labels against their anchors without letting any two collide, and
   * without letting any escape the drawing. Labels are sorted by anchor,
   * pushed down until they clear the one above, then pulled back up from the
   * bottom so the last one stays inside `yMax`. Returns {y, entry} pairs in
   * anchor order. This is the same algorithm the matplotlib drawing uses, so
   * the browser figure and the report figure lay their callouts out alike. */
  function stackLabels(entries, minGap, yMin, yMax) {
    var placed = entries.slice().sort(function (a, b) { return a.anchor - b.anchor; })
      .map(function (entry) { return { y: entry.anchor, entry: entry }; });
    var level = yMin;
    placed.forEach(function (item) {
      item.y = Math.max(item.y, level);
      level = item.y + minGap;
    });
    var limit = yMax;
    for (var i = placed.length - 1; i >= 0; i--) {
      if (placed[i].y > limit) placed[i].y = limit;
      limit = placed[i].y - minGap;
    }
    return placed;
  }

  /* Black or white, whichever stays readable on `hex`. Used wherever a label
   * is written straight onto a fill whose colour comes from the data. */
  function readableInk(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(String(hex || '').trim());
    if (!m) return '#FFFFFF';
    var n = parseInt(m[1], 16);
    function lin(v) {
      var c = v / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }
    var L = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) +
      0.0722 * lin(n & 255);
    return (L + 0.05) / 0.05 > 1.05 / (L + 0.05) ? '#12191A' : '#FFFFFF';
  }
