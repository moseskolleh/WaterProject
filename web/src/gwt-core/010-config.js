
  /* ================================================================== config
   * groundwater/config.py. Every value is overridable per project, which is
   * what the Settings page edits. The defaults are not written out here:
   * they are src/groundwater/data/defaults.json, which config.py reads and
   * the build emits as GWT.data.defaults, so the two engines start from the
   * same numbers. Why each one is what it is stays beside its field in
   * config.py.
   *
   * They are not part of the engine digest either: the inversion cache key
   * carries the whole VES configuration an inversion ran with, so a changed
   * VES default is already a different key.
   */

  /* The defaults themselves, shared: read, never changed. */
  function configDefaults() {
    var defaults = (GWT.data || {}).defaults;
    if (!defaults) {
      throw new Error('gwt-data.js is not loaded, or is stale: it carries the ' +
        'configuration defaults (src/groundwater/data/defaults.json)');
    }
    return defaults;
  }

  /* A copy of the defaults to change. */
  function defaultConfig() {
    return JSON.parse(JSON.stringify(configDefaults()));
  }

  /** Merge a partial override over the defaults, section by section.
   * @param {Rec|null} [overrides] a partial configuration, section by section
   * @returns {Config}
   */
  function withConfig(overrides) {
    var cfg = defaultConfig();
    if (!overrides) return cfg;
    ['style', 'ves', 'pumping', 'design', 'ves_range', 'odds', 'ledger', 'cost_range',
      'allocation', 'terrain', 'service', 'survival']
      .forEach(function (section) {
      var over = overrides[section];
      if (!over) return;
      Object.keys(over).forEach(function (key) {
        if (key in cfg[section] && over[key] !== null && over[key] !== undefined) {
          /* a table (the suitability weights) is copied, so the overrides
           * stay the caller's own */
          cfg[section][key] = isRecord(over[key]) ? Object.assign({}, over[key]) : over[key];
        }
      });
    });
    /* the calibration set in force, refused unless a named person adopted
     * it (calibration_sets.apply_set) */
    if (overrides.calibration) return applySet(cfg, overrides.calibration);
    return cfg;
  }
