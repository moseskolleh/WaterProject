
  /* ======================================================== electrode arrays
   * groundwater/ves/arrays.py. mn is always the FULL potential spacing MN,
   * matching the field sheets, not MN/2.
   */

  /**
   * @param {string} arrayType
   * @param {Record<string, number>} spacings ab2 and mn, a, or a and n
   * @returns {number}
   */
  function geometricFactor(arrayType, spacings) {
    var kind = String(arrayType || '').trim().toLowerCase();
    if (kind.indexOf('schlum') === 0) {
      var L = spacings.ab2, b = spacings.mn / 2.0;
      if (!(b > 0) || !(L > b)) {
        throw new Error('Require 0 < MN/2 < AB/2 for Schlumberger');
      }
      return Math.PI * (L * L - b * b) / (2.0 * b);
    }
    if (kind.indexOf('wenner') === 0) return 2.0 * Math.PI * spacings.a;
    if (kind.indexOf('dipole') === 0) {
      var n = spacings.n;
      return Math.PI * n * (n + 1) * (n + 2) * spacings.a;
    }
    if (kind.indexOf('pole-pole') === 0 || kind.indexOf('pole pole') === 0) {
      return 2.0 * Math.PI * spacings.a;
    }
    throw new Error('Unknown array type: ' + arrayType);
  }

  /**
   * @param {string} arrayType
   * @param {number} resistanceOhm
   * @param {Record<string, number>} spacings
   * @returns {number}
   */
  function apparentResistivity(arrayType, resistanceOhm, spacings) {
    return geometricFactor(arrayType, spacings) * resistanceOhm;
  }
