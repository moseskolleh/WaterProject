
  /* --- training: find the fault (PLAN.md step 9.3) -------------------------- */

  /* Three results this toolkit once got wrong on its own worked examples.
   * Each is on record in ROADMAP.md with what was done about it (hydraulics-1
   * and hydraulics-2, ves-1, data-ingestion-3), and each is now an exercise:
   * the trainee is shown what the report said, as it was said, and has to
   * say what is wrong with it. The finding and the fix are not put on the
   * page until the fault is found, and a wrong answer says why it is not the
   * fault, so that every answer teaches something and none gives the right
   * one away.
   *
   * The numbers in "what the report said" are the old report's, which no
   * longer exists anywhere else, so they are written here. The numbers in
   * the finding and the fix are what the engine gives for the same sample
   * today, and tests/webapp/smoke.mjs holds each to the page it sends the
   * trainee to: a fix reworded in the engine fails there, not in front of a
   * class.
   *
   *   right    the option that names the fault
   *   options  [letter, the answer, why it is not the fault]
   *   sample   the worked example the exercise is about, and the page of it
   *            that shows the fix at work; none where any project will do
   */
  var TRAINING = [
    {
      key: 'storage', title: 'The 30-minute test',
      about: 'Dr. Timbo\'s Residence, pumping test',
      said: [
        'A constant discharge test at 2.93 m³/h, in a borehole cased at 5 inches.',
        'The pump ran for 30 minutes. When it stopped the water level had fallen ' +
          '32.8 m and was still falling.',
        'The report adopted a transmissivity of 1.4 m²/day and recommended a safe ' +
          'yield of 0.97 m³/h.',
      ],
      question: 'What should have stopped that yield being recommended?',
      right: 'b',
      options: [
        ['a', 'The pumping rate was too low to stress the aquifer.',
          'The rate drew the level down 32.8 m in half an hour. The borehole was ' +
          'stressed hard; the question is what that drawdown was measuring.'],
        ['b', 'The test ended while the pump was still emptying the casing, so the ' +
          'readings describe the borehole and not the aquifer.', ''],
        ['c', 'The static water level was not measured before pumping.',
          'The sheet carries a static level, and the drawdown is worked out from it.'],
        ['d', 'A constant discharge test cannot give a transmissivity; only a step ' +
          'test can.',
          'A constant discharge test is the usual way to find a transmissivity. A ' +
          'step test adds the well loss to it.'],
      ],
      finding: 'With a 5 inch casing and a specific capacity of 0.089 m³/h per metre, ' +
        'casing storage controls the drawdown for about the first 117 minutes ' +
        '(Schafer\'s rule). The test pumped for 30, entirely inside that time, so its ' +
        'curve is the casing being emptied: a Theis fit to it returns a storativity of ' +
        '0.18, more than any aquifer stores. The 1.4 m²/day that was adopted came from ' +
        'a recovery line that missed the origin by 21.7 m.',
      fix: 'The toolkit now works out the casing-storage time from the casing and the ' +
        'first drawdown and adopts no fit made inside it, flags a storativity above ' +
        '0.1, and checks that a recovery line passes through the origin. The same ' +
        'sheet now gives 0.39 m³/h, marked indicative, and says how long the test ' +
        'needed to run. The pumping co-pilot and the field kit give the time the pump ' +
        'must outlast before the test starts.',
      sample: 'dr_timbo', page: 'pumping',
      open: 'Load the example and open its pumping test',
    },
    {
      key: 'halfspace', title: 'The aquifer 80 m deep',
      about: 'Rokel, geophysics',
      said: [
        'Two Schlumberger soundings, each laid out to an AB/2 of 80 m.',
        'Both models end in a layer of 47 to 50 ohm-m that starts about 8 m down, ' +
          'with nothing found beneath it.',
        'The report said: water bearing zone from 8 m to 80 m, aquifer thickness ' +
          '72 m, drill to 80 m.',
      ],
      question: 'Where did the 80 m come from?',
      right: 'b',
      options: [
        ['a', 'From the bottom of the water bearing layer, which the model placed at ' +
          '80 m.',
          'The model gives that layer no bottom. It is the last layer, and a model ' +
          'lets its last layer run on downward without end.'],
        ['b', 'From the electrodes: 80 m is the largest AB/2 the crew laid out, not a ' +
          'depth at which anything was found.', ''],
        ['c', 'From the depth of a borehole nearby, used as a guide.',
          'No borehole enters into the interpretation of a sounding.'],
        ['d', 'From the resistivity: ground of 47 to 50 ohm-m is water bearing to ' +
          '80 m.',
          'A resistivity says what the ground may be. It does not say how deep it ' +
          'goes.'],
      ],
      finding: 'The last layer of a model is a half-space: it has a top and no base. ' +
        'The report took the largest electrode spacing for that base and called ' +
        'everything above it aquifer. A Schlumberger sounding sees to about half of ' +
        'its largest AB/2, so these two say nothing below about 40 m, and nothing at ' +
        'all about where the layer ends.',
      fix: 'The toolkit now reports such a zone as open ended. The drilling depth ' +
        'reads "at least 40 m", a minimum, with a note that the zone continues below ' +
        'the depth of investigation, and the depth to bedrock reads "not resolved". ' +
        'The VES co-pilot asks, before the survey, for the depth the sounding has to ' +
        'see, and proposes spacings long enough to see it.',
      sample: 'rokel', page: 'ves',
      open: 'Load the example and open its soundings',
    },
    {
      key: 'longitude', title: 'The site 250 km away',
      about: 'Site details, any project',
      said: [
        'A position was read off a phone and typed into the site details as ' +
          '8.4657, 13.2317.',
        'The app took it. The site was drawn inside Sierra Leone, about 250 km from ' +
          'the village, and every map and report used that position.',
      ],
      question: 'What was wrong with what was typed?',
      right: 'b',
      options: [
        ['a', 'The latitude and the longitude were typed the wrong way round.',
          '8.47 degrees north is a latitude inside Sierra Leone, and it comes first, ' +
          'as the box asks.'],
        ['b', 'The longitude has lost its minus sign: Sierra Leone is west of ' +
          'Greenwich, so its longitudes are negative.', ''],
        ['c', 'The position was in degrees and minutes, not decimal degrees.',
          'These are decimal degrees. A reading in degrees and minutes carries two ' +
          'numbers for each coordinate.'],
        ['d', 'The phone\'s GPS was too inaccurate to use.',
          'A phone is good to a few metres. An error of 250 km is not a poor fix; it ' +
          'is a different place.'],
      ],
      finding: 'Typed without its sign, 13.2317 is a longitude east of Greenwich, in ' +
        'UTM zone 33 and some 2,900 km from Sierra Leone. The app then relabelled the ' +
        'zone as one of Sierra Leone\'s two, which put the point back inside the ' +
        'country, though not where the village is, and said nothing.',
      fix: 'A longitude typed without its western sign is now read as western, with a ' +
        'note saying so. A position outside the country\'s two UTM zones is refused ' +
        'with a message and never moved into one, and degrees and minutes are read as ' +
        'what they are.',
      sample: null, page: 'site',
      open: 'Open Site & maps and try it',
    },
  ];

  /* How far a trainee has got: for each exercise the wrong answers given, in
   * order, and whether the fault was found. It is the trainee's and not the
   * project's, so it is in no project file; it is kept in this browser, and
   * in this tab alone where the browser will not keep it. */
  var TRAINING_KEY = 'gwt.training.v1';
  var trainingState = null;

  function trainingProgress() {
    if (trainingState) return trainingState;
    trainingState = {};
    try {
      var kept = JSON.parse(localStorage.getItem(TRAINING_KEY) || '{}');
      TRAINING.forEach(function (exercise) {
        var was = kept && kept[exercise.key];
        if (!was || typeof was !== 'object') return;
        var letters = exercise.options.map(function (o) { return o[0]; });
        trainingState[exercise.key] = {
          wrong: (Array.isArray(was.wrong) ? was.wrong : []).filter(function (l, i, all) {
            return letters.indexOf(l) !== -1 && l !== exercise.right && all.indexOf(l) === i;
          }),
          found: was.found === true,
        };
      });
    } catch (e) { /* no storage, or not ours: start from nothing */ }
    return trainingState;
  }

  function keepTraining() {
    try {
      localStorage.setItem(TRAINING_KEY, JSON.stringify(trainingState || {}));
    } catch (e) { /* kept for this tab only */ }
  }

  function forgetTraining() {
    trainingState = {};
    try { localStorage.removeItem(TRAINING_KEY); } catch (e) { /* nothing to remove */ }
  }

  function trainingAnswer(exercise, letter) {
    var progress = trainingProgress();
    var mine = progress[exercise.key] || (progress[exercise.key] = { wrong: [], found: false });
    if (mine.found) return;
    if (letter === exercise.right) mine.found = true;
    else if (mine.wrong.indexOf(letter) === -1) mine.wrong.push(letter);
    keepTraining();
    render();
    /* the keyboard, and with it a screen reader, goes to what the answer
     * brought: the finding, or why that answer is not the fault */
    var said = document.getElementById('training-' + exercise.key + '-said');
    if (said) said.focus();
  }

  function trainingCard(exercise, number) {
    var mine = trainingProgress()[exercise.key] || { wrong: [], found: false };
    var tries = mine.wrong.length + (mine.found ? 1 : 0);
    var last = mine.wrong[mine.wrong.length - 1];
    var body = [
      el('p.muted', exercise.about),
      el('h3', 'What the report said'),
      el('ul', exercise.said.map(function (line) { return el('li', line); })),
      el('h3', { id: 'training-' + exercise.key + '-asks' }, exercise.question),
      el('div.training-options', { role: 'group',
        'aria-labelledby': 'training-' + exercise.key + '-asks' },
      exercise.options.map(function (option) {
        var wrong = mine.wrong.indexOf(option[0]) !== -1;
        var right = mine.found && option[0] === exercise.right;
        return el('button.training-option' + (wrong ? '.is-wrong' : '') +
          (right ? '.is-right' : ''), {
          type: 'button',
          /* an answer already given stays where it is and cannot be given
           * again; once the fault is found the question is closed */
          disabled: wrong || mine.found,
          onclick: function () { trainingAnswer(exercise, option[0]); },
        }, [
          el('span.training-letter', { 'aria-hidden': 'true' }, option[0].toUpperCase()),
          el('span', option[1]),
          wrong ? el('span.badge.badge-warn', 'not the fault') : null,
          right ? el('span.badge.badge-ok', 'the fault') : null,
        ]);
      })),
    ];
    if (mine.found) {
      body.push(el('div.callout.callout-ok', { id: 'training-' + exercise.key + '-said',
        tabindex: '-1' }, [
        el('p', el('strong', tries === 1 ? 'Found, at the first answer.'
          : 'Found, at answer ' + tries + ' of ' + exercise.options.length + '.')),
        el('h4', 'The finding'), el('p', exercise.finding),
        el('h4', 'What the toolkit does now'), el('p', exercise.fix),
        el('div.btn-row', [
          button(exercise.open, async function () {
            if (exercise.sample) await loadSample(exercise.sample);
            goto(exercise.page);
          }, { variant: 'ghost' }),
        ]),
        exercise.sample ? el('p.muted', 'Loading an example replaces the project ' +
          'that is open. Save yours first if you want to keep it.') : null,
      ]));
    } else if (last) {
      var why = exercise.options.filter(function (o) { return o[0] === last; })[0][2];
      body.push(el('div.callout.callout-warn', { id: 'training-' + exercise.key + '-said',
        tabindex: '-1' }, [
        el('p', [el('strong', 'Not the fault. '), why]),
        el('p', 'Look again at what the report said, and choose another answer.'),
      ]));
    }
    return card(number + '. ' + exercise.title, body);
  }

  PAGES.training = function () {
    var progress = trainingProgress();
    var found = TRAINING.filter(function (e) { return progress[e.key] && progress[e.key].found; }).length;
    var begun = TRAINING.some(function (e) {
      return progress[e.key] && (progress[e.key].found || progress[e.key].wrong.length);
    });
    return [
      pageHead('Training: find the fault', 'Three results this toolkit once got ' +
        'wrong, on its own worked examples. Each is shown as the report gave it. ' +
        'Find what is wrong with it; the finding and what was done about it are ' +
        'shown once you have.'),
      el('div.callout.callout-info', el('p', C.phrase('training.browser_only'))),
      card('Progress', [
        el('p.training-progress', found + ' of ' + TRAINING.length + ' faults found'),
        el('p.muted', 'Kept in this browser, not in the project: it is yours, and ' +
          'goes with no project file.'),
        begun ? el('div.btn-row', [
          button('Start again', function () {
            forgetTraining();
            render();
            S.toast('The three exercises are as they were at the start.', 'ok');
          }, { variant: 'ghost' }),
        ]) : null,
      ]),
    ].concat(TRAINING.map(function (exercise, i) { return trainingCard(exercise, i + 1); }));
  };
