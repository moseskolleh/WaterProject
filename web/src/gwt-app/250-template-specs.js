
  /* --- templates ------------------------------------------------------------ */

  var TEMPLATE_SPECS = {
    ves: {
      label: 'VES field data', file: 'ves_template.xlsx',
      sheets: function () {
        return [{ name: 'VES 1', rows: [
          ['SCHLUMBERGER ARRAY VES FIELD DATA'],
          ['Client', '', 'Community', ''],
          ['Project', '', 'Sounding Number', 'VES 1'],
          ['District', '', 'Chiefdom', ''],
          ['GPS Coordinate East', '', 'GPS Coordinate North', ''],
          ['Elevation', '', 'Date', ''],
          ['Field Supervisor', '', 'Instrument', ''],
          [],
          ['No.', 'AB/2 (m)', 'MN (m)', 'Apparent Resistivity (ohm-m)'],
          [1, 1.5, 0.5, ''], [2, 2, 0.5, ''], [3, 3, 0.5, ''], [4, 4, 0.5, ''],
          [5, 6, 0.5, ''], [6, 8, 0.5, ''], [7, 10, 0.5, ''], [8, 15, 0.5, ''],
          [9, 15, 5, ''], [10, 20, 5, ''], [11, 25, 5, ''], [12, 30, 5, ''],
          [13, 40, 5, ''], [14, 50, 5, ''], [15, 60, 5, ''], [16, 80, 5, ''],
          [17, 100, 5, ''],
        ] }];
      },
      note: 'One worksheet per sounding. Repeat an AB/2 with the new MN at a ' +
        'segment change — both readings are kept.',
    },
    drilling: {
      label: 'Drilling log', file: 'drilling_log_template.xlsx',
      sheets: function () {
        return [{ name: 'Drilling Log', rows: [
          ['BOREHOLE DRILLING LOG'],
          ['Community', '', 'Client', ''],
          ['Contractor', '', 'Borehole Ref. No.', ''],
          ['District', '', 'Chiefdom', ''],
          ['Drilling Method', '', 'Drill Rig', ''],
          ['Start Date', '', 'Completion Date', ''],
          ['Total Depth', '', 'BH Status', ''],
          ['Grouting Depth', '', 'Screens installed (m)', ''],
          [],
          ['Depth Interval (m)', 'From', 'To', 'Penetration rate (m/min)',
            'Sample description / lithology', 'Bit diameter (in)', 'Water strike (m)'],
          ['0-3', '', '', '', '', '', ''],
          ['3-6', '', '', '', '', '', ''],
          ['6-9', '', '', '', '', '', ''],
        ] }];
      },
      note: 'Format the depth column as Text before typing "5-10", or Excel ' +
        'converts it to a date and the row is skipped. Fill "Screens installed" ' +
        'as ranges ("25-35; 48-53") once the string is set: the drawing is then ' +
        'an as-built record rather than a design.',
    },
    daily: {
      label: "Driller's daily report", file: 'daily_log_template.xlsx',
      sheets: function () {
        var rows = [
          ["DRILLER'S DAILY REPORT"],
          ['Community', '', '', 'Borehole Ref. No.', ''],
          ['Date', '', '', 'Drill rig', ''],
          ['Contractor', '', '', 'Supervisor', ''],
          ['Weather / site conditions', '', '', 'Record taker', ''],
          [],
          ['Time from', 'Time to', 'Depth from (m)', 'Depth to (m)',
            'Formation / activity', 'Water strike (m)', 'Airlift yield (L/s)'],
        ];
        for (var i = 0; i < 14; i++) rows.push(['', '', '', '', '', '', '']);
        rows.push([]);
        rows.push(['Metres drilled today', '', 'Cumulative metres', '',
          'Casing installed today (m)', '']);
        rows.push(['Standing / breakdown hours', '', 'Reason', '']);
        rows.push([]);
        rows.push(['Rig operator signature', '', '', 'Supervisor signature', '']);
        rows.push([]);
        rows.push(['Notes: one row per drilled interval or activity (moving, ' +
          'standing, casing). Both signatures are required every day; the ' +
          'office checks invoiced metres against these logs.']);
        return [{ name: 'Daily Log', rows: rows }];
      },
      note: 'The daily record the supervision guidance expects, and what ' +
        'invoiced metres are checked against. One row per drilled interval ' +
        'or activity, and both signatures every day.',
    },
    pumping: {
      label: 'Pumping test', file: 'pumping_test_template.xlsx',
      sheets: function () {
        /** @type {Array<Array<*>>} */
        var rows = [
          ['PUMPING TEST FIELD SHEET (STEP / CONSTANT DISCHARGE)'],
          ['Community', '', '', 'Date', '', '', 'GPS Coordinate East', ''],
          ['Client', '', '', 'Length of each step (min)', '', '', 'GPS Coordinate North', ''],
          ['Borehole Ref. No.', '', '', 'Test Type', 'step', '', 'Depth of Borehole', ''],
          ['Static Water Level', '', '', 'Pump Setting', '', '', 'Test conducted by', ''],
          ['Step 1 Q (m3/h)', '', 'Step 2 Q (m3/h)', '', 'Step 3 Q (m3/h)', '',
            'Step 4 Q (m3/h)', ''],
          [],
          ['Time (min)', 'Water Level (m)', 'Drawdown (m)',
            'Time (min)', 'Water Level (m)', 'Drawdown (m)',
            'Time (min)', 'Water Level (m)', 'Recovery (m)'],
        ];
        /* the co-pilots' and the field kit's schedule (data/field.yaml), to
         * the end of the hour each group covers */
        C.readingMinutes(60).forEach(function (t) {
          rows.push([t, '', '', t, '', '', t, '', '']);
        });
        return [{ name: 'Pumping Test', rows: rows }];
      },
      note: 'The Drawdown and Recovery columns are the increment between ' +
        'readings; the toolkit never uses them — true drawdown is recomputed ' +
        'from water level minus static level.',
    },
    quality: {
      label: 'Water quality results', file: 'water_quality_template.xlsx',
      sheets: function () {
        var params = [
          ['pH', 'pH units'], ['Temperature', 'deg C'],
          ['Electrical conductivity', 'uS/cm'], ['TDS', 'mg/L'],
          ['Turbidity', 'NTU'], ['Total hardness', 'mg/L'], ['Alkalinity', 'mg/L'],
          ['Calcium', 'mg/L'], ['Magnesium', 'mg/L'], ['Sodium', 'mg/L'],
          ['Potassium', 'mg/L'], ['Chloride', 'mg/L'], ['Sulfate', 'mg/L'],
          ['Bicarbonate', 'mg/L'], ['Nitrate', 'mg/L'], ['Nitrite', 'mg/L'],
          ['Ammonia', 'mg/L'], ['Iron', 'mg/L'], ['Manganese', 'mg/L'],
          ['Fluoride', 'mg/L'], ['Arsenic', 'mg/L'], ['Lead', 'mg/L'],
          ['E. coli', 'CFU/100mL'], ['Total coliforms', 'CFU/100mL'],
        ];
        return [{ name: 'Water Quality', rows: [
          ['WATER QUALITY LABORATORY RESULTS'],
          ['Community', '', 'Client', ''],
          ['Sample ID', '', 'Borehole Ref. No.', ''],
          ['Sample Date', '', 'Laboratory', ''],
          [],
          ['Parameter', 'Value', 'Unit', 'Detection limit', 'Method'],
        ].concat(params.map(function (p) { return [p[0], '', p[1], '', '']; })) }];
      },
      note: 'Write "<0.01" for a below-detection result; the value is then ' +
        'treated as unknown rather than as a concentration equal to the limit.',
    },
  };
