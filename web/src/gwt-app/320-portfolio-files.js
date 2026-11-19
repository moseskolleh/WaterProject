
  /* --- portfolio ------------------------------------------------------------ */

  /* A saved project, whichever of the two applications wrote it.
   *
   * The browser app saves JSON and the Streamlit app saves YAML, but both
   * carry the same headline ``summary`` block, so a programme can pool files
   * from both. An older file without a summary falls back to its site inputs,
   * which is all the map and the status column need. */
  function summaryFromProjectFile(name, text) {
    return projectFileEntry(name, text).summary;
  }

  /* A saved project file's summary, its ledger of predictions and
   * outcomes (PLAN.md step 5.1) and its works record (step 6.3, null where
   * it carries none), from either app's file. */
  function projectFileEntry(name, text) {
    var payload;
    if (/\.ya?ml$/i.test(name)) {
      payload = S.parseYaml(text);
    } else {
      payload = JSON.parse(text);
    }
    if (!payload || typeof payload !== 'object') throw new Error('not a project file');
    return { summary: summaryFromPayload(payload),
      ledger: C.cleanLedger(C.migratePayload(payload).ledger), works: C.cleanWorks(payload.works) };
  }

  function summaryFromPayload(payload) {
    var summary = payload.summary;
    if (summary && typeof summary === 'object' && Object.keys(summary).length) {
      return summary;
    }
    var state = payload.state;
    if (!state || typeof state !== 'object') throw new Error('not a project file');
    if (state.site) {                                   /* browser project file */
      return {
        community: state.site.community, district: state.site.district,
        chiefdom: state.site.chiefdom, easting: state.site.easting,
        northing: state.site.northing, utm_zone: state.site.utm_zone,
      };
    }
    return {                                          /* Streamlit project file */
      community: state.meta_community, district: state.meta_district,
      chiefdom: state.meta_chiefdom, easting: state.meta_easting,
      northing: state.meta_northing,
      utm_zone: Number(String(state.meta_zone || '29N').replace(/N$/i, '')) || 29,
    };
  }
