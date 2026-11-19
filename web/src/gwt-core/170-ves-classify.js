
  /* =========================================================== curve type
   * groundwater/ves/classify.py
   */

  var TRIPLET = { '10': 'K', '01': 'H', '11': 'A', '00': 'Q' };

  /**
   * @param {LayeredModel} model
   * @returns {string}
   */
  function classifyCurve(model) {
    var rho = model.resistivities;
    if (rho.length < 2) return 'uniform';
    if (rho.length === 2) {
      return rho[1] > rho[0] ? '2-layer ascending' : '2-layer descending';
    }
    var letters = '';
    for (var i = 0; i < rho.length - 2; i++) {
      var up1 = rho[i + 1] > rho[i] ? '1' : '0';
      var up2 = rho[i + 2] > rho[i + 1] ? '1' : '0';
      letters += TRIPLET[up1 + up2];
    }
    return letters;
  }

  var CURVE_DESCRIPTIONS = {
    H: 'a conductive layer between two more resistive layers, the classical ' +
       'signature of a saturated weathered zone above fresh basement',
    K: 'a resistive layer between two more conductive layers, often dry ' +
       'laterite or duricrust over a conductive saprolite',
    A: 'resistivity increasing with depth, typical of progressively less ' +
       'weathered rock towards fresh basement',
    Q: 'resistivity decreasing with depth, typical of deepening weathering ' +
       'or increasing saturation with depth',
  };

  /**
   * @param {string} curveType
   * @returns {string}
   */
  function describeCurveType(curveType) {
    if (curveType.indexOf('2-layer') === 0) {
      if (curveType.indexOf('descending') >= 0) {
        return 'a two layer response with resistivity decreasing at depth, ' +
          'consistent with weathered or fractured, possibly water bearing ' +
          'rock beneath a resistive surface layer';
      }
      return 'a two layer response with resistivity increasing at depth, ' +
        'consistent with more competent rock beneath the surface layer';
    }
    var parts = ['type ' + curveType], seen = [];
    for (var i = 0; i < curveType.length; i++) {
      var letter = curveType.charAt(i);
      if (CURVE_DESCRIPTIONS[letter] && seen.indexOf(letter) < 0) {
        seen.push(letter);
        parts.push(CURVE_DESCRIPTIONS[letter]);
      }
    }
    return parts.join('; ');
  }
