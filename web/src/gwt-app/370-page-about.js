
  /* --- about ---------------------------------------------------------------- */

  PAGES.about = function () {
    return [
      pageHead('About & method', 'What this app computes, what it assumes, and ' +
        'where the numbers come from.'),
      card('What it is', [
        /* the release a bug report or a finding should name; written into the
         * bundle from pyproject.toml, so it is the same number the Python
         * package and the Streamlit app report */
        el('p.about-version', 'Version ' + (GWT.data.version || 'not recorded') +
          ' of the Groundwater Investigation Toolkit.'),
        el('p', 'A standalone version of the Groundwater Investigation Toolkit ' +
          'for rural water supply boreholes in Sierra Leone. It covers the whole ' +
          'project lifecycle — geophysical siting, borehole design, drilling ' +
          'records, pumping tests, water quality, costing, supervision and ' +
          'handover — and produces client-ready Word reports.'),
        el('p', 'Everything runs in this browser. Uploaded field sheets are ' +
          'read in the page, the analyses run in the browser, and the reports ' +
          'are assembled in the page. No data is sent to any server, which is ' +
          'what makes it usable on a field laptop with an intermittent ' +
          'connection.'),
        el('p', 'The long computations - the VES inversion and the pumping test ' +
          'fits - run in a background thread of the browser (a Web Worker), so ' +
          'the page stays usable while they work, shows how far they have got, ' +
          'and can stop them. Opened as a file rather than from a web address, ' +
          'the app cannot start that thread; it does the same work on the page ' +
          'itself, with the same results, and the page is busy while each ' +
          'sounding is inverted.'),
        el('p', 'Two features are the exception, and both are a button you ' +
          'press rather than something the page does on its own: looking up ' +
          'existing water points asks the Water Point Data Exchange, and the ' +
          'AI-assisted reading of a photographed field sheet sends that sheet ' +
          'to Anthropic under a key you supply. Everything else works with the ' +
          'network cable pulled out, including the CSV path for water points.'),
      ]),
      card('Methods', [
        el('h4', 'Geophysics'),
        el('p', 'Apparent resistivity comes from the measured resistance and the ' +
          'array geometric factor. The layered-earth forward model evaluates the ' +
          'Hankel transform of the Koefoed resistivity transform by direct ' +
          'Gauss-Legendre quadrature — no tabulated filter coefficients — and the ' +
          'inversion is damped least squares on the logarithms of resistivity and ' +
          'thickness. The reported fit error matches the IPI2Win ERR quantity.'),
        el('h4', 'Hydraulics'),
        el('p', 'Cooper-Jacob on the late-time straight line with the u < 0.05 ' +
          'validity check, a Theis type-curve fit, Theis recovery on residual ' +
          'drawdown, and Hantush-Bierschenk for step tests. The safe yield ' +
          'projects drawdown to the design period and applies the stated safety ' +
          'factor; it is reported as a range across the assumptions it rests on, ' +
          'because storativity and the effective well radius are not resolvable ' +
          'from a single pumped well.'),
        el('h4', 'Water quality'),
        el('p', 'Results are compared against WHO guideline values and the ' +
          'national standard, with the combined nitrate and nitrite rule applied. ' +
          'The charge balance checks the analysis itself. Corrosivity uses the ' +
          'Langelier, Ryznar, Aggressive and Larson-Skold indices and produces a ' +
          'rising-main materials recommendation.'),
        el('h4', 'Costing'),
        el('p', 'The RWSN Borehole Costing Model: line items by stage and by ' +
          "resource category, the contractor's cost separated from the client's " +
          'price, and a programme estimate that lets the successful boreholes ' +
          'carry the expected dry attempts.'),
      ]),
      card('Data sources', [
        el('ul', [
          el('li', 'WHO Guidelines for Drinking-water Quality, 4th edition with addenda.'),
          el('li', 'RWSN/Skat Cost-Effective Boreholes, and "Costing and Pricing: ' +
            'a Guide for Water Well Drilling Enterprises".'),
          el('li', 'RWSN/UNICEF "Supervising Water Well Drilling" and ' +
            '"Professional Water Well Drilling".'),
          el('li', 'geoBoundaries administrative boundaries (CC BY 4.0).'),
          el('li', 'BGS Africa Groundwater Atlas hydrogeology of Sierra Leone (CC BY-SA 4.0).'),
          el('li', 'USGS Geologic Map of Africa.'),
          el('li', '2015 Population and Housing Census, Statistics Sierra Leone.'),
          el('li', 'Water Point Data Exchange (WPdx+), CC BY 4.0 — user supplied.'),
        ]),
        el('p.muted', 'The guideline table, the rate catalogue, the checklists ' +
          'and the separation distances are editable data files in the ' +
          'repository, so field practice can be adapted without code changes.'),
      ]),
      card('Limitations', [
        el('ul', [
          el('li', 'Resistivity models are not unique: different layer ' +
            'combinations can fit one curve almost equally well, and the depth of ' +
            'investigation is limited by the maximum electrode spacing. Only ' +
            'drilling confirms the section.'),
          el('li', 'Storativity from a single pumped well is an assumption, not ' +
            'a measurement.'),
          el('li', 'A water quality analysis describes one sample at one moment; ' +
            'microbiological quality in particular varies with season.'),
          el('li', 'Unit rates are indicative and must be confirmed locally ' +
            'before use in a tender.'),
        ]),
      ]),
      card('Also available', [
        el('p', ['This app carries every page the Streamlit version has — ' +
          'including the Depth Spine, the Portfolio and the scanned-sheet ' +
          'reader — and its engine is held to the Python package\'s own ' +
          'numbers by a parity check that runs on the real sample workbooks.']),
        el('p', ['Two things read differently rather than less. The PDF ' +
          'text-layer reader here works from the layout of the words on the ' +
          'page; the server version uses pdfplumber, which finds a table from ' +
          'the rules drawn around it. And the sign-off ledger on the Depth ' +
          'Spine is kept in the project file rather than in a session.']),
        /* and what of the terrain is not here, which "every page" would hide */
        el('p', C.phrase('terrain.python_only')),
        el('p', C.phrase('terrain.not_in_reports')),
        el('p', ['A WebAssembly build of the Streamlit app is published ' +
          'beside this one — it runs the real Python package in the browser, ' +
          'at the cost of a 60 MB first load.']),
        el('p', el('a', { href: 'wasm/', target: '_blank', rel: 'noopener' },
          'Open the WebAssembly build →')),
      ]),
    ];
  };
