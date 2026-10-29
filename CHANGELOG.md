# Changelog

One section per version, newest first. PLAN.md step 0.4 closed the long
"changes pending release" entry as 0.3.0; everything below the Stage 0 notes is
that entry, kept as it was written.

## Unreleased

### Links that go to a page, and less before the first paint (PLAN.md steps 1.4 and 1.5)

Every page of the browser app now has an address, `#/<page>`. The Geophysics, Pumping test and Asset registry pages can also name one item, as in `#/ves/VES-3`, `#/pumping/KTL-01` and `#/registry/<asset id>`. The back and forward buttons move between pages, the user guide links to them, and a QR code on a field sheet can open one. An address wins over the page a saved session was left on. An address the app doesn't know opens the Overview, and an item the open project doesn't hold is flagged across the top of the page. The Streamlit app has no such addresses; step 1.1 is where its pages get their own.

The first screen now loads less. The map layers and the sample workbooks moved out of `gwt-data.js`, now 86 KB, into `gwt-geo.js` (760 KB) and `gwt-samples.js` (50 KB). Those two, and the figures, the map export, the photo slots and the document writer, are fetched the first time a page, a report or a sample needs them. The five scripts left in `index.html` are deferred, and the service worker still precaches every bundle, so the app works offline as before. Time to interactive on the throttled profile (4x CPU, Slow 4G, cold, median of 5 runs) fell from 16.25 s to 9.08 s, 44 percent lower, against the plan's 40. `bench/web.mjs` now follows Lighthouse in never placing time to interactive before the end of DOMContentLoaded; without that floor a page with deferred scripts reads as interactive at first paint, and the floor does not move the figure on 0.3.0. The cost has moved rather than gone: on a cold, uninstalled visit, the first page that draws maps fetches about 1.07 MB before it draws, several seconds on Slow 4G. Once the service worker has installed, that is instant, offline included. What remains on the critical path is `gwt-core.js` and `gwt-app.js`, uncompressed; minifying them is left for later.

### A saved survey reopens without inverting it again (PLAN.md step 1.6)

Reopening a saved survey no longer inverts it again (PLAN.md step 1.6). Each engine saves its inversions in the project file under the SHA-256 of the sounding's id, array type, AB/2, MN and apparent resistivities, the whole VES configuration, a format number and the engine's name. For Python the engine name is the package version, the numpy and scipy versions and a digest of ves/inversion.py, forward.py, splice.py and models.py. For the browser it is the release and a SHA-256 of gwt-core.js written into gwt-data.js. Only the chosen model, its iteration count, whether it converged and the layer-count trials are stored. `restore_inversion`/`restoreInversion` rebuild the rest, and the result is identical to a fresh one on the same machine and build. A file from another machine gives that machine's answer, which can differ in the last digits, as fresh inversions on two BLAS builds do. An entry is ignored and the sounding inverted afresh when its key does not match, when a field is malformed, or when its model does not reproduce the misfit the search recorded. The entry's digest catches accidental damage, not deliberate editing. project.yaml gains an optional `inversion_cache` (schema stays 1), and `.gwt.json` gains `state.inversionCache`. The cache is mirrored to localStorage but dropped from the mirror rather than letting it stop autosave. In the browser, a recompute such as typing a discharge no longer drops the inversions or cancels a run for the same soundings, which used to leave the Geophysics page showing "not yet inverted". Opening another project stops a running inversion before the new project replaces the session. Measured on a shared 4-CPU machine: reopening the saved Rokel project in Python went from 3.10 s to 34.6 ms (median of 5), and in the browser at 4x CPU slowdown from 4.87 s to 0.38 s (median of 3).

### The Streamlit app runs only the page on screen (PLAN.md step 1.1)

The Streamlit app now runs only the page on screen (PLAN.md step 1.1). Each page is a `render()` in `app/views/`, registered with `st.navigation` behind the grouped sidebar. The folder is not called `pages/`, as the plan has it, because Streamlit reads that as an old-style multipage app. The session state the pages share is written down in `app/state.py`, and the helpers they share are in `app/shared.py`. Results that follow from other results (the design from the pumping test, Depth Spine screens over it, the costing depth from the design) are brought up to date before and after the page runs. Inputs that must outlive a visit to another page are carried across, and an uploaded file is kept while its page is off screen. That carrying is Streamlit's documented pattern and trips a server-log warning by design, so `global.disableWidgetStateDuplicationWarning` is set; the warning is never shown in the app. Parsed workbooks and drawn figures are cached on a hash of their content, the pumping test analysis and the water quality assessment are cached, and the coverage join no longer touches session state. On this machine a rerun with every sample loaded took 3.9 to 4.3 s on every page and now takes 46 to 141 ms. `tests/test_app.py` went from 204 s to 63 s. A project file now holds a page's untouched default inputs only once that page has been opened in the session; loading the file draws them at the same defaults. The guided start's buttons are no longer saved: a file carrying them failed to load while the guided start was on screen. A manual depth typed in the guided start no longer reverts to 60 m on the costing step.

### Projects are stored in IndexedDB (PLAN.md step 1.3)

The browser app now keeps the working session in IndexedDB instead of one localStorage key (PLAN.md step 1.3). Each top-level field of the session is a record, every workbook and photograph is stored once as a Blob, and the inversion cache sits in a store of its own that may be refused for want of room without stopping the rest being kept. An autosave writes only the records that changed, in one transaction, and deletes files nothing refers to any more. For a project of 50 photos and 10 workbooks (20.6 MB as JSON), an autosave after one typed field took 43-59 ms of main-thread time at full CPU before, and every write was refused for quota. It now takes 0.8-1.7 ms, and 3-7 ms at a 4x CPU slowdown, and the project survives a reload exactly. The first write of such a project takes about 75 ms at full CPU, in chunks. A session left in `gwt.project.v1` by an earlier build is moved across and the old key removed once the copy reads back; if an earlier build is used again afterwards, its later session is the one opened. Only one tab saves. A second tab opens read-only and says so, and "Continue here" moves the saving to it after reading what the other tab saved, without that tab's own older state ever being written over it. A pending autosave is written as soon as the tab is hidden. Where IndexedDB is missing or refused, the app says at once that it is saving nothing. The Settings page shows storage use and whether the browser has agreed to keep it. Tested in Chromium only; Firefox's and Safari's handling (Safari private mode, Firefox's persist prompt, IndexedDB on file://) is untested, and where IndexedDB is unavailable the banner says nothing is being kept. An edit made less than 400 ms before a tab is closed may still be lost, as it was with localStorage.

### One source for the words and defaults both engines use (PLAN.md step 1.7)

The water quality recommendations, the handover works list and the reports' citations are now written once, in `src/groundwater/data/text/quality.yaml`, `handover.yaml` and `references.yaml`. Both engines read them: Python through `groundwater.text.phrase`, and the browser through `GWT.data.text`, which `build_webapp_data.py` emits from the same files. A sentence is a template with named values. A number always names its format (`{d:num}`, `{d:g}`, `{d:.0f}`), and `{n:plural:one|other}` agrees with a count. A missing value, a value the template does not use, a bare number or a lone brace is an error rather than a sentence with a hole in it. The configuration defaults moved the same way, into `src/groundwater/data/defaults.json`: `config.py` builds every field from it, and the browser's `defaultConfig()` copies it, so the two apps cannot start from different numbers. Every default keeps its value and type, so saved inversion caches still hit. The two apps' bibliographies had grown apart, so the reference table keeps both wordings, with the browser's marked `_web`; settling each pair is a change of its own. Every report is byte-identical: parity is 1377/1377, reference.json and the worked examples are unchanged. A test that renders about 21,000 generated numbers through both engines found that the browser's rounding had been deciding ties on seventeen rounded digits. To that precision 1.05 reads as a tie, so the browser wrote 1.0 where Python wrote 1.1, and `fmt_num` gave 0.001 for 0.001005 where Python gave 0.00101. The browser now rounds such cases on the exact binary value. It also writes -0, nan, inf and numbers past 1e21 as Python does. `pyFixed` costs 3.0 µs a call against 1.6 µs before (200,000 calls in node, median of five). Many other sentences both engines write, such as the designer's annular fill text, the water quality verdicts, the O&M guidance and the report limitations, are still worded once in each engine; step 1.7 stays open until they move into the catalogue, one list at a time.

### The two engines held to each other on generated field sheets (PLAN.md step 1.8)

The two engines are now compared on generated field sheets as well as the three sample projects. Hypothesis draws VES soundings, pumping tests, laboratory sheets and drilling logs and writes each as a workbook. The Python readers and `gwt-core.js` (in headless Chromium, through a Node process held open) read the same bytes, and the answers are compared at the tolerances parity.mjs uses. A pull request replays every saved counterexample plus 150 cases per generator and 10 inversions, in about 75 s (`nox -s fuzz`, and a CI job of its own). The nightly run draws 6,000 per generator and 300 inversions. In about 65,000 cases the runs found divergences in both engines, and these were put right. The drilling log's depth flags printed floats differently in each engine. The browser read date cells in sheet headers, and time-of-day cells, differently from Python. The browser printed fixed decimals with `toFixed`, which rounds exact ties away from zero; it now uses Python's half-to-even rounding throughout `gwt-core.js` (the document writer, `gwt-docx.js`, still has 20 `toFixed` calls no parity check reads). The browser's Theis fit stopped at 200 iterations; it now runs to convergence within curve_fit's 20,000-evaluation budget. Python's curve_fit tolerance is tightened to 1e-12, which moves Dr Timbo's Theis T and S by about 1.2e-6 relative. Wenner and Schlumberger soundings now count distinct spacings before inverting. These cases are now refused in both engines, where each used to report a different meaningless number, transmissivities from 1,282 to 4e17 m2/day among them: a step test whose steps share one rate (within 1e-6 relative); a Theis or recovery line that moves by less than the 0.01 m a dipper reads across its readings; and a Theis fit that drives the storativity below 1e-280. The first version of the flat-line refusal used a slope of 0.02 m per log cycle, which would have refused genuine handpump tests on aquifers of a few hundred m2/day; the review replaced it with the dipper's resolution, and three tests in `tests/test_hydraulics.py` hold genuine high-transmissivity tests to their answers. A Cooper-Jacob slope within 1e-9 of zero counts as flat. Six questions of method are recorded as open cases and held to diverging until they are answered: a uniform half-space, an unconverged inversion, a poorly resolved boundary, equivalent models, a thin top layer whose resistivity the data do not fix, and prose printed to more digits than the engines agree on. Every counterexample is shrunk and kept in `tests/fuzz/regressions/`, and Hypothesis is pinned so the pull-request cases do not change under it.

### Type and lint checks for the code that had none (PLAN.md step 1.9)

The deferred Ruff UP and SIM findings are cleared and both rule sets are on. Ruff's own fixes did most of it (`X | None` for `Optional[X]`, `collections.abc` for typing's aliases, unquoted annotations). The nested ifs and the try/except/pass were rewritten by hand. SIM108 is off, because five of its eight ternaries read worse. Pyright 1.1.414 runs in basic mode on the package at the 3.10 floor. It starts with `models.py`, `units.py` and `config.py` and checks every module that passes, 59 of 101. The other 42 are listed in pyproject.toml, and `nox -s types` fails if one of them starts passing while still on the list. CI pins numpy, matplotlib and the other libraries whose types pyright reads, so a new release of one cannot turn the job red on its own. pytest-cov reports line coverage with no threshold: 94% over the whole suite. In `docs/js`, `tsc --checkJs` reads every script the app loads. `gwt-core.js` carries `// @ts-check` and is checked in strict mode less `noImplicitAny`, and a script fails the build if any of the 375 functions on `GWT.core` takes a parameter without a JSDoc type. oxlint runs over `docs/js` with warnings denied. Both tools are the versions `ui/depth-spine`'s lockfile pins, run by `nox -s js`. Eleven unused locals the checks found are removed. The annotations are comments and the casts only bracket an expression: with brackets and comments removed, every script parses to the same tree as before, apart from one renamed loop variable. Nothing the apps compute changes. Parity is 1371/1371, and the fuzz and browser suites pass. Both engines' code digests moved, through `gwt-core.js` and through `models.py`, so every saved inversion is inverted once more the first time its project is reopened, in either app. In the browser app, 38,000 lines of JavaScript that were unchecked are now type-checked and linted; only `gwt-core.js` is held strictly.

### One engine or two: two (PLAN.md step 1.10)

The browser app keeps its JavaScript engine. `spikes/pyodide-engine/` ran the VES page's computation, the inversion and interpretation of the two Rokel soundings, through the Python package under Pyodide 0.29.3 in a Web Worker. Only numpy, scipy and PyYAML were loaded, all from a precache with the network cut off, and it was timed against `gwt-worker.js` in headless Chromium on a 4-CPU machine, median of five runs. The inversions came in 1.46 to 1.67 times slower than `gwt-core.js`, inside the plan's 2x. The other two thresholds failed. The precache is 30.9 MB against the plan's 25 MB (23.2 MB sent with brotli). A warm start takes 6.4 s against 4 s; the JavaScript worker starts in 40 ms. Of that start, about 3.5 s is scipy, which the package uses for three Bessel functions. With the CPU slowed 4x on the page, a start took 35 s, and peak memory was 476 MB against 127 MB. Every answer agreed with CPython and with `reference.json` at parity's tolerances. `docs/decisions/0001-engine.md` records the numbers, the decision, and what would reopen it (a change to the runtime, not the device: a warm start under about 1 s here and a precache under 25 MB). Steps 1.7 and 1.8 stay the safety net, and the stage 3 samplers will be written as small, parity-tested cores in both engines. No phone or field laptop was measured. A phone cannot start Pyodide faster than this machine does, so its numbers cannot reverse the decision, but they are still needed to budget the JavaScript samplers. Neither app changes.

### A pumping test co-pilot (PLAN.md step 2.1)

The browser app gains a pumping test co-pilot (`#/pumpcopilot`). Before pumping it works out Schafer's casing-storage period through the engine's `casingStorageMin` for a cautious transmissivity range (1 to 10 m2/day, through Logan's T = 1.22 Q/s), and states the earliest stop time: the later of that period and the engine's minimum test length. Once levels are read, the period worked out from the drawdown so far only replaces the cautious one after the readings have passed it, because that period grows while the level falls: from 13 minutes at minute 1 of the Dr Timbo test to 117 at minute 30. It keeps the log-spaced reading schedule with a countdown, a beep and vibration, and warns of the level at, or within the engine's submergence margin of, the pump intake; a discharge more than 5 percent off the step's first; casing storage; missed readings; and a device clock set back. A pump that started before the page was opened can be backdated. Past storage it fits the engine's own Cooper-Jacob line in the worker, and says the test can stop only when T has moved under 10 percent over a log cycle and the planned time is not short of the analysis's minimum. It times a bucket three times, and a step without a discharge cannot be saved without a stated reason; both apps' readers no longer take a discharge from a note that begins "Not measured". The schedule restarts at the stop for recovery. It writes the standard template, with the device clock and GPS position in the header and a log sheet; readings are written at the scheduled minute only within 6 s before it to 2 percent after it. "Use it as this project's pumping test" sets the project's casing and riser to the ones entered; a downloaded sheet analysed elsewhere still uses the configured casing, because no reader takes the diameters from the sheet yet. The test is kept in IndexedDB at every reading and its clock is the device clock, so a reload or a sleeping phone comes back to the right minute. Played back at speed, Dr Timbo's readings raise "do not stop before 13:07" and "still inside casing storage" at 30 minutes, and the Kuntolo sheet cannot be written until each of its three steps carries a discharge or a reason (tests/webapp/copilot.mjs, 51 checks; tests/test_pumping_copilot.py reads the sheets with the Python reader). Tested in headless Chromium only; no phone has run it. The cautious transmissivity floor, Logan's factor, the rule for handing over from the cautious to the measured storage period, the reading tolerance and the 10 percent stability limit are choices that want a hydrogeologist's confirmation.

### A VES co-pilot (PLAN.md step 2.2)

The browser app has a VES co-pilot (`#/vescopilot`, under Investigation; browser app only, and the Streamlit Geophysics page says so, in a sentence both apps read from the text catalogue). From the target depth it proposes the AB/2 series by the engines' own depth-of-investigation rule, read from the configuration, with MN never above a fifth of AB and each MN change repeating its AB/2, so the line is long enough before a cable is unrolled. Each reading, as V in mV and I in mA or as an apparent resistivity worked out with the engine's own Schlumberger factor, goes on the log-log curve at once and is checked at the peg: a rise more than 10 percent above the 45-degree line from the previous reading at the same MN, which layered ground cannot produce (the allowance is there because, with a finite MN, good readings over a resistive basement sit just above the ideal line); an MN overlap that fails the engine's own 20 percent test (`C.overlapDiscrepancies`, now exported); a potential below the instrument setting (1 mV by default, a working default rather than a standard); and a skipped or repeated spacing. Played back, every Rokel overlap that disagrees by 45 to 98 percent says "Re-measure now" at the peg and the three that agree say nothing, and basement models read through the plan with 3 percent scatter raise no false steep rise. From eight readings a preview inversion runs in the engine worker as its own task (`previewInvert`), debounced, labelled as a preview; it stops when the page is left, and runs only on request where there is no worker. The session is kept with the project, survives a reload, and, like the pumping co-pilot's, is carried over when another project or sample is opened. The output is the standard VES workbook, with the device clock and GPS in row 9 and V, I and time beside each reading, and both apps' readers read it back unchanged. Tested in headless Chromium only. The 10 percent steep-rise allowance, the 1 mV floor, widening MN past AB = 20 MN and stopping the series at AB/2 = 500 m want a geophysicist's confirmation.

### Photo evidence with provenance (PLAN.md step 2.4)

Every photograph either app takes in now records where it came from: the SHA-256 of the file as attached, its capture time and its position, each with its source. The time is the EXIF DateTimeOriginal where the file carries one, with its UTC offset where the camera wrote it, and otherwise the attaching machine's clock at attach, in UTC (in the Streamlit app, the server's). The position is the EXIF GPS, with the horizontal error the camera recorded, or a fix this device gave when the photograph was attached, with the accuracy it reported, or none, with the reason. The browser asks the device only when a box is ticked, and waits at most 30 seconds for it, permission prompt included, before keeping the photograph without a position; the Streamlit app, which runs on a server, cannot ask. The browser downscales large photographs for storage; the hash stays the original's, and the record says the copy kept is downscaled. Both engines read EXIF with a small reader written out in each, so nothing new is installed, and parity holds them to the same record, to the last bit of each coordinate, on a fixture JPEG whose EXIF is written byte by byte by a script in the tests and on variants of it. Read against each other on 7,526 generated files (every truncation of the fixture in both byte orders, random bytes and byte-level mutations), the two readers first disagreed on 14, all because Python trimmed control bytes that the browser keeps; they now agree on all of them, and neither raised on any. Which checklist items need a photograph is a new `photo` column in `supervision_checklists.csv`: the screen make-up, the sanitary seal and the disinfection. Until each has one, or is answered N/A, both apps' readiness gates hold the supervision record. They name each item in a sentence from the new `evidence.yaml` catalogue and say that they check a photograph is present, not whether it shows good work. Both supervision reports print each photograph's time, position and short hash with their sources, and the Python report's section 3 is now numbered in the order it prints. A photograph attached before this step opens as before and is said to have no recorded provenance; nothing is filled in for it. Hashing a 6 MB photograph with the engine's own SHA-256 takes 120 ms on the page's thread (Node, full CPU, this machine), so the page uses the browser's `crypto.subtle` where it can. Tested in headless Chromium only; no phone has attached a photograph. Which items need a photograph, that the gate holds the supervision report only, and that a camera's position wins over the device's want a supervisor's confirmation.

### A field kit for crews without a device (PLAN.md step 2.5)

Both apps have a Field kit button on the Templates and Pumping test pages. It writes one Word document: a pumping test sheet for each borehole named, and three quick cards to laminate, for the pumping schedule, the VES spacings and the chlorine doses. Each sheet is pre-filled with the site and the borehole number under the labels of the standard pumping template. It states the casing-storage time, which is the engines' `casing_storage_min` at the pumping co-pilot's cautious 1 m2/day: 307 minutes for a 5 inch casing and a 1.25 inch riser, so the default sheet reads to 330 minutes. Its Time columns hold the co-pilot's reading schedule for the pumping and again for the recovery, in the template's hourly blocks, the last running to the end of the test. A filled sheet typed into `template_pumping_test.xlsx` reads back as one constant series. The dose card is the supervision calculator's own doses, with the checklist's 20 mg/L rule and its basis. That schedule, the cautious transmissivity range, Logan's factor and the VES spacings were typed into the co-pilots. They are now written once, in `src/groundwater/data/field.yaml`, which both co-pilots, both engines and the printed kit read, and the browser's blank pumping template takes its Time column from it too. The co-pilots' proposals are unchanged on 184,031 VES targets and 40,041 schedule times compared before and after. The borehole box keeps what was typed for the session in both apps, and offers the borehole of a test as soon as it is loaded. Each sheet carries a QR code, with the code printed under it: `GWT-FK/1|pumping|<project>|<borehole>`, documented in the user guide, with a reader in both engines for step 10.1. Each field is trimmed of ASCII spaces only, so the two engines write the same code for a name that begins or ends in another whitespace character. Parity holds the kit's every word and number, its codes for hostile names, and every module of its symbols. OpenCV decodes the codes in both engines' documents to exactly the payload. Because `gwt-core.js` changed, the browser re-runs each saved inversion once when its project is first reopened. Nothing has been printed and read on paper, and no phone has scanned a printed sheet. The 307-minute floor, reading the recovery for as long as the pumping, the dose card's casing diameters and water columns, and printing the VES series to AB/2 = 500 m want a hydrogeologist's confirmation.

### A drilling log co-pilot (PLAN.md step 2.3)

The browser app has a drilling log co-pilot (`#/drillcopilot`, under Investigation; browser app only, and the Streamlit Borehole design page says so in a sentence from the text catalogue). Each interval is logged against the one lithology class table both engines read a log by. The formation is picked from a list, and a note is added after the class only when the row, read with its depths as the drawings and the design read it, is still that class. "Clay, soft saprolite" is refused because it reads as saprolite. So is "Fracture zone, 27-28 m", because both readers take the range as a zone of its own and the rest of the row as other material. A note or a not-measured reason naming a water strike is refused too, because both readers take a depth from it. The penetration rate is the device clock at the start and end of the interval over its length, in minutes per metre, rod changes included. An interval cannot start before the last one ended. A water strike carries an airlift yield from a timed container (volume over the mean time) or a 90-degree V-notch head (the Kindsvater–Shen equation without ISO 1438's head correction, which reads 2–4% low at heads of 50–100 mm; Ce = 0.58, with a head outside 50–380 mm said to be outside the range). Neither engine had an estimate, so both gain one, which asks for finite readings above zero, held together by parity on 15 cases, with the constants in `field.yaml`. Each interval takes a cuttings photograph with the provenance record every photograph carries and the interval's depths. The supervisor countersigns each day with a name and the device time, and a SHA-256 of the day's entries, the airlift yields as printed included, shows any later change. Each interval keeps the day it was logged on, so a device set to another time zone does not move it. A change after signing needs a reason, is kept, and marks the day amended until it is signed again or changed back to what was signed; a signed day emptied of its intervals stays listed as amended. This is a record, not a cryptographic signature, and the sheets say so. The output is the standard drilling log template, with the rate headed in min/m and the airlift, clock times and photo hash after its seven columns, and the driller's daily report template, a sheet a day. Both apps' readers read the drilling log back unchanged (`tests/test_drilling_copilot.py` replays Dr Timbo's log in Node and reads it in Python; `copilot.mjs`, now 68 checks, reads it in the browser). No reader takes the daily report, so it is held to the template's layout. Because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. Tested in headless Chromium only; no phone has logged a hole. The V-notch constants, gross time in the penetration rate, one strike per interval, and leaving cuttings photographs outside the countersign want confirmation.

### VES: a range of models, not one (PLAN.md step 3.1)

The VES page and reports now give a range beside each best fit. Eight Latin hypercube starting models are polished by the inversion's own fit. Each reading is given an error of 3 percent, combined with half its MN overlap disagreement, widened to the best model's misfit where that is larger, and four Metropolis-Hastings chains sample the models that fit. A report then says, for example, "Basement between 22 and 34 m (P10 to P90); not resolved in 30 percent of the models that fit", gives a table of P10, P50 and P90 for each layer, and draws the models as a grey fan over the curve. The drilling depth from the range is read from the P90 and still stops at the depth of investigation. The best fit, its interpretation and every existing reference value are unchanged. Both engines draw the same random numbers (xoshiro128**, bit for bit) and parity compares their ranges: short runs to 1e-4 with identical accept decisions, default runs to 2 percent. On 40 synthetic soundings the true basement fell inside the P10–P90 band in 82 percent and the true interfaces in 86 percent, against a stated 80; six further draws gave 70 to 88 and 80 to 90 percent. Most basement misses are soundings inverted with the wrong number of layers, because the range is conditional on the inversion's layer count. The default 4,000 samples take 5.0 s on Rokel A in Python and 7.8 s in the browser's engine worker, with a work bar and Cancel; past that, more samples did not make the bands steadier from one seed to the next. Ranges are computed on request and not saved in project files; being seeded, they come out the same when sampled again. Parity now takes about 29 s rather than 5 s. The 3 percent base error, widening to the misfit, the priors and bounds, 4,000 samples, and what counts as basement "not resolved" are provisional and want a geophysicist's confirmation.

### The pumping test given a spread, a flow regime and a large-diameter fit (PLAN.md step 3.2)

Every adopted transmissivity now carries a band from the readings themselves. The adopted fit's residuals are resampled 400 times in wrapped blocks of consecutive readings, the cube root of their number long, and each resample is refitted; the 10th to 90th percentile of the refitted values is the band. The draws come from a mulberry32 stream with a fixed seed, which both engines produce bit for bit, so the same sheet gives the same band in either app on every run. The covariance the Theis fit used to discard is kept and printed beside it as the band that assumes independent errors. The safe yield and the pump intake are given as bands too. The yield is re-run at the two ends of the transmissivity band with the dry-season reserve taken. The intake band runs over a 1 to 4 m dry-season decline, and the transmissivity does not move it. An established yield is now called sustainable only where the long-term yield at the bottom of the band still covers the recommended rate. On synthetic tests with 2 cm reading errors, the P10 to P90 band held the true transmissivity in 74 percent of Cooper-Jacob fits, 64 percent of Theis fits and 67 percent of Papadopulos-Cooper fits, against the 80 percent it names, and in 48 percent of Cooper-Jacob fits when consecutive errors were correlated at 0.6. On the Cooper-Jacob line most of the shortfall is the blocks: resampling single readings gives 78 percent. On the Theis fit its own covariance holds the truth only 67 percent of the time. The reports print these rates beside every band and say to read it as the least the spread can be. Both apps' pumping pages and reports now draw the Bourdet derivative (L = 0.2 log cycle) and name the flow regime from its log-log slope, by limits set in defaults.json and printed under the plot. With them is a warning that on synthetic radial flow with 1 to 2 cm reading errors a boundary was named about once in a hundred tests, and some other regime up to half the time where the derivative was under 0.1 m. The Papadopulos-Cooper solution, inverted by twelve Stehfest terms to within 1e-5 of its published integral, models the readings inside casing storage instead of discarding them. It is adopted only where every other fit is disqualified, its storativity is no more than 0.1 and it fits no worse than Theis. On a synthetic 30-minute test it gives 0.30 m2/day against a true 0.3, where the line read inside the casing period gave 0.20, and the result is still marked indicative. Its storativity is printed in neither app. No existing test changes its adopted transmissivity, yield or pump setting, and reference.json only gains a section. The analysis costs more: Dr Timbo's goes from 1.8 ms to 20.7 ms in Python. A bootstrap of the large-diameter fit takes 0.76 s in the browser, 3.8 s at a 4x CPU slowdown. The regime slope limits, when the large-diameter fit is adopted, the sustainability test and P10 to P90 as the band want a hydrogeologist's confirmation.

### The browser engine's Bessel functions, and a fuzz sample that stays put

Main's fuzz job went red after steps 3.1 and 3.2 merged: the two engines inverted a generated sounding differently. Neither engine's inversion had changed. The cause was two defects in the browser's port, which a newly drawn sample happened to reach. The browser computed J0 and J1 with rational approximations good to 5e-9, where Python uses scipy's Cephes routines, and its Bessel zeros were off by up to 7.4e-9. Under a thin resistive top layer the forward model cancels nearly all of the top layer's resistivity, so that error reached the apparent resistivity multiplied by rho1 / rho_a. Measured on a grid of 72 two-layer models, the gap was 1.4e-6 at 100 ohm-m, 1.5e-4 at 10,000 and 3.3e-3 at 200,000, and inversions that walk such a layer outwards stopped in different places, with fits up to a fifth apart. gwt-core.js now carries Cephes j0 and j1 as xsf has them, which scipy 1.18 evaluates; they agree with it to 1.1e-16 out to 2e5, and with the scipy 1.17 that makes reference.json to 1.5e-14, and every zero the tables can reach agrees with jn_zeros to 1 ulp. The worst gap on the grid is 1.3e-7. Separately, the browser's interp read the first of two readings at a repeated first spacing, where numpy reads the second, so such a sounding started the two inversions from different models; it now reads as numpy does, NaN and the order of its arithmetic included. On every pull request parity now holds the three forward models on that grid to 1e-6, J0, J1 and their zeros to scipy, interp to numpy bit for bit and the starting models to 1e-12: 1658 checks. Three counterexamples, including the one CI wrote, are kept as closed regressions; Python's own answer on them moves by at most 1.6e-4 under perturbations of up to 1e-7. Of the five VES cases held open as questions of method, three turned out to be these port defects and are closed: the thin resistive top layer, the equivalent models and the unconverged inversion. The other two now agree only by luck, since a 1e-15 change to Python's forward model moves its own boundary by 1.2e-3 in one and from 0.5 to 0.7 m in the other; until the owner decides, the poorly resolved boundary is replayed the way a generated inversion is compared, which leaves out every fitted number, and the uniform half-space is retired from the replays with its question recorded in the test. Under the pull-request profile Hypothesis no longer draws on the literals it collects from src/: one new constant anywhere in the package re-drew the sample before, which is how this sample landed on the defect (step 3.1's 1e-300). Each generator now has a seed of its own, and a failing case is written as drawn and printed in the log instead of being shrunk against a five-minute clock. An unused literal added to the package, or a line added to the test, now leaves all 610 drawn cases unchanged; a change to a value sheets.py computes, the Python forward model's included, still re-draws it, and the comments say so. The nightly run is unchanged. The engine's digest moved, so each browser inverts its cached soundings once more the first time a project is reopened.

### The chance of a working borehole (PLAN.md step 3.3)

Each VES point now carries the chance that a borehole there yields at least 1 m3/h at the dry-season level, the handpump design rate set in the configuration: "About 61 percent (between 39 and 78) that a borehole here yields enough for a handpump through the dry season. Provisional prior." It can be followed on paper. The prior is a success rate for the BGS aquifer class and USGS geology unit under the point. It is read from the yield ranges of the BGS atlas's productivity classes (O Dochartaigh 2021), which the guide calls average yields; taking them as the quartiles of a lognormal spread is this toolkit's choice. That gives 43 percent for basement and igneous ground, 63 for the Rokel River metasediments and 97 for the coastal sands at 1 m3/h. A point with no class gets an even chance, labelled a placeholder. Three factors from the survey multiply the odds: the depth to basement from the range of models, whether basement was resolved, and the resistivity of the water-bearing layers in the water zone. That resistivity leaves out the slice of dry layer or basement that rounding the zone to whole metres takes in, which the suitability score still reads. A poor fit weakens those three rather than counting as evidence of its own. The band is the prior's Beta distribution, as firm as 10 boreholes, carried through the same factors. Its percentiles are held inside (0, 1), so a low success yield on the coastal sands reads "over 99" rather than failing. A table under each point shows each factor and the chance after it, and the factors multiply back to the answer. Both apps' Geophysics pages and both geophysical reports print this beside the suitability score, which stays, paired with each row by position so that two points sharing an id each keep their own odds. The programme estimate keeps the rate typed for it; the Costing pages offer the first-ranked point's odds beside it, used only when "Use N percent" is pressed. Every ratio is a provisional choice, written down with its reason in success_evidence.yaml, and nothing has been calibrated against drilled outcomes. Parity holds the two engines together to 1e-9 on 147 hand-built cases, including a point exactly on every band edge, and on a 0.3 m3/h case on the coastal sands. The success yield, reading the BGS ranges as quartiles, the effective sample size of 10, every evidence ratio and the absence of a dry-hole term (which makes the priors optimistic) want a hydrogeologist's confirmation.

### The cost as a distribution (PLAN.md step 3.4)

The Costing pages and cost reports in both apps now put a planning figure beside the bill of quantities. A sentence from the new cost_range.yaml says the bill is the contract document and the distribution is the planning figure. borehole_cost_items.csv gains a minimum, a maximum and a spread group for every rate. The likely rate the bill prices is unchanged. The ends come from borehole_cost_spread.yaml, which gives each of thirteen groups of rates sharing a cause a share below and above with its reason. No source is recorded for any of them, and most are wider above than below. Each sampled borehole draws one point per group and its drilling depth from the range of models at the first-ranked point (or the estimate's depth, said so, where no range was sampled). A dry attempt pays siting, set-up and drilling but not the journey from the base. Its price takes the bill's overheads, margin and VAT. The pages give P50 and P80 of a completed borehole, and where the bill and the planning budget fall among the samples. They also give the expected cost per working borehole: the mean completed borehole plus the mean dry attempt for each of the (1 − p)/p dry attempts expected at that point's chance p of a working borehole. For the default Dr Timbo design that is US$ 9,109 and 9,358 against the bill's 8,644, which sits at the 4th percentile because the rates' spreads lean upward. A programme is sampled whole, rates and depth once per programme and dry attempts one by one, with its P50, P80 and attempts. On the Streamlit page it is drawn again at the borehole's depth when a range is sampled later. Both engines draw from the range of models' generator with the same arithmetic, and parity holds short and default runs to the bit. The default of 20,000 samples keeps every figure within half a percent from one seed to the next, at 0.4 s in Python and 33 ms in the browser (90 to 119 ms at a 4x CPU slowdown). Every spread, drawing groups together and independently of each other, and counting a dry attempt's siting and full crew time again all need an engineer's confirmation.

### The value of one more measurement (PLAN.md step 3.5)

Both apps and both reports now say what a second sounding beside the survey's first-ranked point, or a profiling line through it, is worth to the choice of where to drill, in the form "A second sounding beside P1 is worth up to US$ 48 to this decision and costs about US$ 100." The choice is between the first-ranked point and the other point with the best odds (or an unsurveyed site at the prior). Each is priced from the cost distribution's mean completed borehole and mean dry attempt. The value is the expected cost of the best choice now less that after the reading, summed over every combination of the bands in success_evidence.yaml that the measurement could read. The bands are spread among dry and working boreholes as evenly as their likelihood ratios allow; that spread is a choice, not a bound, and the pages say so, since another spread the ratios allow can put the value higher or lower. The pages print the decision with and without the measurement, the readings that would change it, every band with its shares, and what perfect information would be worth. They say plainly that the new reading is assumed independent of the old one, which overstates what a sounding beside the first adds. On Rokel, where both points stand at about 96 percent, a second sounding is worth about US$ 12 against US$ 100, and a profiling line about US$ 7 against US$ 150. The two measurement costs are provisional figures in field.yaml with no recorded source. Parity holds 37 new checks to 1e-9 and word for word. The measurement costs, reading a profiling line as the resistivity class only, the even spread of bands, and taking both places to cost the same to drill want confirmation.

### One way of reporting uncertainty (PLAN.md step 3.6)

Every report now prints its decision numbers in one form, in its executive summary: the value, the band and what the band rests on. These are the drilling depth and odds at the recommended point (at both points where the survey cannot separate the first two), the safe yield and pump intake, and the cost. An example is "Safe yield: 0.391 m3/h (P10 to P90 of the transmissivity, 0.354 to 0.443 m3/h); basis: a block bootstrap of the Cooper-Jacob residuals, …; provisional." The drilling depth is the best fit's, with the P10 to P90 of the depth each sampled model would be drilled to, rounded and cut back as the range's own drilling depth is. The cost is its P50, with the P10 to P90 of the same sample and the P80. Where the design or the seasonal projection has moved the intake, the line prints the moved depth and says in its brackets that the band is the recommendation's: "54 m (the recommendation's setting over a 1 to 4 m dry-season decline, 51 to 52 m)". Where no band can exist yet, the line says why, for example "no band: the range of models has not been sampled at VES-2". Nothing is invented. Every number is labelled provisional, because none has been calibrated against drilled boreholes. The yield used to appear twice: beside an unlabelled assumption envelope, "0.39 m3/h (0.22 to 0.71)", and in the bootstrap's own sentence. Both apps' summaries now give the value once, with the bootstrap band in its labelled form. The key findings that repeated the depth (for one point or a tied pair), the yield and the intake without a band are gone. The readiness gate gains "Decision bands" on the geophysical, pumping, completion, handover and cost reports. A report that prints a number with no band is stamped PROVISIONAL, as it is for a missing GPS fix. So a survey whose range has not been sampled, or a cost estimate with no distribution, is now held back. The worked examples keep their states. The cost curves now shade their P10 to P90. The model panel shades the P10 to P90 of the drilling depth before it is rounded up to the drilling step. The browser's model figure now draws the fan of models, which it used to leave out. The wording is in decision.yaml, and parity holds 78 new checks word for word. Whether the recommended depth should become the P90 once a range is sampled, P10 to P90 rather than P50 to P80 as the cost band, and holding a geophysical report until its range is sampled want the owner's confirmation.

### Reading an elevation model the operator supplies (PLAN.md step 4.1, part a)

Both engines now read GeoTIFF elevation models without GDAL, and the Streamlit Topography tab no longer asks for gdal_translate. The reader takes classic TIFF and BigTIFF in either byte order, strips or tiles, no compression, DEFLATE, LZW and PackBits, the horizontal and floating-point predictors (applied, as libtiff applies them, only with DEFLATE or LZW), 8-, 16- and 32-bit integers and 32- and 64-bit floating point, the first full-resolution image of a file with overviews, GDAL's no-data text and its block leaders. It refuses, each by name in a catalogued sentence, old-style LZW, JPEG, LERC, Zstandard and the other codecs it does not decode, a rotated or control-point grid, a scaled file, a GDAL internal mask (whose hidden cells usually hold 0, which would read as ground at sea level), damaged georeferencing, and a file cut into more blocks than `terrain.max_blocks` (100,000). The published Copernicus GLO-30 tiles are DEFLATE with the floating-point predictor, not LZW as PLAN.md had it; LZW is what GDAL's COG driver and QGIS write by default, and PLAN.md now says so. Python inflates with zlib and decodes LZW a Clear segment at a time in numpy; the browser engine, whose worker must answer synchronously, carries its own inflate, LZW and PackBits decoders, which give zlib's verdict and bytes on every stream tested, corrupt ones included. On the real GLO-30 tile N08 W012, read whole, both engines return all 12,960,000 samples bit for bit as GDAL 3.12.2 reads them, and every column centre within 1.8e-15 degree of GDAL's (tested locally, not in CI; no elevation model is committed). An elevation layer above the reader reads a window around the site rather than the whole file: only the blocks the window meets, from one tile or several joined on one lattice (Copernicus tiles abut; SRTM-format tiles share an edge row, which must agree exactly). Files that do not share a lattice, or come from different products, are refused rather than resampled, and a reprojected (UTM) copy is refused with its coordinate system named. Ground no file covers is a gap, and the read says how much there is. A missing 1-degree tile of a Copernicus or SRTM set is taken as open sea, with no height, only when the full shared edge of every supplied tile beside it is at or below 0 m, because those products publish no tiles for open sea; a missing tile with any land on that edge stays a gap. Heights outside -1000 to 9000 m and infinite values are counted and read as no data. The window is centred on the GPS fix, or on the chiefdom or district without one, and planned in cells from the WGS 84 cell size at its centre, worked out with a polynomial sine and cosine that both engines evaluate to the bit. The analysis window the next part will use is the 10 km radius shown plus a 5 km margin, 983 by 979 cells at 1 arc-second, capped at 2,000,000 cells (`terrain.max_cells`, provisional until part b times the analysis). Reading that window from a synthetic GLO-30-sized tile takes 202 ms from DEFLATE and 403 ms from LZW in Python, and a whole tile 672 ms (`bench/run.py --only terrain`, median of five, `bench/README.md`); decoding LZW a Clear segment at a time makes the LZW read 5.5 times quicker than the loop decoder it is tested against. The source is recognised from the file names together with their georeferencing, and the operator's statement of it wins. A Copernicus tile carries its licence's "produced using Copernicus WorldDEM-30" notice on the figure and its liability sentence under the download, both read from the licence each tile folder carries and recorded word for word in data_provenance.yaml and THIRD_PARTY_NOTICES.md. A renamed tile, a file laid out like one, and an undeclared `.hgt` are credited as files of unstated source. The Streamlit Topography tab takes several GeoTIFF or `.hgt` tiles, kept on disk rather than in the session, draws the map from one window read across them, framed on the whole square asked for (one cell in every few each way, without averaging, when the square is wider than the cap), and shows what the read found. A map drawn from other files, or another declared source, is no longer shown, and loading a project no longer carries over the previous project's elevation model, topographic map, subsurface maps or GeoLibre file. The browser engine reads everything the Python one does, but the browser app has no page for it until part c; both apps say so, in a sentence from the new terrain.yaml catalogue. Parity gains the inflate, geotiff and elevation_window sections, 254 checks (2223 in all), all exact apart from the chiefdom and district label points a window may be centred on, held to 1e-9 as the regional section already holds them; fixtures are served to the page rather than copied, and reference.json grows by 151 KB. 63 synthetic fixtures and their manifest (153 KB), written by a dependency-free builder and checked against GDAL, cover the formats and the refusals; a Node test holds the two readers and the two elevation layers to the same answer on several hundred generated files and windows, and the fuzz suite gains deflate and geotiff generators. Because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. The engine is 118 KB larger, and time to interactive on the throttled profile went from 11.11 s to 11.84 s (median of three cold loads). The plausibility bounds, taking a missing tile as sea by the full-edge rule, refusing projected models and internal masks rather than resampling or applying them, requiring overlapping tiles to agree exactly, the 5 km margin and both caps, crediting an undeclared `.hgt` as of unstated source, and refusing malformed DEFLATE blocks that GDAL would partly read want the owner's or a hydrogeologist's confirmation.

### Terrain analysis in both engines (PLAN.md step 4.1, part b)

Both engines now analyse the window part a reads, and agree cell for cell, though neither app shows the analysis until part c. Each cell is land, sea or a gap. Sea is ground at or below 0 m joined to the edge of the analysed square, so a tidal estuary counts as sea and lines end at its head; a 0 m area meeting land along a straight grid line of 150 cells or more is taken as the 0 m fill a mosaic or clip leaves where it had no data, and read as a gap. Closed hollows are filled to their spill level (a priority flood in the browser, a graph of basins in Python, which give the same surface to the bit), and water leaves each cell for its steepest downhill neighbour (D8, ties going to east, south, west and north before the diagonals), and crosses flats by its distance from higher and lower ground (Barnes et al. 2014). Upslope area is counted in Kahn's order in whole units of 0.01 m², so its sums are exact in any order, and flagged by TauDEM's rule wherever ground beyond the window's edge, in a gap, or under sea from a file of unstated source may drain into it; flagged area is marked, not deleted. Drainage lines start where 0.5 km² drains (`terrain.drainage_area_km2`), carry Strahler's order, are traced over the 5 km margin and cut to the square shown, and are written as GeoJSON with each piece's area, length, order, outlet and contamination, and the number of its cells that were filled or routed across a flat. The surface layers are GDAL's hillshade on Horn's gradients at each row's own cell size, its multidirectional composite lit from 225, 270, 315 and 360 degrees and four panels lit from 270, 315, 0 and 45 degrees; the wetness index ln(a / tan β) by D8, with tan β floored at 0.001; and Evans and Young's profile and tangential curvature at about 90 m. Captions say what each layer can and cannot show. On the real GLO-30 tile N08 W012, in three 10 km windows, 79 to 87 percent of the drainage-line cells were routed across filled hollows or flats rather than by slope; on a surface model, which records canopy and roofs as ground, those are the least certain stretches, so the analysis marks them, the GeoJSON counts them and part c draws them paler. The 5 km margin was checked against an 11 km one on the same windows: no undashed line cell in the square shown appears or disappears, and 0 to 100 of them keep a changed area. The Streamlit topographic map changes tone. Its hillshade measured the azimuth the wrong way round, so its north-west sun shone from the north-east; it is now the same GDAL hillshade, left blank on the edge and beside gaps (where it used to draw a cliff), and drawn on a fixed scale rather than stretched to each window's own range. The slope it reports is Horn's, and the contour interval keeps its rule, now worked in integers. The cap of 2,000,000 analysed cells was kept on the analysis alone (part c, which measures the whole press, lowers it to 1,500,000): on the bench machine an analysis at the cap took 2.79 s (median of five; the default window 1.39 s) and raised the peak memory by at most 279 MB, which with the Streamlit app's idle 159 MB is well under the 690 MB Streamlit Community Cloud gives an app; surfaces built to be hard (a channel winding through the whole window, a tilted plane, a channel that turns at every cell, dead flat ground) took at most 4.3 s and raised the peak by at most 435 MB, still within the rule but with little to spare (`bench/README.md`). The browser is timed in part c. An adversarial review of this part confirmed 21 findings (one high, six medium, fourteen low), and all are fixed here: among them, a valley winding through a window at the cap took 27 s and now takes 3.0 s, and a tilted plane, nearly all of whose cells lie on a line, raised the peak memory by 692 MB and now by 308 MB. Parity gains the terrain section, 112 checks, all exact apart from the wetness index, held to 1e-12 relative (the worst gap measured is 1.2e-16, one unit in the last place, between the two engines' logarithms), and nine formatting cases for numbers too small for a normal float (2344 checks in all); reference.json grows by 96 KB, and nothing else in it moves. The fuzz suite gains a terrain generator, and a committed gdaldem output holds the multidirectional hillshade to GDAL's in every environment, not only where GDAL is installed. The engine is 92 KB larger; because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. Filling rather than breaching on a surface model, the 0.5 km² threshold, sea as ground at or below 0 m joined to the edge, the straight-edge rule of 150 cells, flagging rather than deleting contaminated area, the wetness index and its floor, the curvature spacing, the hillshade azimuths and GDAL's weights, counting a cell in its own upslope area, ties going to cardinals first, Barnes's flats, tinting raises of 1 m or more, and the cap want the owner's or a hydrogeologist's confirmation.

### Terrain pages in both apps (PLAN.md step 4.1, part c)

Both apps now draw the terrain analysis. The browser app's Site & maps page gains a "Topography and terrain" card (`#/site/terrain`). Tiles are dropped or picked (any file, so that a phone's picker does not grey out `.hgt`), and each is listed at once with its size, the source recognised and any refusal or question; the source can be declared, and the radius (1 to 50 km) and the drainage threshold (0.05 to 100 km²) start from the settings. *Analyse the terrain* reads only the blocks the window needs, in a few large reads per file, and hands them to the engine worker, which reads the window and analyses it while a bar names each stage and offers Cancel. The four figures follow the read report with the engine's own captions, each downloadable as PNG or SVG, with *Drainage lines (GeoJSON)* beside them, and a new drainage threshold re-traces the lines, the relief figure, its captions and the GeoJSON on the page from the core the worker handed back, without analysing again. Nothing is saved with a project: loading one, opening a sample, taking the saving over from another tab or *Reset everything* drops the tiles and the figures, and a new file or another source drops the figures. The Streamlit Topography tab gains the same button, progress under the same stage names, the same four figures and captions and the same downloads, each run's files kept in a folder of their own so that a run stopped part-way never mixes its figures with the result on show; it keeps no analysis arrays between runs, analyses one `.asc` or `.xyz` grid as well, and a project load now also takes the outgoing site's maps off the Overview's deliverables. The two apps draw the figures alike: the relief shaded by the multidirectional hillshade, with contours, ground the fill raised tinted, assumed sea hatched and gaps grey, and drainage lines widening with their order, paler where routed across a flat or a filled hollow and dashed where their area is uncertain; the wetness index, with every cell that may take water from beyond the window lightened; profile and tangential curvature; and the shading from four directions. Each figure carries the credit and the surface caveat inside it, so that a downloaded figure keeps them. In place of part a's notice, both apps say that ESRI ASCII and XYZ grids, the wider map and the ground profile are in the Python app only, and that the reports do not carry the terrain yet. A worker that stops while it works, or runs out of memory, ends the run with a sentence that suggests a smaller radius rather than running it again on the page; a device that reports 2 GB of memory or less is asked before it analyses more than 1,000,000 cells; and the worker is stopped once it has answered, which took a quarter off a press's memory peak at the default window (314 to 232 MB, median of nine presses each, alternated).

The cap comes down from 2,000,000 analysed cells to 1,500,000, by the bench rule's own steps, so the planner now offers 13.6 km at 1 arc-second where it offered 16.5 km. Part b had judged the cap on the analysis alone; part c measured the whole press in the running Streamlit server, the read, the analysis and the four figures together. At 2,000,000 cells a first press took the server to 679 to 729 MB and a second to 747 to 779 MB, against the 690 MB Streamlit Community Cloud gives an app; at 1,750,000 a second press reached 751 MB; at 1,500,000 every first press (535 to 543 MB) and second press (600 to 669 MB) stayed under it. Drawing the Python figures from 8-bit colour rather than float64, which leaves every PNG byte for byte as it was, and handing freed memory back to the system after each press had already taken about 140 MB off a first press at the old cap and 320 MB off a second. At the new cap CPython analyses the window in 2.04 s (median of five; the default window 1.21 s), and a browser press takes 3.99 s with the worker, adding 349 MB to the tab at its peak, and 17.7 s on the page at a quarter of the CPU's speed; at the default window 2.73 s, 233 MB and 12.0 s. An ad hoc Pyodide run analysed the old cap's window in 4.1 s. Part c's scripts add 67 KB to the first load, and time to interactive on the throttled profile went from 12.40 s to 12.58 s (median of three cold loads, back to back); because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. On the real tile N08 W012, tested locally and not in CI, both engines give the same analysis of the default window (1.37 s in Python, 1.28 s on the browser's page), with 87.4 percent of its drainage-line cells routed across flats or filled hollows. The fill caption now says "less than 1%", with the count, where a few cells were raised rather than "0.0%", and an empty window's refusal says how far it reached each way: parity gains 12 checks for the two sentences (2356 in all), and the browser's smoke suite 53 for the terrain pages (333). An adversarial review of this part confirmed 31 findings (nine medium, 22 low), and all are fixed here. Tested in headless Chromium only. Lowering the cap to 1,500,000, the 2 GB question at 1,000,000 cells, the figures' styling, saving nothing with a project until step 4.4, offering PNG, SVG and GeoJSON but no GeoTIFF of the layers, failing a stopped terrain job rather than running it again on the page, and the Streamlit tab's needing the button pressed again for a new threshold want the owner's confirmation.

### The fuzz suite tells a knife edge from a divergence

Main's nightly fuzz job went red on 13 and 14 October with nothing changed: on each night `test_inversions_agree` drew a VES sounding the two engines inverted differently. Neither was a defect of the port. On the first, no layer count reaches the 10 percent target and the parsimony fallback takes the simplest model within 1.15 times the best fit; one of the browser's three-layer searches stopped inside that line (10.31 percent) and Python's two stopped outside it (11.90 and 12.73), so the browser reported three layers and Python four. A one-ulp change to 5 percent of Python's quadrature weights, as another libm's sin and cos would make, gives Python the browser's three-layer model in two draws of eight. On the second, both engines fit a thin resistive top layer the data do not determine (Python rates its resistivity uncertain by its cap, a factor of 10) and stop in a valley along which the fit still improves, Python at 10,519 ohm-m and the browser at 18,763. The same `gwt-core.js` stops at 10,518 in Node 22, whose `Math.sin`, `cos` and `pow` differ from Chromium 141's in the last bit, and at 10,507 or 10,572 in Chromium when one of its starting values moves by one ulp. Such an answer is one neither engine can be held to, by the other or by itself. So a generated inversion the engines disagree on is now put to the engines themselves: both invert the sheet again with every reading moved by one ulp (up, down, and alternately each way), and where one engine's own answer moves by more than parity's 1e-3 at a place the two disagree, the case is a knife edge. It is printed in the log, written to `tests/fuzz/knife-edges/found/` (which CI keeps as an artifact on a green run too) and does not fail the run. A divergence neither engine moves at still fails: with the browser's Numerical Recipes Bessel functions and old interp edge put back, every one of the regressions they caused that diverges under the generated-inversion rules is still judged a divergence. The two sheets are kept in `tests/fuzz/knife-edges/` with what the engines were choosing between, and `test_knife_edge` replays them on every run: while the engines disagree on one, the check must still call it a knife edge. The rules that leave out unconverged and poorly resolved models are unchanged. The engines and the drawn sample are unchanged.

### Lineament candidates in both engines (PLAN.md step 4.2, part a)

Both engines now find lineament candidates in an analysed terrain window, straight valleys and ridges and valleys that line up, and agree on them to the bit. Neither app draws them yet; part b adds the figure and the rose to both. The new module is `groundwater.mapping.lineaments`, with `lineamentCandidates`, `lineamentCaptions` and `lineamentGeoJson` in the browser's engine. The heights are smoothed with binomial passes about 65 m across (9 passes at 1 arc-second); unsmoothed, the canopy a surface model records broke every edge into pieces of a few cells. The smoothed relief is shaded from the four panel azimuths (270, 315, 0 and 45 degrees, the sun at 45 degrees), and the gradients of the four hillshades are added up as a structure tensor whose principal direction runs across the line. Cells where the tensor's strength peaks across the line are its centreline (Canny's thinning). Each centreline cell is weighed against the mean strength within 1.5 km of it, so that a valley on the plains counts as well as one in the hills, and the strongest 40 percent of those in the square shown are kept. A cell where the ground bends by less than 0.1 per km across the line is on no line, which stops the weighing from drawing lines on a plane. A cell is a valley or a ridge by the sign of that bend. Neighbouring cells of one kind whose directions differ by no more than 30 degrees make a line, each line is cut into straight pieces until no cell lies more than 90 m from its piece, pieces of one kind that line up (within 10 degrees and 90 m, across a gap of up to 300 m) are linked into one candidate, and candidates at least 600 m long are kept, cut to the square shown. Their strikes are drawn up as a rose of 10-degree bands, by length and by count, for valleys and ridges apart. The captions say the candidates are "inferred from terrain, not confirmed by geophysics" and name what else draws a straight line (a fracture zone, a contact, a dyke, a road, a field boundary), and the GeoJSON carries each candidate's kind, length, strike, the pieces linked into it and whether the square shown cut it.

Two simpler methods were measured and dropped. Edges taken from each hillshade alone favoured the strikes across the panels' light: on random terrain with no preferred direction their rose showed a 90-degree pattern of amplitude 0.10, about five standard errors. Straight runs of the D8 drainage lines, which can only step along rows, columns and diagonals, showed amplitudes of 0.55 to 0.59, ten to twenty standard errors. On twelve such terrains (six, and each turned by 90 degrees) the tensor's 529 candidates give harmonics of 0.029, 0.019 and 0.037 at periods of 180, 90 and 45 degrees, each under one standard error (0.044), and a slow test holds them under 0.1. Ten valleys planted at known strikes in each of three fractal terrains were all found: 8 m deep in 60 m of relief, each strike within 0.8 degrees of the planted one; 4 m deep, within 3.8; 8 m deep in 150 m of relief, within 6.9. The same windows held 240 to 480 other candidates, which is what the relief itself draws and why they are candidates. Every number the method uses is worked out in both engines with additions, multiplications, divisions and square roots in a fixed order, sums of whole numbers, and Cephes' arctangent and the engines' own sines and cosines as polynomials, so that the strike, which decides a candidate's band of the rose, is the same to the bit.

On the real tile N08 W012, tested locally and not in CI, the default window holds 187 candidates (83 valleys and 104 ridges, 18 of them linked from more than one piece, 149 km in all), the same in both engines field by field, with the captions word for word and the GeoJSON (41,407 characters) to the character. Python finds them in 0.89 s (median of five) and the browser's page in 0.81 s (median of three). At the cap on cells the same tile holds 399, in 1.48 s in Python. Most of the land can be a line cell, and taking the thinning over the whole grid at once raised the peak resident set by 214 MB at the cap; it is now done a band of rows at a time, which gives the same cells, and the peak rises by 90 MB. On the bench's synthetic tile, which holds few straight lines, `bench/run.py` gives 0.55 s on the default window and 0.90 s at the cap, and `bench/terrain_memory.py` now also reports what finding the candidates adds to the peak: 60 MB at the cap, against the analysis's own 198 MB. The browser's memory was not measured; part b times and measures the whole press. Parity gains a lineaments section of 85 checks (2441 in all): the small terrain windows with the defaults and with settings fine enough to find candidates a few cells long in them, the settings both engines refuse in the same words, and a window generated in both engines with five valleys and ridges cut into it, with the defaults (12 candidates) and with every centreline cell kept (82). reference.json grows by 100 KB, and nothing else in it moves. The fuzz suite's terrain windows draw lineament settings in four windows of five and hold the candidates, summary, roses, captions and GeoJSON exact; 3,000 windows agreed. A Node test holds sixteen seeded windows to the bit, some analysed in float32 as the apps analyse, and the real-tile acceptance gains the tile's candidates. The engine is 27 KB larger; because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. Every setting (the smoothing, the 1.5 km square, the share kept, the curvature floor, the turn, the straightness, the piece and candidate lengths and the linking rule), shading from the four panel azimuths at 45 degrees, taking ridges as well as valleys, and weighting the rose by length want a geologist's confirmation.

### Lineament candidates drawn in both apps (PLAN.md step 4.2, part b)

Both apps now draw the lineament candidates part a finds, as the fifth and sixth terrain figures, each with the engine's captions under it, and offer them as GeoJSON beside the drainage lines. The Streamlit Topography tab looks for them after the analysis, under the stage "Looking for lineament candidates", and the browser card's worker does so after its own, as the last 15 percent of the bar. Neither depends on the drainage threshold, so a new threshold on the card leaves them as they are. The map (`terrain_lineaments.png` and `.svg`) draws each candidate as a straight line from its start to its end over the multidirectional hillshade in grey, lightened 40 percent towards white, valleys in blue and ridges in orange, keyed in the upper left, with the site, the scale bar and the north arrow of every terrain map. The rose (`terrain_rose`) draws valleys and ridges as two roses on one scale: each 10-degree band twice, opposite itself, because a strike has no way along it, and each petal's area rather than its reach in proportion to the length in its band, so that the longest band does not look longer than it is; the rings, at a quarter, a half, three quarters and all of the longest band, name their lengths, and each rose is headed with its count and length. The rose is drawn only where there is a candidate. Both figures carry inside them, under the credit, "Lineament candidates are inferred from terrain, not confirmed by geophysics." and the caveat, so that a downloaded figure keeps both. The candidates download as `lineament_candidates.geojson` in both apps. The rose's caption now says how it is drawn, and `lineament_captions` and `C.lineamentCaptions` give the note and the roses' headings too, held to parity word for word: reference.json's lineaments section moves with them, and nothing else in it. On the real tile N08 W012, both apps draw the same 187 candidates in 35 bands.

A whole press at the cap (13.6 km, 1,478,647 cells) in the running Streamlit server, three fresh servers on main and three on this branch, alternated, measured as part c measured it: a first press now peaks at 554 to 580 MB (main 533 to 606 MB) and a second, from another session, at 624 to 658 MB (main 605 to 628 MB), all under the 690 MB Streamlit Community Cloud gives an app, so the cap holds; a first press takes 11.1 to 11.6 s from the click to the last download (main 9.6 to 10.1 s). The bench's synthetic tile holds few straight lines, and finding the candidates on the real tile raised the peak by about 12 MB more, so a press on real ground may come that much closer (`bench/README.md`). In the browser, `bench/web.mjs --only terrain` (two runs of three presses at each size, beside four runs on main the same day) gives a press at the cap 5.0 to 5.1 s with the worker (main 4.2 to 4.4 s), adding 370 to 372 MB to the tab at its peak (main 333 to 354 MB), and 20.4 to 20.5 s on the page at a quarter of the CPU's speed (main 17.0 to 17.2 s); at the default window 3.3 to 3.4 s, 266 to 273 MB and 14.1 s (main 2.8 to 2.9 s, 228 to 246 MB and 11.8 to 12.2 s). The worker builds the page's answer first and lets go of the analysis's other layers before it looks for the candidates, which read only the heights, the classes, the row metric and the settings: looked for beside those layers, they took the peak at the cap to 446 MB. The browser's smoke suite gains 5 checks for the two figures and their download (338 in all) and checks the rose on the card, on a synthetic tile now cut by a straight valley; the Python app's press test and a figure test cover the same in Python. Because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. The colours, drawing a candidate as a straight line from end to end, the rose of equal area with both kinds on one scale, the relief lightened under the lines, and leaving the rose out where there is no candidate want the owner's confirmation.

### A survey plan across the lineament candidates (PLAN.md step 4.3)

Both apps now lay a survey plan round the site as the seventh terrain figure, in the same press as the lineament candidates, and offer it as GPX and as a GeoLibre project. The plan is laid within the 500 m service radius the water point check uses (`waterpoints.SERVICE_RADIUS_M`), since a borehole further out does not serve the community. The candidates that come within it are taken nearest first. Each gets a profiling line at right angles to its strike through its point nearest the site, which makes a line through the site unless the candidate ends short of it: 400 m long, or as long as the radius leaves room for, a station every 10 m, the crossing a station of it and as near the middle as the radius allows. A candidate that a line already laid crosses at right angles (strikes within 20 degrees) gets no line of its own, and at most two lines are laid. Each line gets three soundings: on its candidate, and 50 m along the line to either side, because a candidate is placed from the terrain only to within a cell or two. A sounding is a place a borehole may go, so each is kept the distances of `site_separation_distances.csv` from what the page maps: a mapped water point by what it is (a borehole 50 m, a dug well 20 m, surface water 20 m as a stream, any other water point 10 m), the drainage lines 20 m, standing for the streams, and the sea 1,000 m. A sounding inside a ring moves along its line to the nearest place clear of every ring, no further than 20 m. Where there is none, it is left out, and the caption says how many and why. The table's other rows (latrines and soakaways, buildings, refuse dumps and burial grounds) are on no map here, and the caption says to check each peg for them on the ground. Each sounding's AB/2 series is the VES co-pilot's own (`ves_survey_plan`) for a 60 m target by the depth-of-investigation rule, AB/2 = 120 m, its 240 m spread laid along its candidate's strike. Where no candidate comes within the radius, one line runs through the site across the strike of the 10-degree band holding most of the candidates' length, and no sounding is proposed. Where the square shown holds no candidate, or the site has no GPS position, the caption says why there is no plan.

The new module is `groundwater.mapping.survey` (`survey_plan`, `survey_plan_captions`, `survey_plan_gpx`, `survey_plan_geojson`), with `C.surveyPlan`, `C.surveyPlanCaptions`, `C.surveyPlanGpx` and `C.surveyPlanGeoJson` in the browser's engine. Everything is worked out in the candidates' own frame, with the site and water points placed in it as `lineament_lonlat` places a point back, from additions, multiplications, divisions, square roots, floors and ceilings in a fixed order and the engines' polynomial sine and cosine. So the two engines lay the same plan to the bit, and write the same GPX and GeoJSON bytes. The figure (`terrain_plan.png` and `.svg`) draws the plan over the lineament map's grey relief, cut to a square a quarter wider than the service radius each way. It shows the drainage lines, the candidates, the service radius, each mapped water point's ring, the lines with their stations, and the soundings numbered with their spreads dashed along the strike. Inside it, with the caveat, it says that the candidates are inferred from terrain, not confirmed by geophysics, and that every peg is a proposal to check on the ground. A table under it lists each sounding's position, line and distance along it, and what it was moved clear of. The GPX (`survey_plan.gpx`) holds a waypoint at the site, at each sounding and at each line's ends, and each line as a route with a point at each station, named by its distance along the line, so a phone's GPS can walk the team to each peg. The GeoLibre project (`survey_plan.geolibre.json`) takes the plan's GeoJSON apart into its layers over the candidates and water points near the site, and opens on the service radius. The water points are those loaded on the Water points page when the terrain is analysed. In the browser a new drainage threshold lays the plan again from the lines it traces, as a press in the Python app does. Seven settings join `terrain`: `survey_lines`, `survey_line_m`, `survey_station_m`, `survey_flank_m`, `survey_move_m`, `survey_cross_within_deg` and `survey_target_depth_m`, each refused in the same words in both engines when out of range.

On the real tile N08 W012, a site at its centre gets two lines, across two ridges 44 and 113 degrees in strike, with three soundings each. Python lays the plan in 0.18 s at the default window and 0.21 s at the cap, and the browser's engine in 4.1 ms (median of seven, Node 22). The press measure in `bench/README.md` sets no site and its synthetic tile has no candidate near its centre, so the rule was checked again on the real tile with the site at its centre, at the cap, three fresh servers on main (3b9d307) and three on this branch, alternated. A first press peaks at 554 to 579 MB (main 560 to 602 MB) and a second, from another session, at 645 MB (main 650 to 673 MB), all under 690 MB, so the cap holds. A first press takes 17.4 to 18.3 s from the click to the last download (main 16.0 to 16.8 s). Drawn with `st.dataframe`, the table of soundings loaded pandas, which the server kept, and every second press went over the rule (728 to 768 MB); the table is now Markdown. `tests/test_survey_plan.py` holds each rule on candidates, water points, drainage lines and sea placed for the purpose, and the figure, the GPX, the GeoJSON and the GeoLibre project. It also runs the browser's engine in a Node vm on 40 seeded cases mixing candidates, water points of every kind, drainage lines, sea, gaps, an offset square and changed settings, and holds the plan, captions, GPX and GeoJSON to the Python ones to the bit. Parity gains a survey plan section of 23 checks (2464 in all), laid on the generated window L1 analysed in each engine round six sites. They cover moves, both reasons for leaving a sounding out, a candidate given no line because another's line crosses it, a shortened line, the line across the strike, a square that does not hold the radius, a depth past the field schedule's longest spacing, and five refused settings. Only that section is added to reference.json. The browser's smoke suite checks the plan on the card both ways: across the strike where its synthetic tile's valley is found only beyond the radius, and across the valley with the site moved beside it, with its table and both downloads. The Python app's press test checks the figure, table, GPX and GeoLibre project on the committed Copernicus pair. Because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. The 500 m radius, the line's length and stations, the flank distance, the 20 m move, the 20-degree crossing rule, the 60 m target, laying the spread along the strike, the separation distances taken from the table, the drainage lines standing for streams, and proposing no sounding beforehand on a line across the strike all want a hydrogeologist's confirmation.

### Sums added as the browser adds them

Main's nightly fuzz job went red on 17 October on a laboratory sheet with chromium 0.064, copper 1.65 and arsenic 0.029 mg/L. Its Hazard Index is 4.55 exactly, a tie at one decimal: Python's flag said 4.5 and the browser's said 4.6. From Python 3.12 the built-in `sum()` compensates a sum of floats, and it came to 4.55; the browser adds the hazard quotients one at a time and came to 4.550000000000001, as Python 3.10 and 3.11 do. So Python's answer hung on its version. The new `utils.sum_in_order` adds one value at a time from 0, as `costing/distribution.py` and `mapping/lineaments.py` already did. Every built-in `sum()` of floats that `gwt-core.js` mirrors now goes through it: the Hazard Index and the ionic balance's cation and anion totals, a cost estimate's direct cost and a programme's dry-attempt cost and transport rate, a design's screen length, the pumping test's step volume and step durations and the spread's residual mean and slope sums, the field kit's timed-container mean, the VES interpretation's aquifer thickness, the portfolio's mean yield and cost per metre, the study-area map's centre, and a payment certificate's totals. The browser's certificate now adds each line's variation as a difference, `t + (a - c)` rather than `t + a - c`, as Python does. The sheet is kept as `tests/fuzz/regressions/quality-hazard-index-half-tie.json`, and `tests/test_indices.py` holds the flag at 4.6 on every Python version. Python's float sums that the browser does not mirror, such as the Depth Spine's Piper percentages, the iso-resistivity map's geometric mean and the regional maps' label points, are unchanged. Because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened.

### What a desk study says, in both engines (PLAN.md step 4.4, part a)

Both engines now put together the content of a desk study: what is known of a site before anyone travels to it. Neither app offers it yet; part b lays it out as the eleventh document and puts a button for it on Site maps in both apps. The new module is `groundwater.desk_study` (`desk_study_content`, `desk_study_terrain`, `site_ground`), with `C.deskStudyContent`, `C.deskStudyTerrain` and `C.siteGround` in the browser's engine. Its words are in the new catalogue `data/text/desk_study.yaml`. Like the field kit's, the content is plain data that the two document writers will only lay out, and every number in it is already written as text, so parity compares the content whole. It holds:

- **The site:** its names, its position in degrees and in UTM, for the cover.
- **The stamp**, "PRE-FIELD DOCUMENT - NOT A SURVEY RESULT", with a lead that says nothing in it was measured on the ground. It goes on every desk study: a desk study is never a certification, so it takes no readiness gate.
- **The ground:** the USGS unit and the BGS aquifer class under the site, with the formation and what the rock means for a borehole from the crosswalk the map key uses (so the Freetown Complex is named as such, not as the USGS layer's "Paleozoic Igneous"), and the class's published yield range from the prior table.
- **The terrain and its lineament candidates,** where an elevation model was analysed: the count, the length and the 10-degree band of strike that holds the most of it, how many come within the 500 m the site serves, and the figures' captions. `desk_study_terrain` keeps this from the press beside the figures, since neither app keeps the analysis, with the position the plan was laid round; a desk study whose site has moved more than a metre since leaves the terrain out and says to analyse it again.
- **The water points** the Water points page loaded, within the radius it searched: how many are working, not working or of unknown status, whether a working improved source lies within the 500 m the site serves, the improved sources recorded as not working there (rehabilitation candidates), the nearest working one, and a table of the nearest 15. The WPdx+ inventory carries no depth or yield, and neither reader reads one; the content says so and points to the earlier projects.
- **The earlier projects** in the portfolio loaded within 5 km, nearest first, with their status, depth, safe yield and water quality, and how many were drilled and successful; a project with no position is counted and left out.
- **The odds from the prior alone:** the new `prior_odds` (`C.priorOdds`) is `success_odds` with no evidence to move it, so its headline and its prior sentence are step 3.3's own (`odds_prior_text`, factored out of `odds_point_text` with no change to the geophysical report).
- **The survey plan's** caption, its lines (bearing, length, ends) and its soundings (line, distance along it, position, what is said of it).
- **What the field visit is to check:** the rock, the position where there was none, the sources that may already serve the community, the broken ones, what draws each candidate a line crosses, and each peg.
- **The references,** including a new WPdx+ entry in `references.yaml`.

Each section says what it waits for where something is missing: no position, no water points loaded, no portfolio loaded, no elevation model analysed. Parity gains a desk study section, 14 checks (2478 in all). Each engine keeps what a desk study says of each of L1's six survey plans from its own analysis of the window, and the content of eight cases is held whole:
- inland, with water points and earlier projects;
- Freetown, with nothing near;
- no position;
- L1's two lines with more water points than are listed;
- L1's line across the strike;
- the site moved off L1's plan;
- the Bullom Group;
- surface water, where the placeholder prior applies.

`tests/test_desk_study.py` holds each rule, and holds the browser's engine to Python's in a Node vm on 60 seeded cases, with a test that they reach every rule. Because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. The 5 km, the 15 water points listed, the stamp's words, the checks and showing the prior before any survey want the owner's confirmation.

### The desk study, the eleventh document (PLAN.md step 4.4, part b)

Both apps now write the desk study: *Build the desk study (.docx)*, at the foot of the Site maps page in the Python app (under the four tabs) and as the last card of the browser's Site page. `reporting.desk_study.build_desk_study_report` and `GWT.docx.deskStudyReport` lay out part a's content and nothing else:

- the cover, with the site's names and its position in degrees and UTM;
- the stamp, "PRE-FIELD DOCUMENT - NOT A SURVEY RESULT", on the page after the cover on every copy. It is the new `pre_field_stamp` / `preFieldStamp` in each engine's report builder, which no readiness takes away;
- the table of contents and the executive summary;
- the area maps every report opens on, with the aquifer and geology maps;
- the seven sections, each with its paragraphs, figures, tables (at set column widths) and bullets;
- the references.

**Where the terrain figures come from.** In the Python app they are the PNGs the last *Analyse the terrain* press drew, and the press now also keeps what the desk study says of the terrain (`desk_study_terrain`, a few kilobytes) beside them, since the analysis is not kept. The browser draws the relief, the candidates, their rose and the plan again for paper, one at a time, from the analysis on show, without touching the card's own figures. A figure the content names that was not drawn is left out, and its section's text stands. Water points come from the Water points page, within the radius it searched; earlier projects from the files the Portfolio page holds. The page's portfolio reader is now `shared.project_summaries`, shared with the desk study. A site with no name is "an unnamed site" (the new catalogue entry `desk_study.where_unnamed`, in both engines). The terrain card's note now says the relief, the candidates and the plan go into the desk study and the other reports carry none of the terrain yet.

**Memory.** The desk study peaks at 360 to 496 MB in the Streamlit server at the cap, far under the 690 MB rule, and takes 3.2 to 3.8 s. The rule's two presses still hold on the branch (first press 559 to 608 MB, second 643 to 657 MB, three servers). But a desk study leaves the server 50 to 70 MB higher, and a second press from another session after one can go over the rule: 703 MB in one of five servers. The page's existing *Generate area maps* button does the same, and worse (702 to 731 MB in three of three), since it draws the same maps; `bench/README.md` has the table. Python-docx is imported only when the button is pressed, so a page shown without it does not load it.

**Tests.** `tests/test_desk_study.py` adds three tests:
- the document laid out in the content's order, the stamp after the cover, the figures placed where they were drawn, and the tables;
- a document with no terrain and no position;
- the unnamed site.

The seeded browser cases now include unnamed sites. `tests/test_app.py` presses the terrain analysis, then the desk study, on the committed Copernicus tiles and reads the document back; it also builds one with no elevation model. `smoke.mjs` builds it beside the valley and reads it back for the stamp, the terrain, the plan's soundings and the figures, and has the site moved off the plan leave the terrain out (342 checks). README counts eleven documents, and the user guide's Site maps section describes the desk study.

### A ledger of predictions and outcomes (PLAN.md step 5.1, part a)

Both engines can now keep what a survey predicted at each point beside what the borehole drilled there found: `groundwater.ledger` and its twins in `gwt-core.js` (`C.surveyPredictions`, `C.completionOutcome`, `C.recordPredictions`, `C.attachOutcome`, `C.poolLedgers` and the rest), with the new catalogue `data/text/ledger.yaml` and the setting `ledger.pair_within_m` (50 m, provisional). It is not the Depth Spine's sign-off ledger. Neither app writes into it yet; part b records the predictions, asks which point was drilled where the log does not say, shows the comparison and pools it on the Portfolio page.

- **One entry for each survey point.** Its prediction is the depth to basement and its band over the models that fit, the water-bearing zones and their thickness, the drilling depth and the band the reports print, and the chance of success with its prior, status, sample size and calibration, as plain numbers.
- **Predictions are kept as recorded.** One is replaced only while the project holds no completion, and `before_outcome` says whether it was recorded before drilling, so a prediction written afterwards is never read as a forecast. A point no longer in the survey keeps its entry.
- **Outcomes are current.** The outcome is worked out again from the project's completion: the depth to basement (the top of the log's first band of basement rock, in the class table every drawing uses), the bands of rock, the water strikes, the total depth, the tested safe yield and its band, and whether it succeeded. Success is the odds' own where a pumping test says (a tested safe yield of at least `odds.success_yield_m3_per_h`, decided on the yield as worked out, not as rounded). Without a test, a status the portfolio reads as unsuccessful is a recorded failure, quoted in the driller's word since "abandoned" and "collapsed" are not "dry", and "successful" is the driller's word, not a test; `success_basis` says which.
- **Pairing.** The outcome goes to the point a person chose, else the nearest point within 50 m of the log's position (each read in its own UTM zone), else the survey's only point. Never the recommended point by default: a wrong pairing would mislead the calibration that learns from the ledger.
- **Pooling.** An entry's id is a hash of the point's name, place and position to the metre, so two copies of one project count once in a portfolio, the copy with the outcome kept. The pooled table lists the drilled points; the rest are counted.
- **Schema 2.** Both apps' project files carry the ledger at their top level and write `schema: 2` (the browser's said `version: 1`). `project_io.migrate_payload` and `C.migratePayload` bring a file up one schema at a time, and a schema-1 file opens with an empty ledger. The schema was raised, where the saved inversions and the photographs came in as keys an older toolkit ignores, because the ledger is a record: an older toolkit opening a schema-2 file now warns that it does not restore everything, rather than dropping the record on its next save without a word. The browser now warns too, as the Python app did. `.inf` or a word where the schema belongs reads as schema 1. A hand-edited ledger is cleaned rather than raised (`clean_ledger`): a number written as text is not read, an entry with no id, point or prediction is left out, and untold timing is taken as recorded after drilling. A load always replaces the session's ledger with the file's.

**The browser reads a Streamlit file as Python does.** The browser's YAML reader, which the Portfolio page uses for Streamlit project files, read a list in a list (`- - 8.0`, as PyYAML writes the ledger's zones and bands of rock) as text; read escapes such as `\xE8` and `\u2013` as written, so a community with an accent came out `Kp\xE8t\xE8ma`; dropped a line of a long quoted string that began with `#` and joined the lines of one PyYAML had broken with a backslash wrongly; read `1e3`, which YAML 1.1 and PyYAML hold to be text, as a number; and read a deeper line holding `key: value` as more of the value above it, where PyYAML refuses the file. It now reads every escape PyYAML writes in double quotes and folds quoted strings as YAML does. It also reads a key with a colon in it, takes numbers as YAML 1.1 does, and refuses what PyYAML refuses. `tests/test_web_yaml.py` holds it to PyYAML on 400 generated documents.

Parity gains a ledger section, 12 checks (2490 in all):
- predictions over three kinds of point, four kinds of range and with and without odds (24);
- outcomes over four logs and six tests, and two at a wider success yield (26);
- three scenarios of recording, re-recording, pairing, choosing and attaching, step by step, one of them across the zone 28/29 boundary;
- 92 sets of the comparison's words;
- seven hand-edited ledgers;
- pooling over five files;
- point ids, with a half metre;
- ten schema reads and migrations;
- the Rokel survey's predictions from the browser's own inversions;
- a ledger read out of a Streamlit project file, with an escaped name and a long status PyYAML folds.

`tests/test_ledger.py` (106 tests) holds each rule, the project file's round trip and migration, and the browser's engine to Python's in a Node vm on 60 seeded cases, with a test that they reach every rule. `smoke.mjs` saves and opens a project with a ledger, a schema-1 file and a later one (344 checks); `test_app.py` loads a project with a ledger and then one without. Because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. The 50 m, counting an abandoned or collapsed hole as a recorded failure, and leaving the recommended point out of the pairing want the owner's confirmation.

### The ledger in both apps (PLAN.md step 5.1, part b)

Both apps now write into the ledger and read it back:

- **Recording.** *Predictions and outcomes*, on the Geophysics (VES) page of the Python app and as a card on the browser's VES page, below the drill-target suitability, records each point's prediction with *Record the survey's predictions*, from the interpretations, the range of models where one was sampled and the odds on show. Building the geophysical report records them too, as the report is issued. A recording made while the project holds a drilling log is marked as made after drilling, and keeps every forecast recorded before it; the page says how many it kept.
- **The point drilled.** *Point drilled* chooses the point the borehole was drilled at, or leaves it to the drilling log's position. Where neither pairs it (a log with no position and more than one point), the page says so and asks.
- **The comparison.** For the drilled point the page shows how it was paired and the four rows of `entry_rows`: depth to basement, water, drilling depth and the chance of success, each predicted beside found; under it, every point recorded, when, and whether drilled.
- **Saving.** The project file carries the ledger with the outcome attached as the project then holds it (`shared.current_ledger`, the browser's `currentLedger`), so a corrected log or a later pumping test corrects it. A point is recorded under the project's community and district, or the survey's where the site details leave them blank, so a re-saved copy keeps its ids.
- **The Portfolio page** pools the ledgers of the files it is given (the Python app's `shared.project_files` now reads each file's summary and ledger in one pass), with the summary sentence, the table of drilled points, and *Download the pooled ledger (.json)*, the same file from either app. *Add this project* and *Start from the open project* in the browser add the open project's ledger with its summary.

`tests/test_app.py` records the Rokel survey, loads Dr Timbo's log (which carries no position, so the page asks), chooses the point, records again and builds the report, and pools two copies of one project and another on the Portfolio page. `smoke.mjs` does the same in the browser (347 checks). The user guide's sections 10a and 11 describe it.

### The calibration in both engines (PLAN.md step 5.2, part a)

Both engines can now score the forecasts in a pooled ledger against what was drilled. The new module is `groundwater.calibration` (`depth_scores`, `odds_scores`, `hit_rates`, `calibration_content` and `binomial_range`), with `C.depthScores`, `C.oddsScores`, `C.hitRates`, `C.calibrationContent` and `C.binomialRange` in the browser's engine and the words in the new catalogue `data/text/calibration.yaml`. Neither app offers the report yet; part b draws its two figures, lays it out as a document in both apps and puts it on the Portfolio page.

- **Only forecasts are scored.** The band and the odds are judged on the predictions recorded before drilling. One recorded afterwards may have been made knowing what the borehole found, so it is counted and left out. The hit rates count every drilled point, since a rate does not rest on when the prediction was written.
- **The band.** A borehole is judged against its P10 to P90 band where it found basement, or where it stopped below the band's P90 without finding it; one that stopped higher, or had no band, is counted and not judged. A calibrated band holds about 80 percent. The report gives the range a calibrated band's count would fall in at least nine times in ten on as many boreholes, the 5th to the 95th percentile of a binomial at 0.8 (6 to 10 of 10, 20 to 27 of 30). By it the band reads as calibrated, too narrow or off centre (with how many fell above and how many below), or wider than the ground needs. It also gives the mean of the depth found less the best fit's, and the mean distance between them.
- **The odds.** The Brier score (Brier, 1950) over the forecasts whose outcome is known, beside the score the prior alone would have had and the improvement between them; the reliability diagram's bands of forecast chance, each with its forecasts, their mean chance and the share that succeeded (Murphy and Winkler, 1977); and how many outcomes rest on a pumping test, a failure the driller recorded or the driller's word of success. A chance outside 0 to 1 in a hand-edited file is not scored.
- **Hit rates** by geology unit (the BGS class and the USGS unit the odds read), survey team and contractor: the boreholes drilled, successful, not and not known, the rate, and the mean chance forecast beside it. Names are grouped as written, their white space tidied, and listed most drilled first, then letter by letter as Python orders them; the browser compares code points rather than UTF-16 units, which order a letter beyond the Basic Multilingual Plane differently.
- **Too few to judge.** Below `ledger.min_boreholes` (10) boreholes judged or forecasts scored, the band and the odds say there are too few boreholes to judge and give the counts, and a group's hit rate needs `ledger.min_group` (5) known outcomes. `ledger.reliability_bins` (5) sets the bands. All three are provisional.
- **The ledger names who.** Each prediction now records its survey team, `survey_team`: the field supervisor its own VES sheet names, as the geophysical report prints it over the sounding, else the project's. Each outcome records its `contractor`: the project's drilling contractor, else the log's, as the site details win over every sheet in the reports' headers. Both apps pass them in. A ledger saved before reads both as blank, which the hit rates show as "Not recorded". Schema 2 is not yet released, so the schema stays at 2.

The binomial range is worked out from the most likely count outward by products and quotients, so no power of 0.8 underflows and the two engines agree to the bit. It matches scipy's `binom.ppf` for every n from 1 to 3000 at p of 0.05, 0.5, 0.8 and 0.95. The two works the report cites are new in `references.yaml`.

Parity gains three checks, 2493 in all: a survey's points with their teams (nine surveys); the band, the odds, the hit rates and the report over eight pooled portfolios built to give every verdict, under three settings (14 cases); and 30 binomial ranges. The ledger's outcomes gain a case for each log with the project's contractor. `tests/test_calibration.py` (104 tests) holds each rule, and the browser's engine to Python's in a Node vm on 40 seeded portfolios; the 60 seeded cases of `tests/test_ledger.py` now carry teams and contractors, and both apps' ledger tests check what is recorded. Only the `ledger` and `calibration` sections of `reference.json` changed. Because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. The two minimums, counting the driller's recorded success without a test as a success, taking the survey team from the field supervisor, and the project's contractor winning over the log's want the owner's confirmation.

### The calibration report in both apps (PLAN.md step 5.2, part b)

Both apps' Portfolio pages now carry a **Calibration** section under *Predictions and outcomes*. It scores the pooled ledgers' forecasts against what was drilled and writes them up as the twelfth document, the calibration report.

- **On the page.** The report's summary (how many forecasts are scored, the band's verdict, the Brier score beside the prior's, and where the hit rates are given), and its two figures where the content names them.
- **The figures.** Drawn by `groundwater.calibration_plots` in Python and `charts.depthCalibration` and `charts.reliabilityDiagram` in the browser, from the engines' `depth_scores` and `odds_scores`:
  - the depth to basement found against the depth the best fit gave, each point with its P10 to P90 band, the line where they agree, and a hole that stopped short of basement drawn at its total depth pointing down. A point whose best fit resolved no basement is drawn hollow at its band's P50, named so in the legend, so it is never read as a best fit's depth;
  - the reliability diagram, the share that succeeded in each band of forecast chance against the band's mean forecast, with each band's number of forecasts and the diagonal of calibrated forecasts.
- **The document.** *Build the calibration report (.docx)* writes `Calibration_Report.docx` from `calibration_content`: the cover with what the ledgers hold, the summary, the depth to basement, the chance of success, the hit rates by geology unit, survey team and contractor, what the report does not say, and the references. Python's is `groundwater.reporting.calibration.build_calibration_report`, the browser's `GWT.docx.calibrationReport`. Unlike the site's reports it opens on no area map, since it covers many sites.
- **A built report goes with its files.** The Streamlit app offers the report only while the files it was built from are the ones on the page, and leaves it out of the session's deliverables, so a report of other files is never handed out as this one. The browser writes it at once.

`tests/test_app.py` builds the report on the Portfolio page, reads it back and checks the download goes when the files change. `tests/test_calibration.py` (108 tests) builds the document with both figures, one with nothing drilled and none, draws every kind of point and an empty bin, and places a point without a best fit at its band's P50. `smoke.mjs` (348 checks) builds it in the browser from the Rokel project, whose one drilled point has neither a best fit's depth nor a band and so no figure, and from twelve forecasts with bands and chances, checking each document's four sections and that its pictures are the figures its content names. `gwt-core.js` is untouched, so saved inversions do not re-run. The user guide's section 10a describes it, and the README counts twelve documents.

### Calibration sets in both engines (PLAN.md step 5.3, part a)

Both engines can now fit a **calibration set** to the boreholes in a pooled ledger: the 3.3 priors, the resistivity edges of each geology unit and the suitability score's weights. A set changes nothing until a named person adopts it. The new module is `groundwater.calibration_sets` (`fit_set`, `fit_prior`, `fit_edges`, `fit_weights`, `adopt_set`, `set_name`, `set_yaml`, `read_set`, `clean_set` and `default_set`), its twins are in the browser's engine (`C.fitSet`, `C.adoptSet`, `C.setYaml`, `C.cleanSet` and the rest), and the words are in the new catalogue `data/text/calibration_sets.yaml`. Nothing uses a set yet: part b puts an adopted set in force in both engines, and part c lets a person fit, review and adopt one on the Portfolio page.

- **Always from the provisional default.** Every fit starts from the cited tables, with every borehole in the pooled ledger, and never from the set in force, so no borehole is counted twice. A borehole counts once it is drilled, its success is known and it was judged at the definition of success in force. The others are counted in `left_out`.
- **The prior** of each row of `success_prior.csv` that boreholes fall in: the row a point's recorded ground matches, its class and unit, else its class. It is a beta-binomial update in which the provisional rate counts as its effective number of boreholes (10). Each borehole was sited on survey evidence that moved its odds, so counting its success as the ground's alone would count that evidence twice. The count it adds is the number of successes the forecasts would expect at the rate that, carried through each borehole's own evidence (its recorded chance over its prior, in odds), expects as many successes as there were. Without evidence that is the count itself, and the update is the plain beta-binomial. The even-chance fallback rows are never fitted, since no cited rate is there to fit.
- **The resistivity edges** of each USGS unit, the two a drilling log can test. `clay_max_rho` parts the layers the log calls clay from sand, weathered rock and fracture zones. Saprolite is left out, since "clayey saprolite" is saprolite in the class table. `fresh_basement_min_rho` parts the weathered profile from basement rock. Each layer of the best fit is read as the class of rock filling at least half of it, down to the log's total depth or the depth of investigation, whichever is shallower. The edge goes to the midpoint between neighbouring resistivities that misreads the fewest layers. It moves only where it misreads fewer than the edge in force, and on a tie goes to the nearer, by ratio. The clay edge stays under the water-bearing window's top, and the basement edge over the clay edge. The 800 ohm-m and laterite edges are not fitted: no class in a log says whether weathered rock was dry.
- **The suitability weights** are fitted once `ledger.fit_weights_min_each` (10) boreholes have succeeded and as many failed. Of the 1,771 ways to weight the four parts in twentieths, the fit takes the one that ranks the most pairs of a success and a failure the right way round. A tie goes to the weights nearest those in force.
- **Too few to fit.** A prior row or a unit's edge needs `ledger.fit_min_boreholes` (5) boreholes; below that it is listed with its counts, not fitted. Both minimums are provisional.
- **Adopted by a person.** `adopt_set` refuses a blank name and a set adopted already. It numbers the set one after the set in force, version 0 being the provisional default, and records the set it replaces. Every report can name the set: the default as before, "the toolkit's provisional default from PLAN.md step 3.3, adopted by no named person …", and an adopted one as "calibration set 2, fitted on … to 34 boreholes and adopted by … on …".
- **The file.** `calibration.yaml` is block-style YAML that both engines write byte for byte, which PyYAML and the browser's reader both read back. A file is read whole or refused with a sentence naming what is wrong. It lists the boreholes it used by their ledger ids alone, without the project, place or borehole name, so it can be shared without the projects behind it (step 5.5).
- **The ledger records what the fit needs.** Each prediction now keeps its best fit's `layers` (top, bottom and resistivity) and the suitability score's four parts (`suitability`). Both apps pass the ranked siting in, matched to each point by its index. A ledger saved before reads both as blank, and its points are left out of the edges and the weights. Schema 2 is not yet released, so the schema stays at 2.

The fits use only sums, products, quotients and square roots, and the weights are ranked in whole numbers, so the engines agree to the bit. `tests/test_calibration_sets.py` (68 tests) holds each rule, and the browser's engine to Python's in a Node vm on 24 seeded portfolios, including the file's text and hand-edited files. Parity gains four checks: sets fitted, adopted, named, written and read back over four portfolios under three settings; hand-edited files read or refused; adoption refused; and the default. The ledger's predictions and surveys now carry layers, parts and a ranked siting. Only the `ledger` and `calibration_sets` sections of `reference.json` changed. Because `gwt-core.js` changed, each saved inversion is re-run once when its project is reopened. The evidence adjustment of the prior, fitting only the clay and basement edges, leaving saprolite out of the clay edge, the two minimums, the weights' grid and ranking, fitting every set from the provisional default, and recording boreholes by their ledger ids alone want the owner's confirmation.

### A calibration set in force, in both engines (PLAN.md step 5.3, part b)

A calibration set that a named person has adopted can now be put in force, and both engines then use it. With no set in force, every number is as it was. Part c below lets a person fit, review and adopt a set on the Portfolio page and put it in force there. Outside the apps a set is put in force from Python by `calibration_sets.apply_set`, or by naming its file in a project's `config.yaml` (`calibration: calibration.yaml`, beside it), and in the browser by `withConfig({ calibration: set })`. A set nobody adopted is refused: "nothing changes until a named person adopts it".

- **The prior.** Where the set fitted the row of `success_prior.csv` that a point's ground matches, the odds start from its rate and effective size instead of the table's. The headline then reads "Prior fitted in calibration set 3." The prior's sentence gives the table's rate it started from, the boreholes it was fitted to and how many succeeded. A row the set did not fit, the even-chance fallback, and every row of a set fitted at another definition of success keep the table's prior. The survey evidence moves a fitted prior exactly as it moves the table's.
- **The edges.** `config_for_sounding` gives the configuration a sounding is interpreted with: the set's clay and fresh-basement edges for the geology unit under the sounding's own position, or the site's. Where the set fitted no edge, nothing is looked up. Restoring a project in Python (`recompute_results`) interprets each sounding this way, and the two apps do too since part c.
- **The weights.** The suitability score's weights are now a setting, `ves.suitability_weights` in `defaults.json`, in place of the hard-coded `_WEIGHTS` in `siting/suitability.py` and its copy in the browser. A set that fitted them puts its own in force. The inversion never reads them, so the cache key of a saved inversion leaves them out: with the default weights it is the key it was before, and a set changing them does not invert a survey again.
- **Every report names the set.** The basis of the odds names the set in force. That is "calibration set 3, fitted on … to 12 boreholes and adopted by … on …", or the provisional default in the words it had before, which now come from `calibration_sets.yaml` rather than `success_evidence.yaml`. The basis then says what else the set changes: "Calibration set 3 reads the USGS unit pCm with clay up to 31.5 ohm-m and fresh basement from 1,500 ohm-m," and the weights it gives the score's four parts. The ledger records the set each prediction was made with.
- **Fitting against the set in force.** A new fit still starts its priors from the provisional table. Its edges and weights start from those in force, so an edge or a weight moves only where it does better than the set's.

`tests/test_calibration_in_force.py` (37 tests) holds each rule, and the browser's engine to Python's in a Node vm on 18 seeded sets, including sets fitted to seeded portfolios and adopted. Parity gains a check, 2498 in all: the odds over nine kinds of ground with their sentences, each unit's edges, soundings and models read by them, the suitability ranking and what the set changes. It runs under the default, a set, the set at another definition of success, a set without weights, and a set nobody adopted, which is refused. The odds, decisions and measurement sections of `reference.json` gain the odds' new fields, all blank under the default, and the new `calibration_in_force` section is added. Because `gwt-core.js` changed, each saved inversion is re-run once in the browser; the Python app's are kept, since neither its inversion code nor, with the default weights, its keys changed. Two calls want the owner's confirmation: that a set fitted at another definition of success fits no prior, and that a set without weights puts back the toolkit's weights after one that had its own.

### Calibration sets on the Portfolio page, in both apps (PLAN.md step 5.3, part c)

Both apps' Portfolio pages now end with **Calibration sets**, where a set is fitted to the pooled ledgers, reviewed beside the set in force, adopted by a named person and put in force. Until someone adopts one, every number is as it was. The card is shown even with no files on the page, so a set can be downloaded, loaded or dropped without them.

- **The set in force** is named, with what it changes besides the priors (its edges by geology unit and its weights). *Download the set in force (calibration.yaml)* saves it. *Put it in force* reads a calibration.yaml back: a file that is not a set, or a set nobody adopted, is refused and the set in force stays. *Return to the provisional default* drops it.
- **Fit a set to the pooled ledgers** fits one to the pooled files' drilled points and shows its review. `calibration_sets.set_review` (`setReview` in the browser) writes it: how many boreholes it uses and leaves out, what it fits against the minimums, how the weights rank the pairs of a success and a failure against the weights in force, and a table each of the priors (the provisional table's rate, the rate in force and the fitted one, with the boreholes it is worth), the edges (the layers under and over each, and the layers each misreads) and the weights. A set that fits nothing says there is nothing to adopt and offers no button. The review is shown only while the files and the set in force it was fitted under are the ones on the page.
- **Adopted by a named person.** *Adopt the set and put it in force* takes the name typed beside it and refuses a blank one. The set is numbered after the set in force and put in force at once.
- **Every page reads by it.** Both apps build their configuration with the set in force (`shared.app_config`, `config()`). Each sounding is interpreted by the edges the set fitted for the geology unit under it: on inversion, on a project reopened, in the VES co-pilot's preview and when a set is put in force, which reads the survey on show again. The range of models is sampled by the same edges. In the Streamlit app a sounding's range is dropped where the set changes its edges; in the browser every recompute drops them, as before. The ranking and the suitability table use the set's weights. Ranking used the toolkit's weights in both apps' interpretation step and in `recompute_results`, and the siting calls in the Streamlit app (the GeoLibre file, the drill-target table, the costing's first point and the value of a measurement) used them too; all now take the weights in force.
- **Whose it is.** The set in force belongs to the session (`calibration_set` in the Streamlit app's session state) or to the browser (`calibration` in the store), not to a project. No project file carries one, and opening a project or a sample leaves it in force; a project file that carried one is not read. In the browser it outlives a refresh, and *Reset everything* returns it to the default.

The page's sentences are in `calibration_sets.yaml`, read by both apps. `tests/test_calibration_sets.py` (71 tests) gains the review's rules, and the browser's review is held to Python's in the Node vm on the 24 seeded portfolios, against the default and against each portfolio's adopted set. `tests/test_app.py` drives the Streamlit flow: fit, a blank name refused, adopt, the default, a file loaded and a set nobody adopted refused; and a set put in force reading the Rokel survey again, its first sounding then finding basement at 1.0 m by the fitted 579.7 ohm-m edge, and its range dropped. The browser's smoke suite gains two checks of the same flow, a project opened over the set and the file it downloads. `reference.json` is unchanged. Because `gwt-core.js` changed, each saved inversion is re-run once in the browser; the Python app's are kept. Keeping the set out of project files, letting *Reset everything* drop it in the browser, and offering a return to the default without a named person want the owner's confirmation.

### The VES quadrature, short soundings and what "converged" means

An audit of the VES forward model and inversion found six things wrong in both engines, or wrong in one and not the other. Each is fixed alike in both, and every fitted number moves a little.

- **Where the quadrature stops.** Both engines cut the Hankel integrals 18 decay lengths of the thinnest layer out. Against a quadrature with no cut (Gauss-Legendre on every half-period of the Bessel function out to 80 decay lengths, which agrees with scipy's adaptive quadrature and the two-layer image series to 1e-9), the cut left (5 to 7)e-8 x (rho1 / rho_a) x sqrt(AB/2 / h1). The 1.6e-7 x rho1 / rho_a this changelog gave left out the square root and was low by up to 11 times at long spacings. The error was 2.7 percent at 150,000 over 10 ohm-m under a 0.5 m top layer at AB/2 = 300 m, and 110 percent at the inversion's bounds (200,000 over 0.5 ohm-m, 0.2 m). Where the cut crossed a Bessel zero, rho_a stepped, and 17 of 99 Jacobian-sized steps of h1 read slopes of +-17.7 where the true slope is 0.00002. The cut now follows the top layer's thickness, which alone sets how fast the integrand decays (the Koefoed recurrence gives T - rho1 = (T2 - rho1)(1 - tanh(lambda h1)) / (1 + T2 tanh(lambda h1) / rho1), so no deeper layer slows it). It also follows the contrast: the integral stops n decay lengths out, where the tail it leaves, 2 rho1 e^-n sqrt(2 n d / pi), is 1e-8 of the least resistivity in the model, and n is never under 18 (`forward._cut`, `quadratureCut` in the browser). Over 2932 models of two to four layers at 10 to 150,000 ohm-m, 0.5 to 60 m thick, at AB/2 1 to 300 m, the worst error falls from 2.7e-2 to 3.1e-8. It is 1.5e-8 on 540 Wenner and 96 finite-MN models. At the inversion's bounds it is 4.0e-7 for Schlumberger; Wenner and finite MN there are in the next section. The steps are gone: the same slopes are within 3e-4 of the true one, and a thin layer at depth no longer moves the cut at all. The integration runs 15 percent further on the median model and less far where a deeper layer is thinner than the top. Forty synthetic soundings invert about 10 percent slower in Python and 2 percent slower in the browser, the label below included. The 1e-8 is a choice: 1e-7 left up to 1.1e-7, and 1e-9 bought nothing below the quadrature's own floor of 2e-8 at these contrasts. The rule the triage proposed, 18 + ln(rho_max / rho_min) decay lengths of the thinnest layer, left 2.2e-6 on the same models, with 143 of them over 1e-6, and was not taken.
- **The potential integral below x = 1e-6.** The quadrature's first section began at 1e-6. For the J0 integral of a Wenner or finite-MN reading the piece below it is about (rho_n - rho1) x 1e-6, and a reading, a difference of two potentials, carried it whole: (rho1 - rho_n) x 1e-6 ohm-m at every spacing. That is 5e-4 relative for 5000 over 10 ohm-m at a = 100 m, and 40 percent at the bounds. The first section now starts at 0, with one more eight-point Gauss-Legendre panel on (0, 1e-6). A midpoint rule there was not enough: under 0.5 ohm-m on 200,000 ohm-m it was 5e-5 out at a 1 m spacing. Under a thick cover of that, one panel was not enough either, and the next section takes the J0 table's panels further down.
- **A short sounding fitted with a parameter per reading.** The search tried three and four layers on any sounding of four spacings or more. Four readings of an 800 / 40 / 2000 ohm-m earth were fitted with a three-layer model's five parameters at 0.00003 percent. The parsimony rule then preferred that to the two-layer model's 2.1 percent. The uncertainty factors, from a residual variance divided by max(m - p, 1), all read 1.0, and the interpretation gave confidence 1.0 and "resolves a 3 layer subsurface" for a 9.8 ohm-m clay below 3.5 m. Both engines now fit at most m // 2 layers to m distinct spacings (`inversion.most_layers`, `C.mostLayers`), so a model keeps at least one degree of freedom: two layers below six spacings, three below eight, four from eight. Asked for more by `n_layers` (`nLayers`) or an initial model, the inversion refuses in the same words in both engines: "Too few spacings for a 3-layer model: its 5 parameters need at least 6 spacings, and the sounding has 4". With no degree of freedom the uncertainty factors are 10, which reads as not resolved, and a saved inversion with more layers than its readings allow is not used. Keeping one degree of freedom is a choice: it is the least that lets the misfit say anything about the readings' error, and keeping two would refuse three layers to soundings of six and seven spacings. Soundings of eight spacings or more, the Rokel pair among them, are searched as before.
- **The browser's iteration count.** A browser fit that ran out of iterations reported 61 against a limit of 60; Python reported 60. The browser's own cache refused a count over the limit, so every sounding whose chosen fit ran to the cap was inverted again each time its project was opened: 2 of 40 synthetic soundings and 3 of 7 edge cases. The Geophysics page printed "61 iterations". The count is now taken as Python's `range()` takes it.
- **A reading at AB/2 = 0.** Both readers kept a row whose AB/2 is 0, such as a formula over a blank cell or a placeholder, with only the warning that MN/2 is not smaller than AB/2, and the inversion kept it too. Its logarithm, -inf, went into the starting models. numpy's interp recovers from that by reading from the right-hand point, and the browser's did not, so for Rokel A with such a row added the browser fitted a NaN top layer at 100 percent and Python three layers at 12.9 percent. Both engines now leave out any reading whose spacing is not finite and positive, from the fit and from the depth of investigation. Both readers flag it as a warning, `nonpositive_spacing`: "A spacing must be positive; 1 reading at a spacing of 0 or less is left out of the inversion." The browser's interp now takes numpy's fallback and returns a point's own value at that point, as numpy does.
- **What "converged" means.** "Converged" was set whenever the damped step search found no lower misfit, and cleared whenever a fit ran its 60 iterations. On 240 fits (40 synthetic Sierra Leone soundings, two starts at two, three and four layers each), 8 of the 158 labelled converged could still be lowered by more than 0.1 percentage points by a bounded trust-region polish on the same forward model. Meanwhile 31 of the 82 that ran out were already at a minimum. A fit is now labelled converged when the Gauss-Newton step from where it stopped, over the parameters free to move within the bounds (a parameter at a bound the gradient pushes outward is held), would lower its sum of squared log residuals by at most 1e-6 of itself, or when that sum is under 1e-10 (`inversion._stationary`, `stationary` in the browser). Each result now says why it stopped: `stopped` is "exact fit", "no improving step" or "iteration cap". The label is worked out at the returned point and nothing in the iterations changed, so it moves no fitted number. On the same 240 fits with the new cut, 148 stop with no improving step and 92 at the cap. The label calls 162 of them converged, 143 and 19. The polish lowers 6 of those by more than 0.001 points, all two-layer fits at 59 to 213 percent misfit, and none by more than 0.06 percent of its misfit. Of the 78 it does not call converged, 33 are at a minimum by the polish: the test errs towards "not converged" in an equivalence valley. The 1e-6 is a choice. The two worst stalls the audit found (68.9 percent where 63.9 was in reach, and 84.7 where it was 80.0) were the cut's steps in the Jacobian, and with the new cut both fits reach the lower misfit. No report prints the label; the inversion cache and the fuzz suite's open-question rule read it.

What moves. Rokel A's fit is 13.34676 percent (was 13.34685), rho 1104.9, 1637.1 and 47.278 ohm-m (was 1105.5, 1637.8 and 47.280), and h 1.0180 and 7.0850 m (was 1.0213 and 7.0799). Rokel B's is 26.80184 percent (was 26.80178), with its layers unchanged to five figures. The drilling preference table prints Rokel A's resistivities as 1,105 and 1,637 ohm-m (was 1,106 and 1,638). The range of models moves with the forward model under it. Rokel A's range now finds basement within reach in 8.8 percent of the models that fit, so the report says "not resolved in 91 percent" (was "over 99 percent"), and the water-bearing zone is 31 to 34 m thick (was 31 to 33). The short synthetic Wenner run's P90 drilling depth is about 25 m (was about 30): its 200 samples go other ways once any likelihood moves. In `reference.json` the inversion, siting, interpretation, preference, range, odds and ledger sections move with the Rokel fits, and the forward grid with the cut. The forward grid gains four layered models whose thinnest layer is not the top one, and a new `ves_fit` section holds the rest. Sections whose only differences were this machine's library builds against the committed file's were left as committed. Parity gains 43 checks, 2541 in all: the short soundings' layer counts, trials, models, factors, labels and refusals; fits allowed 0, 1 and 3 iterations; a full inversion run to the cap, and the browser cache taking it back; the sheet with a row at AB/2 = 0, its flags and its fit; interp over log 0; and how the Rokel inversions stopped. Iteration counts of full inversions are not compared, since last-bit differences send the damped steps different ways while the models agree. `tests/test_ves_forward_inversion.py` (19 tests) holds each rule, the forward model against the image series and against the uncut quadrature. `tests/test_inversion_cache.py` refuses an entry without a stop or with one the search never makes. The cache's format is 2, so every saved inversion is run once more in both apps. The fuzz suite passes unchanged, with no saved case's expectation moved. The Rokel example's report, tables and VES figures are regenerated; the other examples' reports read word for word as before and are left as committed. The user guide's section 2 says how many layers a short sounding is read as, and QUESTIONS.md item 11 asks a geophysicist to confirm the three choices.

### The VES potential integral under a thick conductive cover, and two VES sentences in the catalogue

A review of the change above found that one of its accuracy claims held for Schlumberger readings only, that two of its new sentences were typed out in each engine, and that one of its regression assertions passed on the old engine too.

- **The potential integral at the corner of the inversion's bounds.** The change above gave the J0 (potential) integral, which Wenner and finite-MN readings use, one eight-point Gauss-Legendre panel on (0, 1e-6). Below x = r / (rho_n S), S the conductance h_i / rho_i of the layers over the basement, that integrand is the whole rho_n - rho1. One panel integrates it exactly only while the resistivity transform is flat across it. Under 300 m of 0.5 ohm-m on 200,000 ohm-m that point is 8e-9 for a 1 m radius, and Wenner at a = 1 m read 0.49944 ohm-m where the image series gives 0.50000, 1.1e-3 out. Finite MN (MN 0.4 m) was 1.1e-3 out at AB/2 = 1 m, and under three 300 m layers of 0.5 ohm-m it was 1.15e-3 out at AB/2 = 3 m. So the 4.0e-7 at the inversion's bounds in the change above is Schlumberger's alone. Both engines' J0 tables now carry 16 more panels, two a decade, from 1e-6 down to 1e-14, and one on (0, 1e-14) (`forward._J0_FLOOR`, `J0_FLOOR` in the browser). Inside the inversion's bounds (0.5 to 200,000 ohm-m, three layers of at most 300 m on the basement) that point stays above 1e-14 for any radius over 4 micrometres. Against a reference integrated down to 1e-20, Wenner and finite MN at the corners of the bounds are now within 5.2e-9 and 6.1e-8. On 900 random models of two to four layers across the bounds they are within 9.2e-10 and 1.5e-8; two of those models had been over 1e-6, at 4.3e-6 and 1.5e-5. The J1 table, which every Schlumberger reading uses, is unchanged. A Wenner forward model of 12 spacings takes as long as before in Python (0.42 to 0.47 ms here either way) and about 9 percent longer in the browser (0.58 ms, was 0.53).
- **What moves.** Only Wenner and finite-MN forward models move: by the amounts above where rho_n S puts that point below 1e-6, and elsewhere by under 1e-9. No example sounding is a Wenner one, so the example reports and every Schlumberger fit are as committed; regenerated, the reports read word for word as before. In `reference.json` the forward grid moves by under 1e-9 and gains two models, 300 m and three 300 m layers of 0.5 ohm-m on 200,000 ohm-m, where the browser's former tables would now fail parity by 1.15e-3. The Wenner sounding of the range of models moves too: its fit's misfit is 5.27778378549 percent (was 5.27778378547), one start's misfit 32.56417 (was 32.56420), its depths by a few parts in a billion and its resistivities by under 3e-7. Its text is unchanged. The fuzz suite passes as before (36 passed, and its one expected failure), with no saved case's expectation moved.
- **Two sentences in the catalogue.** The readers' warning for a spacing of 0 or less and the inversion's refusal of more layers than a sounding's spacings can determine were each written out in both engines, the plural rule included. They are now `ves.nonpositive_spacing` and `ves.too_many_layers` in a new `src/groundwater/data/text/ves.yaml`, which both engines read. The words are unchanged. Parity gains one check, 2542 in all: a sheet with two rows at a spacing not above 0, whose warning says "2 readings ... are".
- **Tests.** The test that the forward model has no steps checked a deep thin layer's slopes for a spread under 0.01. The old cut's spread there was 0.0031, so it passed on the old engine too. It now sweeps 0.5 m of 300 ohm-m under 0.55 m of 5000 ohm-m and 3 m of 10 ohm-m, where the old cut's slopes spread over 0.10 and the new one's over 4e-5, against a limit of 1e-3. A new test holds Wenner and finite MN under 60 and 300 m of 0.5 ohm-m on 200,000 ohm-m to the image series to 1e-8 (they now agree to 3e-10), and another holds the J0 table's floor below every cover the inversion's bounds allow, with room to spare. `tests/test_ves_forward_inversion.py` has 22 tests. The forward model's comment on how far the largest quadrature table reaches still gave the old rule, 20,900 times the thinnest layer. It now says 10,000 to 15,000 times the top layer, which is AB/2 of 2,000 to 3,000 m over the inversion's 0.2 m floor.

### What the VES readers take from a sheet, and a resistive layer over water read as cover rather than bedrock

An audit of the VES sheet readers and the interpretation found eight things wrong. Seven are fixed alike in both engines; the eighth is in the IPI2Win reader, which only Python has. The second item below is what the first does to a calibration set already in the tests.

- **A resistive layer over conductive ground was taken for bedrock.** The depth to basement was the top of the first layer below the surface at or over `fresh_basement_min_rho` (3,000 ohm-m), whatever lay below it. A 5,000 ohm-m duricrust 0.8 m down, over 20 m of 60 ohm-m on 8,000 ohm-m, was labelled "fresh basement" and gave a depth to bedrock of 0.8 m, with the 3 to 23 m water zone under the bedrock. The suitability then read "overburden of about 1 m that limits the target" and scored 55.7, where the same ground with a 2,900 ohm-m duricrust scored 82.7, and the range of models read every sample the same way. Fresh basement is now resistive ground with no conductive ground beneath it in the fitted model. It is the top of the first layer below the surface that reaches the edge with no layer under it that the rules read as water-bearing or clay-rich (under both the 800 ohm-m top of the water-bearing window and the edge); failing that, as before, it is the top of a half-space of 800 ohm-m or more (`interpret.basement_top`, `basementTop` in the browser). The interpretation and the range of models (`model_range._summary`, `rangeSummary`) both read it from there. A layer that reaches the edge over conductive ground is labelled "resistive cover (a duricrust or a dry layer) over conductive ground", and the narrative says why: "Layer 2 is as resistive as fresh basement, but conductive ground lies below it in the fitted model, so it is read as resistive cover and not as bedrock." The duricrust above now has its bedrock at 22.8 m and scores 82.7, the same as with 2,900 ohm-m. The water zones and the drilling depth come from the water-bearing layers, so they do not move; the depth to bedrock, the suitability's overburden and basal-fracture parts, the bedrock maps and the range's basement band do. Counting clay-rich ground as conductive, so that a resistive layer over clay is not basement either, is a choice (QUESTIONS.md item 12).
- **Rokel A under a fitted basement edge.** Part c above recorded the Streamlit test's calibration set leaving Rokel A "finding basement at 1.0 m by the fitted 579.7 ohm-m edge". That was its 1,637 ohm-m second layer, over the 47 ohm-m zone it is drilled for, and by the rule above it is a resistive cover: under the set Rokel A now finds no basement. The Streamlit test and the browser's smoke check now assert that the set relabels the layer, and that the depth to basement stays blank.
- **One resistance row lost the workbook.** On a sheet that records V/I and has no K column, K was computed for each row from AB/2 and MN, and the geometric factor raises where MN/2 is not between 0 and AB/2. One mistyped spacing raised out of the reader in both engines, and every other sheet of the workbook was lost with it. Such a row is now left out with a warning, `k_undefined`: "The Schlumberger geometric factor K needs MN/2 between 0 and AB/2, so the resistances read at AB/2 0.3 and 0.5 m could not be turned into resistivities and are left out. Check the spacings on the sheet." A row with MN 0 is flagged the same way; it used to be dropped without a word.
- **A column in ohm-metres read as a resistance.** The resistance test (`resistance`, `R (`, `V/I`) ran before the resistivity test and never looked at the unit. So a column headed "R (ohm-m)", "R (Ωm)" or "Apparent Resistance (Ωm)" was read as V/I and multiplied by K, 6 to 155 times too high on the audit's sheet, with only an information note to show for it. A column whose unit is ohm-metres (ohm-m, ohm.m, ohm m, ohmm, Ωm, Ω·m, ohm-metre) is now a resistivity whatever its name says, in both readers by one pattern. "R (ohm)", "V/I (ohm)" and "Resistance (ohms)" are resistances as before. The fuzz suite's sheets now also head a resistivity column "R (ohm-m)" or "Apparent Resistance (Ωm)".
- **An IPI2Win ERR in the next cell, and a table headed "ρ".** `read_ipi2win_models` read the ERR only from the cell that holds the label. "ERR (%)" and 21.5 in two cells therefore gave no misfit, and a 21.5 percent fit was rated "ok" at confidence 0.85 instead of "unreliable" at 0.425. A cell that holds the label alone ("ERR", "ERR (%):") now takes its value from the next non-empty cell to the right, else from the cell below. The table header now accepts IPI2Win's Greek "ρ" and "ρa", and a unit after a comma ("ρ, Ohm.m", "h, m") as well as in brackets; such a table used to yield no model. A sheet with no model table is reported to a `skipped` list, as `read_ves_workbook` reports one, where it used to be left out without a word.
- **A spacing read twice with no MN change.** The splice merges repeated spacings only on a Schlumberger sounding with more than one MN segment. A sheet with no MN column or one MN throughout, and every Wenner sheet, is fitted reading by reading. The range of models still added the overlap term to the error of each copy, which its own rule says the misfit already holds, and listed the spacing once per copy ("MN overlaps at AB/2 10, 10, 40 and 40 m"). A spacing the fitted readings hold more than once now takes the base error alone. The readers' flags said such a pair was "repeated with different MN (segment changes)" and that "the inversion merges the pair by geometric mean". Where the splice does not merge, they now say "1 AB/2 value(s) read more than once; the readings are kept, and the inversion fits each one as it stands rather than merging them". For a pair that disagrees, they say that the inversion fits each reading as it stands, so the disagreement is part of the model misfit. The four flag sentences are now in `ves.yaml`; the two for a merged pair keep their words.
- **A zero at an MN overlap dropped its partner.** The merge took the geometric mean over every reading at a spacing, a zero or a blank included. A pair with one reading of 0 merged to 0, and the inversion dropped the spacing with its good reading. The mean is now over the finite, positive readings, and a spacing with none is still left out.
- **A 1 m zone printed as none.** Each end of a water zone was rounded half to even, so a layer from 3.5 to 4.5 m (or 5.5 to 6.5 m) became "4 m to 4 m", an aquifer of 0 m and a score of 0, while the drilling depth was still set from it. The ends are still rounded half to even, but a zone that would round to no thickness now ends 1 m below its rounded top: "4 m to 5 m", 1 m of aquifer. Only such zones move, and only a zone exactly 1 m thick on two half metres can round that way.
- **A layer above a short sounding's reach said to lie below it.** On a sounding whose depth of investigation is 3 m or less, a water-bearing layer that starts above it was said to lie "below the 2.5 m the sounding resolves". The test used the layer's top after the 3 m vadose floor, and the sentence printed the real top. Only a layer whose own top is at or below the depth of investigation keeps that sentence. One that starts above it now reads: "The water-bearing layer from 0.6 m starts within the top 3 m, which are taken as unsaturated, and the sounding resolves only 2.5 m, so it is not counted as a water zone." Both sentences are in `ves.yaml`.

What moves. The Rokel fits, interpretations, preference table and odds are unchanged. At the default settings Rokel A's range of models found basement within reach in 8.8 percent of the models that fit, each time at the top of a second layer sampled over 3,000 ohm-m above the 47 ohm-m zone. It now finds it in none, so the report says "not resolved in 100 percent" (was 91) and `model_ranges.csv` says 100.0 (was 91.2). The odds read "not resolved" before and after. In `reference.json` only the `ves_text` and `ves_range` sections move. The existing "thin resistive at 2.5" case (5,000 ohm-m from 2.5 to 5.5 m over 100 ohm-m) loses its depth to bedrock of 2.5 m and its overburden penalty, and scores 75.2 (was 68.2). The Wenner sheet with an MN column now says its repeat is fitted as it stands. Rokel A's default range loses its basement band. Parity gains 94 checks, 2636 in all: seven interpretation cases (a cover over a water zone, over clay and over a conductive half-space, two covers, basement over compact rock, a 1 m zone on half metres and a sounding too short for the vadose allowance); three sheets (a resistance sheet with two rows K cannot convert, a resistivity headed as a resistance and a repeat with no MN column); what the readers read off every sheet; the fitted readings and their errors on three soundings; and a short range on a duricrust over a conductive weathered zone, where no model finds basement. `tests/test_ves_reading_interpretation.py` (40 tests) holds each rule in Python, and the browser's engine to Python's in a Node vm; each finding's tests fail on the code before this change. The fuzz suite passes as before (36 passed, and its one expected failure), with no saved case's expectation moved. The Rokel report and `model_ranges.csv` are regenerated; the other examples' reports read word for word as before and are left as committed. The user guide's section 2 says how a resistance sheet, a column in ohm-metres and a repeated spacing are read, and what the depth to bedrock is taken from.

### What the pumping test readers take from a sheet, when a level has stabilised, and the yield search's floor

An audit of the pumping test readers and the analysis found seven things wrong, every one of them in both engines. One, Cooper-Jacob's slope floor, was on the list below, and two more items there are closed with them: the casing a co-pilot writes on its sheet, and the unlabelled range beside the yield. Each is fixed alike in both engines.

- **Times written as a clock.** A cell Excel shows as a clock reaches the Python reader as a time and the browser's as the text "01:30:00", and "1:30" typed as text is the same. Both readers took the first number in it for the minutes: 01:30 was minute 1 and 00:05 minute 0, and readings at minute 0 are dropped by the fits without a word. An 8-hour test of an aquifer of 20 m2/day written that way "pumped for 8 minutes", its readings stacked on minutes 1 to 8, and was flagged as a short test inside its casing-storage period with an indicative yield. The only trace was a `time_not_increasing` warning. The fuzz suite already wrote such cells, and the two engines agreed on the wrong times. Both readers now read a clock as the elapsed hours and minutes it shows (`units.read_time`, `readTime`). That covers the pumping, step and recovery columns and the length of each step, and a day or more in a cell formatted [h]:mm, which reaches the readers as a duration or as a date in January 1900. Reading "5:30" as five and a half hours is how Excel reads it typed into a cell; it is a choice, and a column headed "Time (mm:ss)" or "Time (min:sec)" reads it as five and a half minutes instead. An info flag, `time_clock_read`, says so: "12 pumping readings are written as a clock and read as hours and minutes, as Excel reads a time typed into a cell: 01:00:00 is minute 60 since the pump started." Four kinds of cell are now refused as unreadable readings under the existing `time_reading_unreadable` warning: text that starts as a clock and is not one ("1:60", "1:30 pm", "10:00 (approx)", "1: 30") and hours and minutes written as words ("1h 30m", "1 hr 30 min"), which both readers read as their first number, so that 1:30 pm and 1h 30m were minute 1; a date, which Python read as its year (2026 minutes) and the browser dropped without a word; and an Excel TRUE, which Python read as minute 1 and the browser dropped without a word.
- **Times of day.** A column of times of day, 08:05, 08:06, would now read as a test that began eight hours in. An earliest pumping reading written as a clock past the first hour is taken for a time of day, and the sheet is refused with an error, `time_of_day`, using no reading: "The earliest pumping reading is written as 08:05, a time of day rather than the time since the pump started (a test's first reading is taken within its first hour), so no reading on the sheet was used: this toolkit does not turn times of day into elapsed time. ..." It is the earliest reading, not the top row, so elapsed clocks in rows out of order are still read. A block whose heading names the minutes it covers ("Constant discharge 61-120 min") is held to its heading instead. The hour is a choice. Turning times of day into elapsed time needs the minute the pump started and the day each reading fell on, and is not attempted. A sheet left with no pumping readings at all, this one or one whose time column is headed in a unit the toolkit cannot read, had its yield "pending: discharge is missing on the field sheet" beside the discharge it records; it is now pending because "no pumping readings were read from the sheet".
- **A recovery in blocks, and on the test's clock.** Only the first recovery block was read, without a word: a two-hour recovery in two hourly blocks kept its first hour, and the report's "residual drawdown at the end of monitoring" was the 60-minute 0.307 m where the 120-minute reading was 0.210 m. Recovery blocks are now joined by the constant test's rules (the minutes the heading names, else continuing from the block before), with `recovery_blocks_joined` and `recovery_block_unreadable` flags. Recovery times written on the test's clock (241, 242 after a 240-minute test) were taken as minutes since the pump stopped: a recovery of an aquifer of 20 m2/day read 0.62 m2/day, caught only by the intercept guard, whose message blamed casing storage, a changing static level or a wrong pumping time. A recovery whose first time is at or after the minute the pump stopped is now moved back by the pumping time, with an info flag, `recovery_on_test_clock`, unless its time header or heading says it counts from the stop ("stop", "shut" or "off"); it then gives 20.02 m2/day. Taking such a recovery for the test's clock is a choice. The block sentences, the constant test's and now the recovery's, are in `pumping.yaml`; the constant test's keep their words.
- **The recovery read against another step's rate.** The recovery's rate was the latest step's that had one. With the last step's rate blank, a step test's recovery was read against step 3's rate over the whole test, and its 11.58 m2/day (for an aquifer of 15) was adopted ahead of the drawdown fits at established confidence. It is now read against the last step's rate alone; with none, it is not analysed and a warning says why, `recovery_rate_missing`: "The rate pumped when the pump stopped, step 4's, is not recorded, so the recovery is not analysed: ...". That test now adopts Cooper-Jacob's 15.00 m2/day, with a safe yield of 5.24 m3/h (was 4.92). The `missing_discharge` flag said every result was pending even where the first step's rate let the drawdown fits run and a yield follow. Where only some steps lack a rate it now says which results go without it: "... the drawdown fits take the first step's rate, the recovery and the specific capacity the last step's, and the step-test fit leaves out a step with none." Its words where no step has a rate are unchanged. Both sentences are in `pumping.yaml`.
- **The length of each step.** It was read as a bare number, so "1 hr" or "1 hour" was a step of 1 minute: a short test inside its casing-storage period, the Theis fit disqualified, the yield projected 5.7 log cycles and indicative at 4.76 m3/h where "60" gives an established 5.26. It is now read in the unit its label or its own cell names, a clock included, and a length that cannot be read is not used, with a warning, `step_length_unreadable`. With the cell blank, a step test's yield was projected from the whole test's duration while the short-test check took the first step's own length: on a test of four 100-minute steps that gave 5.46 m3/h where a filled cell gives 5.26, 3.6 percent more. Both now take the step's own length (`recommend_yield`, `recommendYield`).
- **Cooper-Jacob's 0.02 m per log cycle.** The fit was refused when its window's slope fell under a fixed 0.02 m per log cycle, which refuses any straight line from a test whose T exceeds about 220 times Q m2/day. At 1 m3/h in 250 m2/day, with levels read to the millimetre, the line ran 1.77 cm a log cycle at R squared 0.9975 and rose 1.74 cm across its window. It was refused with "the drawdown has stabilised or the slope is below reading resolution", which was false on both counts. Cooper-Jacob now refuses a window whose fitted line rises by less than the 0.01 m a dipper reads across it, the test the Theis and recovery fits already apply: "Across the fitted window 50-480 min the drawdown rises by less than 0.01 m, which a dipper cannot tell from a level that holds, so Cooper-Jacob does not apply". The handpump line gives 248.8 m2/day and is adopted. `cooper_jacob_min_slope_m` is gone from the configuration, and a `config.yaml` that still sets it is told the key is ignored. A tail that has flattened but still rises a centimetre or two is the next item's.
- **A level called stabilised.** The pumped level was called stabilised when the last three readings lay within 5 cm, whatever log time they spanned. Hourly readings at the end of a 24-hour test span 0.04 log cycles, so a Theis drawdown at 2 m3/h in 10 m2/day, still rising 0.88 m a log cycle, was reported as held by a recharge boundary or leakage. The report said the level stabilised and the Depth Spine labelled the pumping level so, beside a derivative that showed radial flow. The level is now judged over the last half log cycle of the last step, on the step's own clock. It has stabilised when its fitted line moves by less than 0.01 m there and its slope is under half the slope over the log cycle before, which rose by at least 0.01 m (`stabilised_tail`, `stabilisedTail`; `stabilised_span_log10` and `stabilised_slope_ratio` in `defaults.json`, both choices). A Theis line keeps its slope and a boundary flattens it. The flag now says where and against what: "The pumped water level held at about 13.69 m from 480 to 1440 minutes: its fitted line moved by less than 0.01 m over those minutes, having risen 0.24 m a log cycle over the log cycle before. A recharge boundary or leakage is indicated, ...", and on a step test "from 90 to 240 minutes into step 2". A Cooper-Jacob window that takes in such a level is not adopted (it is held invalid, as a recovery line that misses the origin is). The level of a drawdown that follows Theis to two hours and then rises 1.5 cm a log cycle is readable, so Cooper-Jacob no longer refuses that window for its slope, but read as the aquifer's the window gave about 870 m2/day for an aquifer of 20.
- **The yield search's floor.** The bisection for the long-term yield began at 0.01 m3/h and never checked that the root lay above it, so any lower yield came back as exactly 0.01, safe yield 0.0067, whatever T was: with 0.7 m of drawdown to spend the projection allows 0.0044 and 0.0012 m3/h at 0.2 and 0.05 m2/day. The search now starts at zero. The Dr Timbo sheet with its pump at 15 m, whose 0.0067 m3/h the tests recorded, has a safe yield of 0.0042 m3/h, long-term 0.0062.
- **The casing on the sheet.** A pumping test co-pilot writes "Casing diameter (in)" and "Riser diameter (in)" on its sheet, and no reader took them. Dr Timbo's sheet with 8 and 2 inches on it gave a casing-storage period of 117 minutes from the configured 5 and 1.25 inches, where its own give 300. Both readers now read them, in the unit the label or the cell names (`PumpingTest.casing_diameter_in` and `riser_diameter_in`). A diameter with no unit is refused rather than taken as metres or as inches, `diameter_unreadable`, and a casing no wider than its riser is refused with the riser, `diameters_inconsistent`, since it would leave no casing storage and no fit inside it. A value cell whose text does not start with a number is not a diameter, so a riser left blank on a co-pilot's sheet does not take the "Planned rate (m3/h)" label under it for its value. The analysis takes the sheet's diameters over the configuration's for the casing-storage period, the Papadopulos-Cooper casing radius and the sentences that name the casing, in both apps' pumping reports (`sheet_config`, `sheetConfig`). A sheet that records one of the two is read with the configuration's other, unless that pair would leave no water between them, when the configuration's pair is kept.
- **The yield's range over the assumptions labelled.** The yield tables of the pumping, completion and handover reports and the readiness gate's yield detail printed the safe yield's range over the assumptions as "0.39 m3/h (0.22 to 0.71)". The same reports print the P10 to P90 band of the same yield in their decision lines (step 3.6): two ranges, one of them unlabelled. It is now "0.39 m3/h (range over the assumptions, 0.22 to 0.71)", worded once in `decision.yaml`.

What moves. The Dr Timbo and Kuntolo sheets read as before. Dr Timbo's completion and handover reports change in the label alone; the other example reports read word for word as before and are left as committed. In `reference.json` every range text and the readiness details that quote one take the label (`analysis`, `pumping_cases`, `pumping_spread`, `readiness`, `spine`). The "level below pump" case's safe yield is 0.0042 m3/h (was 0.0067), and its bootstrap band moves from 0.0067 to 0.0067 m3/h to 0.0038 to 0.0047. Every other value that was there is as it was, to the last bits of the yield search's root. Parity gains 611 checks, 3247 in all. Nineteen sheets cover each item: clock cells, a minutes-and-seconds column, clocks in rows out of order, times of day, a recovery in two blocks and one on the test's clock, step lengths in hours, blank and unreadable, a last step with no rate, the casing on the sheet, one with no unit, one no wider than its riser and a co-pilot's with its riser blank, a 24-hour Theis drawdown, a flattened tail, a step test whose last step flattens, the handpump line and a yield under 0.01 m3/h. Each pumping case is compared on eight more quantities, and 34 time cells on what the readers make of them. The audit's sheets are clean Theis curves with no casing storage in them, which leave the large-diameter fit's storativity running off to 1e-22 or 1e-78, where the engines stop about 1 percent apart, so they are held in `pumping_cases` and left out of `pumping_spread`. Two fuzz regressions, written here rather than found, replay a 30-hour test in clock and [h]:mm cells and a date and a TRUE in a time column through both engines' .xlsx readers; `tests/fuzz/sheets.py` learns to write a duration cell for them, and `tests/test_ingestion.py` holds the first to the times it records, not only the engines to each other. The fuzz suite passes (38 passed, the two new regressions among them, and its one expected failure), with no saved case's expectation moved. `tests/test_hydraulics.py` gains 7 tests (42), `tests/test_ingestion.py` 9 (48) and `tests/test_units.py` 1 (25); each fails on the code before this change. `review.mjs` checks that the downloaded pumping report labels the range and names the sheet's casing. Because `models.py` and `gwt-core.js` changed, every saved inversion is inverted once more the first time its project is reopened, in either app. The user guide's section 3 says how times, the step length, a recovery in blocks and the casing on a sheet are read, the README lists them among the readers' behaviours, and QUESTIONS.md item 13 lists the four choices.

### What a laboratory sheet's units and bases say, a clock read as a quantity, and the gravel pack under the seal

An audit of the water quality assessment, the unit handling and the borehole design found eight things wrong, every one of them in both engines. Each is fixed alike in both engines, with the new sentences in the text catalogue (`quality.yaml`, and `design.yaml`, which is new).

- **A unit after a measured value, or in the result header.** Both sheet readers read a unit written after a bound ("<0.05 mg/L") and converted it onto the row's unit, but dropped one written after a measured value, and never read one in the result column's header. Arsenic "0.05 mg/L" in a ug/L row was read as 0.05 ug/L, a two-hundredth of the guideline, and the sample was graded Safe; lead "8 ug/L" with its unit cell blank was read as 8 mg/L, a health failure; arsenic 5 under "Result (ug/L)" was 5 mg/L, five hundred times the guideline. A unit after a measured value is now read when the toolkit can read it ("0.05 mg/L", "8ug/l", "27 oC") and converted as a bound's is; a note beside the number ("0.5 ND", "8 (field)", "8*") is not a unit and leaves the reading as it was. A unit in the result header is the unit of every row whose unit cell is blank or "-", when the toolkit can read it ("Result (lab)" declares nothing). A row it cannot measure, E. coli under "Result (mg/L)", is refused rather than read in its guideline's unit, which is a choice (QUESTIONS.md item 14). A basis stated on one side only no longer refuses a cell, as it already did not refuse a row: "46 mg/L" in a column of "mg/L as CaCO3" is the column's scale, and "10 mg/L as N" in a column of "mg/L" keeps the basis the cell names. That arsenic is now a health failure at 0.05 mg/L, the lead complies at 0.008 mg/L and the header's arsenic at 0.005 mg/L.
- **Nitrate and nitrite reported as nitrogen.** A bracket after a parameter's name was stripped as a symbol unless it began with "as", so "Nitrate (NO3-N)", "Nitrate (N)" and "Nitrite (NO2-N)" became nitrate and nitrite as the ions and were held to 50 and 3 mg/L instead of 11.3 and 0.91. 20 mg/L NO3-N, 88.5 mg/L as nitrate, was graded Safe, and the combined rule summed 20/50 + 0.5/3 = 0.57 where it is 20/11.3 + 0.5/0.91 = 2.32. A bracket that names nitrogen ("(NO3-N)", "(N)", "(NO3 as N)", "(as NO3-N)", "(nitrogen)") now resolves to the table's entry for nitrogen, which was there all along; one that names another ion, "Nitrite (NO3-N)", contradicts the name and is refused as a parameter the table does not know. The row is graded against the guideline for nitrogen, and its remark says which basis the sheet used and gives the ion's figure: "exceeds the WHO health based guideline (11.3); reported as nitrogen: 20 mg/L as N is 88.5 mg/L as NO3". "Nitrate" in "mg/L as N" was refused, as a unit naming a basis the parameter did not; it is now put on the ion's scale by the ratio of the molar masses, 62.004/14.007 = 4.4266, with an info flag, `unit_basis_converted`, and the remark "(10 mg/L as N = 44.2664 mg/L as NO3)". A name that states a basis its unit contradicts, "Nitrate (as NO3)" in "mg/L as N", is still refused. "as NO3-N" and "as nitrogen" in a unit are the basis "as N" is, and "Nitrate (NO3)", the ion's formula, is still nitrate as the ion.
- **Nitrogen in the indices.** The charge balance, the hazard index and the water quality index were keyed on nitrate and nitrite as the ions. The same water reported as nitrogen lost its nitrate from the balance, which came out 10.6 percent out and was flagged an unreliable analysis; lost its nitrate from the hazard index (0.32 became 0.14), although the reference doses for nitrate and nitrite are written for nitrogen; and gained it in the water quality index, from which the ions are kept on purpose, where nitrate as N led it: 13.3 became 43.7. A value reported as nitrogen is now put on the ion's scale, under the ion's key, before the indices read it (`standards.canonical_values`, `canonicalValues`), so the same water gives the same balance, hazard index and index; a sheet that reports both forms is counted once, by the ion's row.
- **Calcium and magnesium as CaCO3.** A unit stating a basis the guideline's unit does not was taken at face value with a warning that "an 'as CaCO3' figure is about 2.5 times the same concentration expressed as the element", and the raw figure went into the balance (calcium with 2.5 times its meq, magnesium 4.1 times) and into the Langelier, Ryznar and aggressive indices. Water with calcium 50.04 and magnesium 25.02 mg/L as CaCO3 balanced at +33.1 percent, an unreliable analysis, and read a Langelier index of -0.98 and a Ryznar index of 8.76 where the same water reported as the elements reads -0.09 percent, -1.38 and 9.56. Calcium, magnesium, bicarbonate and carbonate in "mg/L as CaCO3" are now put on their own scale by the ratio of the molar masses (calcium 40.078/100.087, magnesium 24.305/100.087, bicarbonate 2 x 61.017/100.087, carbonate 60.009/100.087), with the info flag, and that water reads -0.09 percent, -1.38 and 9.56. "mg/L as Ca" is calcium's own scale; another basis, "Magnesium" in "mg/L as Ca", is refused. The warning is kept for a basis no factor is held for, such as sodium as CaCO3.
- **A count per 100 mL written with a space.** Only "CFU/100 mL" and "MPN/100 mL" had a spaced spelling, so "/100 mL", "No./100 mL" and "per 100 mL" were units nobody could read. An E. coli count of 12 or "Present" in "No./100 mL" was "Not proven safe", asking the laboratory for its units, while "Absent" in the same unit passed. A space between a number and "mL" or "L" in a unit is now ignored, "#/100 mL" and the numero sign ("Nº/100 mL", "N° per 100 mL") are read, and those counts are health failures. A count seen and not numbered ("Present", "TNTC") in a unit that still cannot be read is graded as a count above zero, which it is on any scale; a number in such a unit is still refused (QUESTIONS.md item 14).
- **A determinand with no guideline value.** A result whose unit could not be read was indeterminate whether or not the table set it a limit, so a fully graded sample whose certificate wrote its temperature as "27 oC", or its calcium as "mg/L Ca", was "Not proven safe" over a determinand there is nothing to compare with; and the corrosivity section said the temperature was "not reported". Such a row is now "No guideline value", its remark says the unit could not be read and that the value is left out of the indices, a warning, `value_not_used`, says the same, and the verdict rests on the graded rows. "oC" and "ºC" are degrees Celsius. Where a temperature was reported in a unit that cannot be read, the corrosivity assumption reads "Temperature assumed 25 C (the temperature is reported in a unit that could not be read)." Both temperature sentences are in `quality.yaml`.
- **A clock read as a quantity.** `units.read_quantity` and `readQuantity` read a time as its first number: "2:00" under "Time (hh:mm)" was 2 minutes and "0:30" under "Time (mm:ss)" none. The pumping readers already read their times through `read_time`; `read_quantity` now reads every time through it as well, so a clock is a clock wherever a time is read. The audit also proposed refusing a two-part clock under a header that names no clock format; that is not done, since the pumping test audit chose to read "5:30" as hours and minutes, as Excel reads it typed into a cell (QUESTIONS.md item 13).
- **The gravel pack under the seal.** The design kept its screens below the seal's foot but not below the pack the rules put above the top screen, and the basis printed the rule's "2 m above the top screen" whatever the pack reached. Under a 20 m grout in a 10 inch hole with 4 inch casing, a fracture logged at 20-26 m was screened from 20 m, with the pack clamped to the seal's foot and grout on the screen; a screen recorded as installed at 15 m in a 20 m grout had its pack from 20 m, 5 m below it. Both were said to have a pack "2 m above the top screen", with no flag; `reference.json` held both engines to the second. A screen the design places now starts at least the pack's height below the seal wherever the annulus takes a gravel pack or a formation stabiliser: 22-26 m there. A 19 mm annulus, the default hole and casing, takes no pack and keeps the seal alone as before. A zone inside that room is said to be ("it lies within the 20 m grouted interval with the 2 m of gravel pack under it"), as is a hole with no room left. The basis now says where the fill's top falls against the top screen ("5 m below the top screen", "level with the top screen", "1 m above the top screen"), and a warning, `gravel_pack_short`, names the seal, the screen and the depth a top screen needs: "The formation stabiliser is drawn from 20 m, the foot of the 20 m seal, and the top screen is at 15 m: the design rules put the formation stabiliser 2 m above the top screen, so that grout placed on it cannot reach the screen. A top screen at 22 m or deeper leaves room for it." Moving the screen rather than shortening the pack is a choice (QUESTIONS.md item 14).

What moves. The example reports read word for word as before and are left as committed: the Dr Timbo sample reports every result in its guideline's unit and on its basis, and its 6.5 inch hole takes no pack. In `reference.json` the `verdicts` case with both ions reported as nitrogen gains the two remarks, `design_cases` case 10, the as-built record, says its stabiliser runs "5 m below the top screen" and gains the warning, and every other value there is as it was. The factors are the molar masses the balance and the hazard index already used, so a sheet that reports the ions has the hazard index it had; nitrite's is 46.005/14.007 = 3.2844 (14.007 + 2 x 15.999), where the audit quoted 3.2845. Parity gains 496 checks, 3743 in all: a new `quality_units` section of 23 samples and 5 sheets, each compared on its statuses, reasons, remarks, flags, balance, hazard index, index, corrosivity, verdict and recommendations, with 26 unit spellings, 22 parameter names and 11 time cells; and 8 more design cases (the fracture at the grout's foot in a wide and in the default hole, a zone in the pack's room, a shallow fracture under the rule's 6 m seal, a hole with no room, and analyst screens below, level with and short of the pack). `tests/test_quality_units_design.py` (52 tests) holds each finding in Python, and the browser's engine to Python's in a Node vm; each finding's tests fail on the code before this change. The fuzz suite's laboratory sheets learn to write the same water another way (nitrate and nitrite as N by name and by unit, calcium, magnesium and bicarbonate as CaCO3, counts per 100 mL with a space or a numero sign, a temperature in "oC", a unit after the number and in the result header), and the suite passes as before (38 passed and its one expected failure), with no saved case's expectation moved. `reporting/__init__.py` lists the calibration report among its lazy submodules, which `tests/test_imports.py` found missing when run alone. Because `gwt-core.js` changed, every inversion saved in the browser is inverted once more the first time its project is reopened. The user guide's sections 4 and 5 say how the design keeps room for the pack and how a laboratory sheet's units and bases are read, the README lists the reading among the readers' behaviours, and QUESTIONS.md item 14 lists the three choices.

### What is still open from these steps

- A page with no service worker yet (a first visit, or `file://`) fetches its bundles on demand, so a deploy landing between first paint and a later bundle could mix two releases in one tab. A release query on the bundle URLs would close it; the service worker already matches with `ignoreSearch`.
- The Python cache key names the numpy and scipy versions but not the BLAS build, and the browser's names the release and the engine's digest but not the JavaScript engine, so a project file from another machine or browser returns that machine's inversion.
- Any change to `gwt-core.js`, or to the hashed Python modules, invalidates every saved inversion, even a change that does not touch the inversion. That is conservative by design.
- The Streamlit "Run inversion" button still always inverts; only loading a project uses the saved inversions.
- After a project is reloaded in the Streamlit app, the cost estimate and the design's pump intake are not rebuilt; main behaved the same before step 1.1.
- IndexedDB storage is tested in Chromium only. Firefox and Safari, including Safari's private mode and IndexedDB on `file://`, are untested.
- The VES quadrature's cut (a tail of 1e-8 of the least resistivity), the converged label's test (a Gauss-Newton decrease of at most 1e-6 of the misfit) and the one degree of freedom a short sounding keeps are choices, measured but not standards, and want a geophysicist's confirmation (QUESTIONS.md item 11). The label errs towards "not converged" in an equivalence valley: 33 of 78 fits it does not call converged were at a minimum.
- Neither app shows why an inversion stopped or whether it converged; what to report for one that ran out of iterations is still the owner's question below. The two engines' iteration counts for a full inversion differ, by their last bits, and parity compares them only where a fit runs to its cap.
- Still for the owner from the fuzz suite: the two knife-edge VES cases (poorly resolved boundary, uniform half-space), whether reports should flag a resistivity the data do not determine, whether a four-layer model with no resolved boundary should be offered, and what to report for an inversion that ran out of iterations. The fuzz suite no longer fails on a knife-edge inversion; whether the inversion should search a flat valley further, or report a model the last bit decides between as one, is a question of method for the owner.
- The reports' citations keep two wordings for five works, one per app; settling each pair is a content decision for someone with the documents.
- Pyright still excludes 42 modules, and `gwt-core.js` is strict less `noImplicitAny`; the other browser scripts are checked loosely. Each can be tightened one at a time.
- Neither co-pilot has run on a phone: sound, vibration, GPS accuracy and timers on a sleeping Android or iOS device are untested. A screen wake lock would guard against the likeliest field failure, a phone that sleeps through readings.
- The co-pilots' limits that are choices rather than standards are listed in their sections above and want a hydrogeologist's or geophysicist's confirmation.
- The pumping test readers refuse a sheet of times of day rather than convert it, which needs the minute the pump started and the day each reading fell on. A stated length of each step that disagrees with the steps' own readings is not flagged; the stated length governs. The four choices the pumping test audit made (when a level has stabilised, a two-part clock read as hours and minutes, the hour past which an earliest reading is a time of day, and a recovery on the test's clock) want a hydrogeologist's confirmation (QUESTIONS.md item 13).
- A yield range past 100 m3/h is printed to two significant figures in exponent form, as it was before it was labelled: the handpump line in `reference.json` reads "90 m3/h (range over the assumptions, 75 to 1.1e+02)".
- A number in a unit the toolkit cannot read is refused even on a microbiological row (E. coli 12 "colonies"), where "Present" in it is graded as above zero. A name such as "Calcium (as CaCO3)" is a parameter the table does not know, and "mg/L Ca" or "mg/L CaCO3" written without "as" is a unit that cannot be read, so such a row is refused where it has a limit and left out of the indices where it has none. "Ammonium (NH4+)" is held to the guideline for ammonia as N. A calcium converted from CaCO3 has no limit, so its remark is "No guideline value" and only the info flag gives the conversion. The three choices of the water quality, units and design audit want confirmation (QUESTIONS.md item 14).
- The design basis names a whole interval of the log that a screen covers in part: "the fractured or water-bearing intervals logged at 7-12 m" beside an 8-12 m screen whose top metre the pack's room took, as it did beside a screen the grout cut short. Only a fracture zone screened in part says so.
- A Theis fit through a level that has stabilised is still adopted, and the yield on it can be called established beside the flag saying that the projection to the design period is not the governing check: the stabilised-tail sheet in `reference.json` adopts Theis at 31.8 m2/day for an aquifer of 20. What the yield should rest on there is a question for the owner.
- Phones may strip a photograph's GPS, and sometimes all its EXIF, before a page sees the file; untested on a real phone. EXIF is read from JPEG only, so PNG and HEIC photographs fall back to the attach time and the device's position.
- A device position is taken at attach, so a photograph attached later in the office carries the office's position unless its own EXIF has one.
- A hand-edited project file whose photograph record has a non-numeric position makes the Python report raise where the browser prints NaN.
- The field kit prints a constant-test sheet only; a step test uses the blank template and the step-length rule printed on the sheet. Neither reader uses the sheet's QR code yet (step 10.1).
- The kit's QR code names the project by its reference, else its name; the Streamlit app has no reference field, so the two apps can print different codes for a browser project that has one.
- Neither app reads the driller's daily report back, and the drilling co-pilot's cuttings photographs do not reach the completion report's photo plate.
- The drilling co-pilot's penetration rate counts every pause inside an interval; nothing deducts standing time.
- A resistive layer is basement only where nothing conductive lies under it in the fitted model, and that includes clay-rich ground and a conductive layer the model puts below the depth of investigation. Both are choices that want a geophysicist's confirmation (QUESTIONS.md item 12).
- The splice's shifted modes ("first" and "last", reached only through the Python API and the browser engine's `spliceMode` option; the inversion merges) still scale a segment by the ratio of the plain means at an overlap, so a zero reading there scales the whole segment to 0.
- The VES range's chains start from distinct local minima and do not jump between them, so each equivalent model is weighted by how many chains start in it rather than by its posterior mass; sampling across layer counts is not attempted. The range is not in the fuzz suite.
- The pumping bands under-cover their nominal 80 percent (64 to 74 percent, 48 with correlated errors) and no cheap principled widening was found; the reports say so. The regime classifier can name a regime from reading scatter where the derivative is small.
- The two apps place a VES point that has no coordinates of its own at different site positions (Python the sheet header's, the browser the stored site's), a split that predates step 3.3 and now also gives such a point different odds; which is right is a decision for the owner.
- The cost distribution does not carry the uncertainty of step 3.3's odds into the dry-hole draw, has no correlation between spread groups, gives a programme one depth and one survey point for every site, draws the outer 5 percent of depth evenly out to the extreme kept models (fattening the tails of a skewed range), and has not been calibrated against real Sierra Leone tenders or outturn costs.
- The value of one more measurement does not model where the extra sounding goes or how it correlates with the first, treats the alternative site as an endless supply at its odds, and has no likelihood ratios of its own for a profiling line.
- The app pages show the decision lines only in reports and gates; the pumping figures have no fan, because the bootstrap does not keep its refits.
- Neither app saves an elevation model, its analysis or its figures with a project. The desk study (step 4.4) carries the relief, the lineament candidates, their rose and the survey plan from the press on show; the other reports carry none of the terrain figures nor the topographic map, and the geophysical reports still say that no elevation model was supplied even when tiles were analysed on Site & maps.
- `.asc` and `.xyz` grids are read only by the Python app, one file at a time and whole; a whole-file read of a GeoTIFF (the command line and the tests) is not capped as a window read is.
- The browser's PDF reader still inflates with DecompressionStream and refuses LZW; the synchronous decoders could replace both.
- The reader's and the terrain card's figures are from Chromium and Node only; Firefox and Safari are untested (the figures' PNG export rasterises an SVG that holds an embedded image, tested in Chromium only), and no phone has read a tile or analysed one.
- The 118 KB the reader adds to the first screen, the 92 KB the analysis adds and the 67 KB the terrain pages add could be won back by minifying the scripts, which step 1.5 left for later.
- The Streamlit server keeps 30 to 90 MB from each press of *Analyse the terrain*, and a later session's upload adds more, so presses in one server creep upward: four at the 1,500,000-cell cap peaked at 535, 630, 680 and 694 MB. The cap's rule covers two presses; a per-session release (dropping a closed session's upload and figures, or the allocator's arenas) was not measured.
- The fill caption's share of drainage-line cells routed across flats can still print 0% or 100% at the extremes; the raised share now says "less than 1%" with the count of cells.
- The whole-press memory measure in the Streamlit server, the browser's memory probe and the ad hoc Pyodide run were made with scratch scripts that are not committed; `bench/README.md` gives the method by hand.
- Nothing tells a lineament candidate that follows a fracture from a straight valley the relief made by chance: in fractal terrain, besides the ten valleys planted in each window, the method found 80 to 160 other candidates in each window about 20 km square. Checking the candidates against mapped fractures, dykes and contacts, and the settings with them, wants a geologist and a geological map.
- The rose counts every strike within the square shown alike, so a window much longer one way than the other favours lines along its long side; the windows the planner makes are square.
- A drainage threshold of 0 km², which only a direct call to the Python API can ask for (the controls part c adds start at 0.05 km²), makes every land cell a line: at the cap, 1.25 million lines in about 22 s and 1.9 GB, the cost of the objects the API returns.
- The survey plan keeps clear of the water points loaded when the terrain is analysed; water points loaded afterwards need another press in either app. It knows of no latrine, building, refuse dump or burial ground, the separation table records no source for its distances, and WPDx does not map every well, so every peg is a proposal for the field.
- Only the desk study carries the survey plan, and neither app saves it with the project. The site project of the Interactive tab does not carry the plan's layers; the plan has a project of its own.
- The ledger of predictions and outcomes (step 5.1) records a prediction only when asked, by its button or the geophysical report; a survey interpreted and drilled without either has no forecast to score. The range of models is still not saved, so a prediction carries a band only where the range was sampled before it was recorded. The calibration report (step 5.2) scores only forecasts recorded before drilling, so such a survey adds nothing to it.
- The WPdx+ inventory as read here carries no depth or yield, so the desk study's depths and yields near a site are only the earlier projects' in the portfolio loaded; a national borehole register would fill the gap. The desk study is built from what the session holds, so it is not saved with the project either, and the browser app keeps the water points and the portfolio across a project load (the desk study measures them from the site, so another site's are left out unless they lie within reach).
- Drawing the four area maps leaves the Streamlit server 50 to 70 MB higher, and a terrain press at the cap from another session after it can go over the 690 MB rule (702 to 731 MB after *Generate area maps*, 703 MB in one of five servers after a desk study; `bench/README.md`). The rule's two presses alone hold; what the area maps keep wants its own change.
- The GPX was checked by parsing it as GPX 1.1; no phone app has imported it and walked to a peg.
- A candidate and a drainage line are placed from a model of 30 m cells or coarser, so a peg moved to clear a 20 m stream ring is cleared from the line the model draws, which may lie a cell or more from the stream on the ground.

## 0.3.0

### The release

This is the first tagged release. The version is 0.3.0 in pyproject.toml, and the browser app's About page now names it: `build_webapp_data.py` writes the version into the bundle, and a test holds the bundle, the package and pyproject.toml to one number. A tag `v0.3.0` pushed on main runs `.github/workflows/release.yml`. The workflow refuses a tag that does not match pyproject.toml or a changelog with no section for the version. It checks that the committed service worker is current, builds the wheel, the sdist and the example packs with `nox -s release`, and publishes them as a GitHub Release. The release notes are this section, and `release.json` records the commit, the SHA-256 of every asset and the web app's release identifier from `docs/sw.js`. From this release on, the changelog has one section per version.

### The browser engine runs in a worker (PLAN.md step 1.2)

The VES inversion and the pumping test fits now run in a Web Worker, docs/js/gwt-worker.js. It imports gwt-data.js and gwt-core.js and answers three requests: invert (one sounding), analysePumping and recompute (what the app derives from the sheets once the page has read them, since reading a workbook needs DOMParser). Before, inverting the two Rokel soundings held the page in a single task of 2.7 s on this machine (11-12 s with the CPU throttled four times), and there was nothing to press to stop it. The page calls the worker through GWT.engine, a promise per request. A work bar in the house style shows what is running, how far it has got and a Cancel button. Cancel terminates the worker, which is the one way to stop it in the middle of a fit, and the next request starts a fresh one. The newest recompute or inversion run wins, and a stopped run leaves the results it would have replaced. Opened from file://, or wherever the worker fails to start, the same tasks run on the page, on a structured clone of the request, and give the same answers, compared in smoke.mjs as whole object graphs. There the bar goes up before the page stops drawing, so Cancel is read between soundings. The step test result's drawdown_at and efficiency_at methods became C.stepDrawdownAt and C.stepEfficiencyAt, because a structured clone cannot carry a method. The progress hooks read nothing back: parity.mjs passes 1377/1377 with reference.json untouched. build_offline.py now follows importScripts in the shell's scripts, so the worker's imports are precached, and offline.mjs checks that the worker starts with no network. Measured with Playwright on the Rokel sample, headless Chromium, 3 runs each: at 1x, no main-thread task over 50 ms appears from the click to the result, where before the longest was 2.67-2.76 s. Inversion wall time is about the same, 4.6-4.8 s before and 4.8-5.2 s after on a machine shared with other work. At 4x the page's own tasks during the run are 53-98 ms rather than 11 s. What remains is drawing the loaded sample and the first, cold interpretation of a model on the page between soundings. Chromium does not throttle a worker, so throttled wall times do not compare. smoke.mjs now collects Long Tasks and holds the page to none over 50 ms while the Rokel soundings invert and a pumping test is analysed, at 1x. It also checks that timers and scrolling keep going, that Cancel works in the worker and from file://, and that the readings do see an inversion run on the page.

### PR #52's performance work, carried onto main (step 0.1)

PR #52's performance work is on `main` now. It was carried over by hand rather than replayed: `main` had moved about 98 commits since the PR branched, and had already solved part of the same problem its own way.

- **Forward model and inversion.** The VES forward model evaluates a sounding's spacings in one pass over the quadrature. The inversion takes its Jacobian's five nudged models in one pass too. The arithmetic is unchanged: 300 random models (Schlumberger, finite-MN and Wenner, thin layers included) and 24 synthetic inversions, uncertainty factors included, hash identically to `main`'s. That needed one correction to #52. Its vectorised finite-MN step moved 18 of 951 readings by one unit in the last place, because a scalar `L**2` goes through `pow()` and an array's goes through `x * x`. So that step still combines one reading at a time. The quadrature tables are now built on first use rather than at import.
- **Imports.** The subpackages bind their plotting, workbook and report modules when first used. Importing `groundwater.hydraulics` for an analysis no longer imports pyplot, and importing `groundwater.reporting` no longer imports python-docx.
- **Boundary lookups.** The two copies of the ray cast behind `district_of`, `chiefdom_of` and the coverage lookups are now one, in `groundwater._geometry`. It takes the crossing count over a whole ring at once and holds every ring's bounding box in one array, so a lookup no longer walks all 256 chiefdom rings in Python.
- **Bundled data.** Every bundled data table and map layer, the app's district table included, is read through `groundwater._resources`. Coverage and mapping share one parse of the chiefdom layer.
- **Figures.** `figure_context` now closes any figure a plot function leaves open when it raises.

Two parts of #52 are not replayed, because `main` already does the job. Placing a national pull of water points is done by `coverage.assign_chiefdoms`. Caching the tables is already done where it is repeated: an `lru_cache` holds the WHO table, the provenance record, the crosswalks and the map layers, and the app caches the unit rates and checklists. Those parse in under half a millisecond in any case.

Measured on one 4-CPU machine shared with another job (load average about 3), alternating `main` and this branch, three rounds of small timing scripts:
- One `district_of` lookup goes from 25 ms to 0.03 ms.
- The forward model on Rokel A goes from 0.90 ms to 0.55 ms, and the Jacobian from 4.6 ms to 2.2 ms.
- Inverting both Rokel soundings goes from 4.8-7.8 s to 1.9-4.1 s (noisy).
- Placing 20,000 in-country water points by district goes from 0.13 s to 0.065 s. Points off the chiefdom layer still take the per-point seam pass, and it is unchanged.
- In a fresh interpreter, median of five: importing `groundwater.reporting` goes from 1.1 s to 0.13 s, `groundwater.mapping` from 0.88 s to 0.13 s, and `groundwater.hydraulics` from 0.81 s to 0.53 s.

Answers, reports and the worked examples are unchanged.

### PR #54, landed as three parts (step 0.1)

The district check no longer reports a site just over a drawn border as being in the wrong district. The chiefdom rings it judges by are simplified to within about 89 m of the geoBoundaries line, so a stated district is now accepted when the point is inside it as drawn or within 90 m of its edge. Both engines do this. Measured over one verified interior point per chiefdom, stated as each of the fifteen districts it is not in, the tolerance lets none of the 2,490 wrong statements through. In random samples of placed points, just under one percent lie close enough to another district's edge for it to apply. PR #54's move of the detached Maforki fragment was not taken: that ring stays withheld for review until someone with a source moves it.

The GeoLibre project from both apps now draws the separation distances in site_separation_distances.csv as rings round the wellhead, so a latrine 20 m away or a burial ground 1 km away can be seen over imagery rather than read from a table. The rings are true to the ground to within 0.08 m and are drawn only round a GPS fix. Each says it is ground that has to stay clear, and that the table has no recorded source. They add about 61 KB to a site project.

The continuous survey surfaces (iso-resistivity, depth to bedrock, aquifer thickness, bedrock elevation, transverse resistance) and the drill-target score are now also written as a GeoTIFF beside each picture, so they can be sampled, contoured or laid under imagery in a GIS. A raster is written only for a surface clipped to the surveyed ground and with no lower-bound point. It holds NaN outside the ground and ohm-m rather than log10. A line of soundings, or a map with an "at least" beside a point, stays a picture. The protective-capacity map, drawn in classes, never gets a raster, because a raster would give back the precision the classes withhold. The Streamlit app offers each raster it keeps for download under its map; the browser app draws the surfaces only as pictures, and both say so. The writer needs no dependency. rasterio is a test-only dev dependency that reads each file back, so a raster in the wrong place cannot pass as correct. A 220 by 220 surface is 193,898 bytes and takes well under a millisecond to write, and drawing a five-sounding map took the same time, within noise, with the raster as without it.

### PR #17's wizard fix, ported (step 0.1)

A sounding that will not invert no longer crashes the Streamlit app or costs a loaded project its costing values. Before, the siting step dropped the wizard's load grace before inverting anything and had no guard around the inversion. A workbook whose readings parsed but would not invert therefore ended the run with a stack trace and stored no result. The loaded project's adjusted costing depth was then reset on the next visit to the costing step: in the test case, 85 m came back as the 72 m prefill. Now the failure appears as an error naming the sounding, and the run's progress bar is cleared. Nothing from the failed run is stored. The last successful siting result stays in place, and when there is one the error says that the results shown come from it. The grace is dropped only once a new result has been stored. This is the fix from pull request #17, ported by hand because that branch shares no history with main. The browser app already limited a failure to its own sounding and needed no change. It keeps the other soundings and names the one that failed, whereas the Streamlit app rejects the whole run.

### One command for the checks, and a CI that checks more (steps 0.2 and 0.6)

`nox -s check` now runs the whole check sequence in one command: ruff at the version the dev extra pins, the pytest suite, the bundle freshness checks, `make_reference.py --check`, the four browser suites, and a rebuild of the Depth Spine. CI calls the same nox sessions step by step, so a command changed in one place changes in both. The one thing CI adds is the Python version matrix: a local check covers only the interpreter it runs on. `nox -s build` regenerates the generated files in the order each depends on the last. The Depth Spine goes first, because the demo inlines the package that carries it, and `build_offline.py` goes last. `nox -s examples` reruns the worked examples and their index. `nox -s release` puts the wheel, the sdist and the example packs in `dist/`. The sessions run in the current environment rather than in virtualenvs, because that is the environment CONTRIBUTING.md installs into and the browser suites need Playwright from `node_modules`.

CI now also builds and lints the Depth Spine workspace (`tsc`, `oxlint`, both Vite builds). It fails if the committed build under `src/groundwater/depth_spine/` is not what the source beside it produces, and it counts a new untracked asset as a difference, because Vite names assets by content hash. Here, with Node 22.22.2 and npm 10.9.7, a fresh build is byte-identical to the committed one.

The 59 tests that drive the app through AppTest, regenerate the examples, or took ten seconds or more are marked `slow`. On pull requests they run on Python 3.12 only, in a job of their own that runs beside the fast suite on all four versions. A new nightly run takes the whole suite on every version. Measured one after the other on a shared 4-CPU machine, the full suite took 930 s, the fast part 269 s and the slow part 540 s. On the run for pull request #72, the last before this change, the Python 3.12 test job took 11 min 28 s and the whole run 11 min 29 s. This split should bring a pull request run to roughly 7 minutes; that is an estimate, and no CI run with the new workflow exists yet.

The Playwright browser download and the npm downloads are cached, the pip cache follows `pyproject.toml`, every action is pinned by commit SHA, and the workflow can only read the repository. CI's lint job reads the ruff pin from `pyproject.toml` rather than repeating it. Dependabot proposes grouped weekly updates for the actions, the Python requirements and the Depth Spine's npm packages.

### A performance baseline (step 0.3)

There is now a performance baseline to quote against. `bench/run.py` times the Python package on the bundled examples: importing each subsystem in a fresh interpreter, one forward-model call, inverting each sample sounding, analysing each sample pumping test, building each of the ten reports, recomputing each example saved as a project, and one run of the Streamlit app's script through AppTest. It takes one warm-up and five samples and reports the median with the interquartile range. It holds numpy to one BLAS thread: on this shared 4-CPU machine, OpenBLAS's thread per CPU made the Rokel A inversion 2.3 times slower and about ten times noisier (3.5 s against 1.5 s), which would have made two commits impossible to compare. `--compare bench/baseline.json` prints each measure beside the baseline with the ratio. `bench/web.mjs` loads the browser app cold with the CPU slowed 4x and DevTools' "Slow 4G" network (562.5 ms, 180,000 B/s down). It records first paint, time to interactive by Lighthouse's definition, the bytes sent before first paint, and the wall time and longest main-thread task of a Rokel re-inversion, started from the Geophysics page and judged finished by what the page shows. Time to interactive counts requests still downloading, taken from the DevTools protocol, because Resource Timing lists a request only once it has finished. In the committed baseline (provisional, taken while the machine was shared) the app first paints at 2.5 s after 65 kB and becomes interactive at 16.2 s. A report takes 3 to 6 s to build, most of it drawing the area maps; the asset placard takes 0.17 s. Importing `groundwater.reporting` costs 1.4 s. A Streamlit rerun with every sample loaded takes 3.9 s. With the inversion in the worker, the longest main-thread task during a re-inversion is 175 ms. On c3cb529, where the inversion ran on the main thread, it was 8.9 s (one run). Chromium will not throttle a worker, so the inversion is also timed unthrottled: 3.6 s in the worker against 3.8 s on the main thread (one run). The worker changed where the work runs, not how long it takes. `bench/baseline.json` is committed with each release. The one committed now is provisional, because it was taken while the machine was shared.

### The small untruths (step 0.5)

The Depth Spine workspace no longer asks Google for its fonts. It was the one page in the toolkit that did: both of its builds linked the Google Fonts stylesheet for IBM Plex Sans, IBM Plex Mono and Space Grotesk. Offline it therefore drew in fallback faces, and online every render told a third party that a borehole was being looked at. The faces now come from the package's brand folder, where the main app already keeps its own. IBM Plex Sans 400 to 700 and IBM Plex Mono 600 were added there, copied unmodified from @fontsource/ibm-plex-sans and @fontsource/ibm-plex-mono 5.3.0 (SIL OFL 1.1), and IBM's Plex Sans copyright line was added to the licence. The component build ships the files beside its script. The single-file page the browser demo shows inlines them, because it is handed to the browser as a string and cannot fetch a relative file. The licence header had pointed to a manifest.json that was not in the repository. It is there now, recording the source and SHA-256 of every font file, and the test suite checks the hashes. offline.mjs loads both builds with every request off the machine refused, and requires that none was made and that all three families actually loaded. Against the previous build the same checks fail on the Google request. A build from a clean `npm ci` is byte-identical to what is committed. The static workspace grows from 257,329 to 469,250 bytes, and the WebAssembly demo, which inlines the package, grows from 3,694,714 to 4,277,166 bytes.

DEPLOY.md no longer tells the reader to add `anthropic` to requirements.txt, which already installs it. It pins Playwright 1.56.1 as CONTRIBUTING.md and CI do, and lists the offline and review checks CI runs. It had claimed the standalone app made no external fetches; it now says plainly that two of its buttons go online. It also says that docs/icon.svg is generated. QUESTIONS.md item 7 had still described district bounding boxes. It now says what the checker does: it places a point through the chiefdom polygons and the chiefdom-to-district crosswalk. It names the two limits that remain. First, seams between chiefdoms, left because the layer's build simplifies each ring on its own, which a 50 m tolerance bridges. Second, the withheld Maforki fragment. It also names the boundary data and gazetteer that would help. docs/icon.svg was a hand-made copy of the brand icon. make_brand_assets.py now writes both from one drawing, and a test fails if either is edited on its own.

### What this release leaves open

- Editing a discharge on the Pumping test page while an inversion runs stops the inversion, and nothing re-runs it. Every recompute has always dropped the inversions; the worker only makes this reachable, because the page now stays usable while one runs.
- With the CPU throttled four times, the page still has tasks of 53-98 ms during an inversion. One is drawing the loaded sample. The other is the first, cold interpretation of a model, which could move into the worker's invert reply.
- `bench/` does not yet time the test suite, or the placement of water points outside the chiefdom layer. That placement still takes the per-point seam pass, 5.5-6 s for 20,000 points spread over sea and neighbouring countries.
- The separation-distance rings are drawn in the GeoLibre export of both apps, not on the matplotlib site map. The loader's docstring cites FGN/NWRI 2010, and data_provenance.yaml records no source; the two should agree.
- `web/make_brand_assets.py`, which the icon test names as the remedy, also rewrites icon.png and logo.png, and those do not reproduce byte for byte under matplotlib 3.11.
- The WebAssembly demo inlines the Depth Spine component build, which cannot run under stlite, and grows by 0.58 MB with the fonts.
- On a failed sounding the two apps differ: the browser keeps the other soundings and names the failed one, and Streamlit keeps the previous run. Neither behaviour is documented.

### The repair roadmap

What stood here as "Changes pending release" before PLAN.md, the work of
the repair roadmap (ROADMAP.md), follows unchanged.

#### Corrections to the previous entry

The entry that stood here described a body of work that was never
uploaded: the pull request carrying it said so in its own description
and was merged anyway. Most of what it announced is not in this
repository, and some of it contradicted what the code does. It has been
replaced rather than annotated, because a release note nobody can check
is worse than none. What it claimed, and what is true:

- "Twelve reproducible example cases" - there are three
  (`examples/CATALOGUE.md` counts them from the files).
- "PDF previews" - none are produced or committed;
  `examples/build_catalogue.py --previews` renders them where the machine
  has LibreOffice and says so plainly where it does not.
- "Demonstration evidence cannot pass the technical readiness gate" -
  the Dr Timbo example supplied its own GPS position so that it would.
  That has been removed; see below.
- "Versioned inventory snapshots" and "IndexedDB persistence" - neither
  exists anywhere in the toolkit. The browser app mirrors a session to
  `localStorage` and saves a project file; that is all.
- "Population-weighted straight-line accessibility" and "closure and
  monitoring decision reports" - no such code exists. The census
  populations the toolkit does carry are chiefdom totals, which is the
  wrong resolution to weight a distance by: that needs settlement points
  or a population surface, and neither is here.
- "Sixteen derived display districts" - see the boundary note below. The
  sixteen current districts are carried by the crosswalk and the
  population tables, and a point is placed in one through the chiefdom
  polygons; there is no sixteen-district polygon layer, and this
  repository does not hold the data to derive one honestly.

#### What changed

A sounding is read to the depth it resolves, not to the length of its
array. A Schlumberger sounding resolves the ground to about half of its
largest AB/2; the interpretation used to take the spacing itself, so a
conductive half-space below 8 m became a "water bearing zone 8 m to
80 m", an aquifer 72 m thick and a recommendation to drill to 80 m, at
both Rokel points, from data that had seen 40. One rule
(`VESConfig.depth_of_investigation_factor`) now sets how deep the
interpretation, the model panel, the layer column, the section and the
drilling-depth cap reach. A water-bearing half-space is an open-ended
zone: "8 m to at least 40 m", flagged `basement_not_resolved`, with the
thickness a minimum and the drilling depth a minimum, and it is called
what it is - a weathered zone whose base the sounding never reached -
rather than "fractured bedrock with groundwater in fractures", which
fresh gabbro at 47 ohm-m is not.

The ranking can now see how well a model fits. Neither Rokel model
reaches the 10 percent misfit target; the report preferred B (2), fitted
to 26.8 percent, over A (1) at 13.3, on 2.7 ohm-m of half-space
resistivity, and said nothing about either fit. A model above the target
now carries a `poor_fit` flag and a sentence in its narrative, the
points are ranked on their suitability discounted by a confidence that
the misfit and an unresolved basement lower, the suitability table
prints that confidence, and two points whose weighted scores are within
three points are said to be indistinguishable rather than 1st and 2nd.
The one ranking is assigned once and read everywhere, so the summary,
the preference table and the scorecard cannot name different points.
The sounding block lists the models tried, names a boundary the
uncertainty factor shows to be unresolved, and, where an earlier
interpretation is supplied, tables it beside the toolkit's with its
reported misfit and the misfit this toolkit computes for it on the same
readings (35.8 percent against the 21.5 reported for Rokel A (1)). Two
readings at one AB/2 that disagree by more than a fifth at an MN change
are a warning naming the pair, not an information note. The preference
table's resistivity column is named for what it holds, the layer
resistivities, and the layer column figure is captioned as one rather
than as a pseudo-section. The browser engine mirrors all of it, and the
parity suite now holds the two engines to the interpretation's zones,
flags, confidence and narrative and to the preference table word for
word.

The survey-scale figures now show what was measured and refuse what was
not. Three soundings on a straight line, the standard field layout,
used to crash the geophysical report and the Streamlit maps page with a
Qhull "initial simplex is flat" error that no handler caught; a survey
that encloses no area now gets its values drawn at the points under a
note saying why there is no surface, and the report catches the error
class Qhull actually raises. The Rokel example hard-coded its two
soundings 60 m apart on the geoelectric section when their own
coordinates put them 20.7 km apart; the section is now drawn from the
recorded positions, no boundary is correlated across a gap wider than
ten times the depth of investigation, and a survey with no closer pair
gets no section and a sentence saying so ("20,751 m apart, about 519
times the 40 m they resolve"). The apparent-resistivity pseudo-section,
the one figure that shows the readings rather than an interpretation of
them, is drawn from two placed soundings, paints no colour across a gap
the correlation rule excludes, and keeps its station labels off the
readings; the protective-capacity map is drawn from the same two. The
report lists, under "Not drawn from this survey, and why", every figure
it could not draw. The drill-target map can be walked to: the
recommended point is a star with its grid coordinates printed beside
it, every point is labelled by rank and score, a tie within three points
is written on the map, the caption describes what was drawn rather than
a surface that was not, and the study-area map stars the recommended
sounding instead of hiding it under a marker for the runner-up. Maps of
an elongated survey keep their proportions and at most five round
grid labels an axis, the resistivity colour scale is fitted to the
models on the figure rather than clipped at fixed limits, and both
Streamlit pages infer the UTM zone from the easting instead of assuming
two different zones.

A pumping test is now worth what it measured. Dr Timbo's constant test
pumped for thirty minutes at 2.93 m3/h from a 5 inch casing and drew the
level down 32.8 m; by Schafer's rule the water standing in the casing
supplies such a pump for the first two hours, so the whole test was the
borehole emptying rather than the aquifer responding, and the Theis fit
duly returned a storativity of 0.18. The report adopted a transmissivity
of 1.4 m2/day from a recovery line that met t/t' = 1 at 21.7 m of
residual drawdown, where the method requires zero, and the completion
and handover reports printed a safe yield of 0.97 m3/h and "successful
and sustainable" without the pumping report's own "treat as indicative".
The analysis now computes the casing-storage period from the casing and
riser diameters, checks the recovery intercept, refuses a storativity no
aquifer has, fits no drawdown line to a first step that ends above the
stated static level, and reads the recovery after a step test against
the discharge-weighted equivalent pumping time. A method that fails any
of these is reported with its reason and not adopted; when nothing
fits to standard the best of the poor fits is adopted and said to be.
Every yield carries a confidence, established or indicative with its
reasons, and every report that prints the yield prints that beside it:
the completion report reserves "successful and sustainable" for an
established yield, and the readiness gate holds "Yield established"
unmet for an indicative one. Dr Timbo's yield is 0.39 m3/h, indicative,
on a 0.54 m2/day Cooper-Jacob line adopted as the best available.

The pump goes where the drawdown the yield was computed on exists. The
intake used to be raised to just clear the drawdown at the safe rate,
which put Dr Timbo's pump at 39 m, three metres above the 42.3 m the
test itself had reached, and spent the safety factor on lifting the
pump; it is now set below the static level plus the dry-season reserve,
the usable drawdown and the submergence margin, never above the deepest
level the test reached, so Dr Timbo's goes to 52 m and the basis says
why. A report prints one pump depth, the deeper of the yield's and the
drought scenario's, instead of 39 m in one paragraph and 40 m in the
next; the test's own pump setting is stated beside it; every depth is
below the top of the casing, the datum the sheet records levels from,
rather than a ground level nobody measured the stick-up to. The
parser flags a level recorded below the pump intake, and a report whose
levels are flagged says they are inconsistent rather than that the
curves are valid. The overview figure labels every step in its own
colour with the legend under the axes, the step figure draws the intake
and the hole bottom, a two-step Hantush-Bierschenk line says it is
exact by construction instead of printing R squared 1.000, the specific
capacity carries its rate, drawdown and time, the test type is written
in words, and the browser engine mirrors all of it with the parity suite
holding both engines to the same confidence, reasons and pump depth.

The borehole design reads the driller's own words. Dr Timbo's log says
"fracture zone 49-52 m" on the 45-50 m row and "fracture zone 60-62 m"
on the 55-60 m row; the screens were set on the five-metre rows, so one
covered a metre of the first zone and the second sat behind plain
casing. A depth range named against a fracture phrase is now the
target, with a metre of screen either side, and the lithology column
draws the zone at those depths with the rock around it classed as what
the driller called it, from one class table shared with the Depth Spine
rather than three. The log records grouting to 20 m; the drawing showed
a 6 m seal with a screen and a gravel pack inside the grouted interval.
The recorded grout is now the seal, nothing is screened inside it, and
the 12 m seepage in clayey laterite is cased off rather than screened,
with the basis saying so. The drilled diameter comes from the log's
diameter column, and the annular fill follows the annulus it leaves: a
5 inch casing in a 6.5 inch hole leaves 19 mm a side, into which no
gravel can be poured, so the drawing, the summary and the bill of
quantities carry no pack instead of the 2-4 mm one the design's own
flag said could not be placed, and the completion and handover reports
print the design's warnings. A pump intake that the yield puts inside a
screen is moved into plain casing beside it, and the reports print that
depth. The drilling template gains a "Screens installed" field; a
drawing built from it is captioned as built, and every other drawing
is captioned as the design it is. Dr Timbo's screens are 25-35, 48-53
and 59-63 m under a 20 m grout, with the pump at 54 m.

The reports say what their inputs support. The geology paragraph was
chosen by the substring "western" in the district name and said
"Freetown Basic Complex" of a site the report's own maps placed on the
Bullom Group; it is now written from the USGS and BGS polygons under
the site, through the crosswalk the map legend uses, and the Western
Area text is chosen by region. The field-work section asserted a
reconnaissance dated the survey day, a geomorphological survey,
traverse selection, pegs and a profiling method for every survey; it
now prints the recorded reconnaissance date and notes when there are
any and says there are none when there are not, states the array and
the count of positioned soundings, says that no elevation model was
supplied, and draws the ground profile the recorded levels support.
Total coliforms were reported as a WHO health-guideline failure and
"faecal contamination" with E. coli at zero: WHO sets no health
guideline for them, so they are a national-limit failure that calls
for disinfection and a sanitary inspection, and the remark, the
verdict and the summary say so. The corrosivity paragraph stated the pH
was within the acceptability range beside a value of 5.9; it now states
the pH and which side of the range it is on. The table of contents
carries the headings themselves rather than "right-click and choose
Update Field", captions carry Word's Caption style, an empty table no
longer crashes a build, the Piper diagram's base labels no longer meet
as "HNO3+K" and the facies section says what the water is, a
provisional report qualifies its own executive summary, the national
standard is cited as unverified, every "(s)" is a noun that agrees with
its count, grid coordinates print as coordinates, the model table
writes "half-space" rather than "0/0", and the placeholder signatories
and phone number are out of the worked examples.

The regional maps show where things are at the scale they are drawn.
The scale caveat quoted an 80 km window on maps drawn at 52 km and
135 km; it now describes the window that was drawn. The same USGS
polygon was named for the site's district rather than its own, so the
Freetown Complex was "Paleozoic Igneous", the age the crosswalk itself
calls wrong, on a Kuntolo map; each polygon is now placed by its own
position. The bundled chiefdom layer truncates names to fifteen
characters and those went onto client maps; the full names are carried
beside them, printed, and accepted from an operator. Guinea and Liberia
were painted the same blue as the Atlantic; the land across the border
is now in the paper tone, told from the sea by the geology layer's own
polygons. Graticule ticks placed past the frame grew every map and
thirteen labels at a tenth of a degree collided; the ticks stay inside
the frame at three to six per axis. The location map highlights the
district the position resolves to, lights both halves of the Western
Area and the chiefdoms of Karene and Falaba, and keeps the site star
clear of the names; the geology tints are separated in greyscale; the
study-area map is drawn at the scale its points need, so Rokel's shows
both soundings 20.7 km apart on one sheet; a unit map over the coastal
plain says that the Precambrian polygon spans the Rokel River Group belt
the aquifer map shows as fracture flow; the Streamlit maps page draws
the maps the reports embed; the national legends sit in the Atlantic
corner and the scale bar's total carries its unit.

An audit of the three worked examples, reading every figure and every
report as a client or a ministry reviewer would, found real defects in
the maps, the borehole design, the VES interpretation, the pumping-test
recommendations and the report text. `ROADMAP.md` lists them by
consequence in the order they are being fixed, with the files, the
browser-engine mirrors and the tests each touches. The first step is
done here: the example folders held twenty-nine figures that no script
had written for months - maps keyed to a district centroid the boundary
layer had since moved, drawings under file names a builder had stopped
using - beside the current ones, with nothing in either name to say which
a committed report embeds. Every example now clears its output folders
before it runs, a map of an area with no GPS fix is named for the area
(`study_area_map_port_loko_district.png`) rather than for a centroid
that moves with every rebuild of the layer, and a test runs each example
into a temporary folder and holds the committed set of files to it.

Offline releases are now built rather than maintained by hand.
`web/build_offline.py` reads the app shell the way a browser does and
emits `docs/sw.js` with exactly the files the page loads; the release
identifier is a hash of those bytes, so a shell change cannot ship
without one. A release is all of its files or none of them: a precache
that cannot complete fails the install, leaves no cache behind and
leaves the device on the release it already had. An open tab finishes on
the release it started with, which is what the app already told the
user.

A handover report no longer claims work nobody recorded. The browser
engine asserted, of every project, that the borehole had been developed
and test pumped, that headworks had been built with an apron, drainage
channel and soakaway, and that a handpump had been installed and
commissioned - whether or not the project held a pumping test, a design,
or anything at all about a pump. Each bullet is now conditioned on the
record that evidences it, as the Python engine has always done.

The Dr Timbo example no longer invents a GPS position to get past the
readiness gate. Its sheets carry none, so its three reports now publish
with the provisional stamp and the position listed as outstanding, which
is what that data supports and a better demonstration of the gate than a
clean cover.

Chiefdom geometry that cannot place a borehole is withheld rather than
trusted. `Maforki` (Port Loko) carried a 21 km² wedge on the Guinea
border in Kono, 247 km from the rest of it, so a borehole sited there
was reported in Port Loko - on the completion report, in the programme
table, and in the coverage ranking that decides where to drill next.
`web/build_boundary_review.py` takes geometry like that out of the
lookup layer and writes it to `boundary_review.geojson` with the
measurements the decision rests on and the chiefdom it probably belongs
to. Nothing is reassigned: a shared boundary is evidence of origin, not
authority over ground. A point there now comes back unplaced, which is
the honest answer.

`examples/build_catalogue.py` indexes the worked examples into
`examples/CATALOGUE.md` and packs each case - inputs, reports, figures
and derived tables - into one zip. Every count comes back out of the
workbook by the reader the toolkit uses, and every verdict is read off
the report's own cover, so a report stamped provisional is listed as
provisional with the requirement it is missing.

Two browser checks now run in CI beside the existing ones.
`tests/webapp/offline.mjs` covers the edges a field device actually
falls off: a file the page loads that nobody precached, a deploy that
half arrived, an update swapped in under a tab mid-recompute, and real
work - loading a survey and recomputing it - with no network at all.
`tests/webapp/review.mjs` holds the documents to what the project holds
a record of: that a demonstration project cannot pass the gate for any
report kind, that the stamp and the outstanding requirement reach the
document the user downloads, that a health failure is still a readable
result while a reading nobody can grade is named, and that an interim
issue says who issued it and why without becoming a certification.

A report drawn from the bundled example data now says so on its own
cover. The samples are offered from a picker so that nobody needs a
borehole to see what the toolkit does, but the documents they produce
carry the same letterhead and signature block as real ones and leave as
`.docx` files that get forwarded and filed. `src/groundwater/data/sample_provenance.csv`
records what each bundled file actually holds - transcribed verbatim,
part illustrative reconstruction, or synthetic - and the certification
gate reads it. Two things fail it, and they are
not equally serious: a source whose readings were invented, which is
true of the file however it was opened, and a source picked from the
sample list, which is a fact about the session and so turns on the
picker's own marker. The Dr Timbo water quality workbook is the first
case - no sample was ever taken - so the completion, quality and
handover reports that example publishes now list it as outstanding. The
Rokel survey is the second: a verbatim transcription of a real 2015
survey, so the example that publishes it under the Rokel name is still
certifiable, while the same file pulled into somebody else's project is
not. The marker is saved with the project, so reopening one does not
launder it, and a role's marker clears when real data is dropped on that
role. `examples/build_catalogue.py` reads the difference straight off
the covers.

The handover works list is now worded identically by the two engines,
and `tests/webapp/parity.mjs` holds them there. Four of its seven
bullets differed, so one borehole got two different certificates: a
quantity surveyor reading the browser's got the screen run, one reading
Python's got the casing size, and neither got the sanitary seal. The
merged bullet carries all three. The drilling bullet also now waits for
a depth figure instead of certifying a borehole drilled to "n/a m" off a
sheet where nobody wrote one down.

The coverage ranking in the browser says how many water points it could
not place. A point inside no chiefdom - the Guinea and Liberia fringe
the search box overhangs, offshore points from bad coordinates, and the
geometry the boundary review now holds back - is left out of every
area's ratio, so the areas it belonged to rank worse than the data
supports. The Streamlit app has always said how many went; this page
ranked the country without them and said nothing.

Autosave tells the truth about what it is holding. A failed write no
longer deletes the copy that already succeeded - the whole state goes in
one `setItem`, which either replaces the old value or throws and leaves
it intact, so there was never a half-written mirror to clear up, and
what the removal actually did was delete this morning's drilling log the
first time a photograph filled the quota. The banner now distinguishes
the two failures, because they call for different urgency: a browser
that has stored something and stopped is losing the last few minutes, and
a browser that has never managed a write at all - a private window, or a
tablet whose storage was full before the app opened - is losing the whole
day, and must not be told a copy is waiting for it.

A release really is all of its files or none of them now. The install
handler has always refused half a release, but that was worth little
while an ordinary page load could rewrite the release it was running:
the fetch handler revalidated in the background and put each answer
back into the *versioned* cache, so a deploy that was still uploading
became the app one file at a time, under the old release's identifier,
without any install ever succeeding. The release cache is now written
only by `install`. Anything in scope that the release does not carry
gets ordinary revalidation in a separate runtime cache, which is
swept with the release it belongs to. `tests/webapp/offline.mjs`
changes a file on the server, loads the page and requires the bytes on
disk to be unchanged; with the old behaviour restored that check sees
the shipped engine replaced by a 39-byte placeholder.

A project saved in the Streamlit app can now be opened in the browser
app. It never could: `serialize_project` always writes five container
keys, PyYAML renders an empty one as `{}` or `[]`, and the browser's
YAML reader refused flow syntax outright - so every Streamlit project
failed to parse, and the portfolio and asset-registry pickers reported
it only as a count of skipped files. Two places in the app and the
user guide said the opposite. The reader now accepts the two empty
collections and still refuses a non-empty flow collection, which it
genuinely cannot read. The smoke fixture that was supposed to guard
this was hand-written and carried none of the five keys, so it passed
against a file no save has ever produced; parity now round-trips the
real bytes of a real `serialize_project` call.

Reports no longer assert equipment and works nobody recorded. The
handover works list ended with an unconditional wellhead bullet, so a
project holding nothing but a site certified an apron and a drainage
channel - in the same function whose docstring says every bullet is
conditioned on the record that evidences it; there is no headworks
record in the toolkit for it to be conditioned on, so the bullet is
gone and `works_completed` remains the supervisor's way to assert it.
The browser's completion report printed "Handpump" as the pump type on
every borehole, from a field nothing in that app ever writes.

The browser's costing report prints the VAT lines again. Its cost
summary table was eight hand-inlined rows with no VAT branch at all,
while the app offers a VAT input and the engine computes the figures,
so a VAT-set estimate showed a contract price, then a contingency
computed on a VAT-inclusive budget, and no line saying where the
difference went. The table now comes from a shared
`costSummaryRows`, compared against Python's `summary_rows` with and
without VAT.

The Streamlit app now reports the inventory rows its reader could not
use. The `skipped` out-parameter added last release was wired only
into the browser, so the two apps disagreed about the same export. And
in the browser, the note that carries those discards sat behind a
"did we load any points?" guard, so it was suppressed in exactly the
case it exists for - a BOM'd export whose first column arrives as
`\ufefflat_deg` loses every coordinate, and the page said "no water
points near this site", the opposite of what the export says.

Stated assumptions are now compared across the two engines, and the
browser states the ones it was silently dropping. A bundled file whose
blank columns were filled in illustratively is recorded as an
assumption on the Python gate and was recorded nowhere on the
browser's; nothing compared the two, because parity checked a gate's
requirements and not its assumptions.

Several documented claims were not true and have been corrected:
`DEPLOY.md` listed two generated parts of `docs/` when there are three
(a deploy following it shipped a stale service worker) and counted six
`.docx` reports when there are ten; `README.md` said every one of the
ten documents opens on a map and that the gate stamps every report,
both of which exclude the laminated identification plate;
`docs/user_guide.md` described the browser app's persistence with the
Streamlit app's words and named a template file the toolkit does not
write; `docs/geolibre_integration.md` still counted seven reports; and
`THIRD_PARTY_NOTICES.md` did not record that chiefdom geometry is
withheld from the CC BY layer.

One test that claimed to catch a defect did not. `review.mjs`'s
"the same figure is the same colour whatever else is on the map"
compared two maps to each other over rank-identical fixtures, and
quantile breaks are rank-based - so the per-map scale it was written
to prevent satisfied every clause in it. It now pins each fill to the
colour the shared class table gives that value, over a third fixture
that is deliberately not rank-equivalent.

The mapping section now answers the question a report opens with. It
had three maps - a national administrative locator and the geological
and aquifer settings - and nothing between the country and the survey
point. There is now a study area map: the chiefdom boundaries around
the site at a scale where the distances can be read off the scale bar,
the survey points and any water points already found on it, and a
thumbnail of the country with the window boxed on it, so the figure
answers "where is this?" as well as "what is here?". Every report that
carries a map of the area carries this one first.

Three of the survey-scale maps the package has always had were
reachable from nothing. `site_location_map`, `iso_resistivity_map` and
`overburden_thickness_map` were called by the test suite and by no
application, report or example; the Maps page drew the three national
context maps and stopped. They are on the Maps page now, alongside the
subsurface maps built from the same interpretations: depth to bedrock,
interpreted aquifer thickness, the bedrock surface as a landform,
aquifer protective capacity in its standard longitudinal-conductance
classes, and transverse resistance. The iso-resistivity map offers only
the electrode spacings every sounding actually measured, because a map
at a spacing two of five curves skipped is interpolated from three
points and captioned as five.

Two sections along the traverse, where there was one. The geoelectric
section existed but had to be told where the soundings were, and its
default was to space them 100 m apart in the order they were handed
over - so a survey that walked 40 m between two pegs and 300 m to the
next came out evenly spaced, which reads as a uniformly thickening
weathered zone when what the ground did was thicken over 40 m and hold
for 300. It is now drawn at the surveyed chainages, from the soundings'
own positions projected onto the best-fit line through them. Beside it
is an apparent-resistivity pseudo-section, which involves no inversion
at all: each point is a reading at the station and electrode spacing it
was taken with, so it is still right if the inversion is wrong. Its
vertical axis is AB/2 and is labelled AB/2, not a depth - current does
spread deeper as the electrodes spread, but the pseudo-depth
conversions vary with the very layering the section is drawn to reveal,
and calling a measurement geometry a depth is how a pseudo-section
starts being read as a cross-section. Where the soundings sit too far
off the line to read as one section, both figures say so on their own
face.

There are topographic maps, and there is no elevation model. None is
bundled and none is downloaded: the map is drawn from a file the
operator supplies and names that file's source on the figure. An SRTM
`.hgt` tile, an ESRI ASCII `.asc` grid and plain
longitude/latitude/elevation columns are all read with numpy alone,
because a drilling supervisor with a laptop in Makeni can obtain any of
them and cannot install GDAL. A void in any of them stays a void rather
than becoming a hollow in the ground, and a scatter of heights is
refused rather than gridded - an elevation surface interpolated from
the spot heights a survey happens to record is a guess about the ground
between the pegs, not a measurement of the landscape. What a survey can
always draw is the ground profile along its own traverse, and that is
drawn separately: measured at the pegs, straight between them, and
saying which stations recorded no elevation.

A caption stopped claiming what its figure did not show. The
geophysical survey report captioned its site figure "Topographic map of
the project area" over a scatter of survey pegs with no elevation,
contour or relief anywhere in it. It is captioned as the survey point
location map it is, and there is a slot beside it for a real
topographic map when the operator supplies an elevation model. The
figure it mis-captioned was, in the event, never drawn at all: nothing
in the toolkit ever set the field it came from.

Two defects in the existing maps, both visible in every report that
carries one. A local geological or aquifer map legended every unit in
the national dataset rather than the units on the map, so a 10 km
window over the Freetown peninsula listed Ordovician, Silurian and
Precambrian formations beside the two under the site, with nothing to
say which two. The legend is now built from what the window actually
holds, tested against the three ways a polygon can reach into a window
- a vertex inside it, the window inside the polygon, or an edge
slicing through. And a two-source attribution line ran a third of a
figure-width past the left spine, which the tight bounding box then
grew the canvas to hold: every local geology and aquifer map has been
sitting in the right-hand half of its own figure with an empty gutter
beside it. The credit wraps to the frame, and the scale bar is lifted
clear of however many lines it wraps to.

A cross-section stopped implying a traverse nobody walked. The
geoelectric section divided the profile equally between its columns, so
two Rokel soundings 20.7 km apart came out as two columns 8 km wide -
each claiming to have measured 8 km of ground. A column is now as wide
as the sounding's own lateral reach, and where the gap between adjacent
soundings dwarfs that reach the figure says in red how many times over:
at Rokel the widest gap is 259 times the 80 m the soundings reached, so
the dashed correlations across it join two measurements with nothing
between them, and the figure now says to read them as a proposal rather
than as a traced horizon.

Both zoomable unit maps now say what scale they were drawn at. The USGS
and BGS layers are published at 1:5,000,000, where a 0.5 mm drafting
line is 2.5 km on the ground, and the toolkit's own default window is
40 km - so a reader is being shown a contact placed to a sixteenth of
the frame it is drawn in. Below 120 km across, the figure says so, and
for the aquifer map it says it in the publisher's words: the BGS Africa
Groundwater Atlas user guide states its country maps are "not suitable
for providing detailed information on geology and hydrogeology at a
sub-national (e.g. catchment) scale".

The maps were redrawn. They had no sea on them, which on the Freetown
peninsula - where most of what this toolkit maps actually is - meant half
of every window was blank paper and the coastline read as the edge of the
data rather than the edge of the land. The mask that stops a geological
unit running on across the Atlantic was painted the page colour, so it
painted out anything drawn underneath it. There is now sea under every
map, a hairline graticule labelled in degrees and minutes instead of a
grey grid heavier than the data, an alternating-segment scale bar with a
zero and divisions somebody can measure against, a compass needle instead
of a line with a letter over it, halos behind every place name, and line
weights that rank coastline over district over chiefdom over geological
contact. All of it lives in one module, `mapping/cartography.py`, because
it had been open-coded in three files with three sets of numbers and the
same site came out looking like three different maps depending on which
function drew it.

The boundaries are the real ones now. They were the geoBoundaries
_simplified_ release put through Douglas-Peucker again at 0.003 degrees
and rounded to four decimal places - about 330 m of simplification on top
of somebody else's, quantised to 11 m steps. On a 25 km study-area map
that is more than a percent of the frame per step, which is why every
coastline looked hand-traced. They are rebuilt from the full-resolution
releases at 45 m for the national outline and districts and 90 m for the
chiefdoms, which is finer than the eye can find at any window this toolkit
draws. This is a real cost and worth stating plainly: the offline app's
precache grows from 1,662 KB to 2,143 KB, on an app installed on phones in
places where that is somebody's data allowance. (The last 12 KB of that is
the lithology crosswalk, bundled so the browser's key can name the rock;
its comment block, which is most of the file, is stripped on the way in.)
It buys a coastline, an estuary and a river boundary that are where they
actually are.

What was NOT done, and deliberately: no curve smoothing at render time.
Running a spline through a simplified boundary produces a confident line
that no survey drew, and this toolkit does not draw confidence it does not
have. The jaggedness was an artefact of simplification, so the fix was
finer data, not a prettier curve over the same coarse data.

The geology stopped being wrong. The bundled layer is the USGS Geologic
Map of Africa at 1:5,000,000 and carries seven classes for the whole
country, which are ages rather than rocks - and one of the ages is
incorrect. The single polygon it calls "Paleozoic Igneous" is the Freetown
peninsula, where the rock is the Freetown Layered Complex: Jurassic
layered gabbro, norite and anorthosite, about 193 million years old. A
driller told "Paleozoic Igneous" has been handed a wrong age and no rock
at all, and the Western Area is exactly where this toolkit is used most.

`sl_lithology_usgs_crosswalk.csv` now says what each class is made of,
from the Geology of Sierra Leone map (Fileccia, Teatini, Walther and
Mastrocola 2017, Hydro Nova for SALWACO and the Ministry of Water
Resources, 1:600,000, 28 formations) - which this repository has committed
all along and the geophysical report already cited in its prose while the
figures beside it said "Precambrian". The key now reads "Freetown Layered
Complex (Jf)" and "Bullom Group (Q, Tb)", and each row carries what it
means for drilling: gabbro stores nothing and yields only from fractures;
the Bullom sands yield well and are the easiest ground in the country to
contaminate.

It annotates rather than reclassifies. The polygon is still the 1:5M one
and is no more accurate for being better named, every row records whether
it is quoted from the committed 2017 map or taken from the wider
literature, a class annotated for one region is not applied to another,
and where the two sources disagree on age the figure states both rather
than quietly correcting somebody else's dataset.

Two of the seven classes are deliberately left unnamed, and that is the
finding rather than an omission. "Ordovician" and "Silurian" have zero
vertices inside Sierra Leone - all 94 and 28 of them are in the Bove
Basin in Guinea, inside the bundled window only because the clip box
reaches 10.15 N. Naming them for a Sierra Leonean formation would put a
name on another country's ground. The 2017 sheet does map Ordovician
inside Sierra Leone; the USGS layer simply does not draw it, because at
1:5,000,000 it is swallowed by "Precambrian".

And "Precambrian", which covers most of the country, is not one rock.
Cross-tabbed against the bundled BGS hydrogeology on a 1.4 km national
grid, 87 per cent of it is basement aquifer and 12 per cent is
consolidated sedimentary with fracture flow - a belt from 7.6 to 9.7
degrees North through Port Loko, Kambia, Moyamba and Tonkolili, which is
the Rokel River Group. That is a different drilling target inside one
colour: fracture flow in indurated beds with shales acting as
aquicludes, rather than a weathered-zone aquifer. Its row says so, and
the BGS aquifer map beside it does separate the two.

The proportions quoted in that row and in this note come from the two
bundled layers and nothing else, so anyone with a checkout can rerun
them; `tests/test_study_area_maps.py` pins them. That matters because an
earlier pass at the crosswalk proposed qualifying the Holocene class as
"85 per cent Bullom Group, 15 per cent metasediment" on the strength of
a nearest-label sample of the 2017 map's PDF text layer. A Voronoi over
label positions is not an overlay of mapped contacts, and it drags a
band of genuinely Bullom ground onto the Magbele and Tapr labels that
sit along the inland edge of the coastal plain. Checked against the BGS
layer - independent, different scale, different publisher - the Holocene
class is 99.4 per cent unconsolidated intergranular aquifer, which is
the Bullom Group and nothing else. The qualification was wrong and was
not made; the header of the crosswalk records why, so nobody
reintroduces it from the same artefact.

The layer also has holes, and the maps now admit it. Two and a half per
cent of Sierra Leone's land area falls in no USGS polygon at all, every
point of it in a coastal district - Bonthe, Port Loko, Moyamba, the
Western Area, Kambia and Pujehun - because at 1:5,000,000 the coastal
units stop short of the shore. That ground used to be painted the same
colour as the ocean, so the Bullom shore and the Sherbro estuaries read
as sea on maps of the country whose coastal aquifer is its most
productive ground. It now carries its own tint and a key entry, "Not
mapped at this scale", on both engines - and the key only carries the
entry when unmapped ground is actually in the window.

Two more things the key used to get wrong. It listed "Ordovician" and
"Silurian", which are masked away when the map is drawn because they are
wholly across the Guinea border: entries for colours that are not on the
map, sending a reader hunting for them. Units that cover no ground inside
the country are now dropped before the key is built. And the national
geological map, which passes no district, refused the crosswalk and fell
back to the source's own wording - so the one polygon in the layer whose
age is demonstrably wrong was captioned "Paleozoic Igneous" on the map
most likely to be read by somebody who does not know better. With no
district there is no region to choose by, but where every row for a
class agrees on the formation there is only one answer to give, and the
lookup now gives it. A named district that has no row still gets
nothing: the Freetown gabbro is not under Kono.

The browser draws the same key. The crosswalk is bundled into
`gwt-data.js` and `gwt-charts.js` mirrors the lookup, its two refusals
and the wrong-age footnote, so the figure on screen and the figure in
the report name the same rock. It also paints sea and unmapped ground
apart, which it did not: the whole map frame was one tint, so a coverage
gap and the Atlantic were indistinguishable. `data_provenance.yaml` had
claimed the crosswalk was embedded in the browser bundle since it was
written; it was not, and now is.

Two defects the rebuild exposed. The boundary review tested whether it had
already withheld a piece of ground by comparing the encoded geometry byte
for byte, which holds only while the layer's vertices never move -
rebuilding at a finer tolerance moved every vertex, so the same Maforki
fragment came back as a second, separate withholding and the file would
have grown another duplicate on every rebuild. Identity is now the same
chiefdom, the same district and centres within five kilometres. And the
graticule labelled the tick just short of 13 degrees West as "12 deg 60'
W", on every map of the Western Area.

The Streamlit design page now designs against the pumping test. It asked
for a static water level with nothing in the box and passed no pump intake
at all, so the intake checks never ran on the design that page hands to the
drawing, the bill of quantities and the completion report: two pages of the
same app disagreed about the same borehole. It prefills the level from the
project's test, says where the figure came from, and passes the intake that
test recommends into the designer.

Every bundled table is now in the provenance record. Six were outside it,
two of them with no stated source at all, so nothing told a reader which
bundled numbers are somebody's published dataset and which are the
toolkit's own working assumptions. The costing and supervision tables are
recorded against the practice guides they were built from, the coverage
classes against the Sphere figures they quote, and the rest as authored
here - with the district boxes marked as a coarse plausibility check and
not a survey product, and the separation distances marked as having no
recorded source at all, which is the honest thing to say about them.
`THIRD_PARTY_NOTICES.md` says the same in prose, and a test now fails if a
bundled table is ever added outside the record.

The parity suite compares what it had only been collecting. Eight groups
were read out of the browser, written into the reference and then held to
nothing: the drilling log's site fields, the pumping test's duration and
recovery levels, the Depth Spine's levels, Piper percentages and quantity
basis, the portfolio statistics and the census statistics. A disagreement
in any of them passed every run, which is how a 12 m against 13 m
divergence once passed 528 of 528 checks. They are compared on the shape
the Python states: a field the browser adds of its own is not a divergence,
and a field Python states has to match.

The browser writes the same reports as the package. It had no figure
derived from the survey at all - no section, no pseudo-section, no
subsurface map, not even the study-area map the report opens on - so a
reader holding the two reports for one survey saw two different documents.
It now draws all of them, the drill-target suitability map with its four
caption states, and the ground surface along the traverse, each with the
caption the Python gives it, and it lists what it could not draw and why.
The refusals are the part that matters: no correlation across a gap too
wide for one horizon to span, no subsurface section where fewer than two
soundings carry a position, and the ground profile omitted in silence where
fewer than two carry an elevation, exactly as the package omits it.

Figures bound for a report are painted for paper. Every chart took its
colours from the live CSS tokens as it was built, and the app's default
theme is dark, so clients opening a report got maps and borehole drawings
rasterised white on black.

The parsers read a field sheet the way a driller fills one in. A non-detect
written with its limit - "ND (<0.05)" - was read as a measured
concentration, so the arsenic a laboratory reported as absent was graded
the worst reading on the sheet. A count nobody quantified - "TNTC",
"Present" - read as "not measured", so a sample with E. coli 0 and total
coliforms too numerous to count was graded Safe, and ">50" was read as
exactly 50, which passes a limit of 50. A longitude typed without its
western sign was taken at face value and the page then relabelled the zone,
moving the site 250 km to fit it inside the country. An interval written
with an en dash was dropped without a word. A water strike was read as the
last number after the last colon, so "8 m at 14:30" recorded a strike 30 m
down. A diameter read without its unit made "165 mm" a 165 inch hole - and
that diameter is what sizes the casing and decides whether a gravel pack
will fit. A Wenner sounding had no ingestion path and was inverted as a
Schlumberger one, wrong by tens of percent with nothing downstream to
notice.

The guideline table no longer carries values WHO does not set. Aluminium
had a health guideline of 0.9 mg/L, which WHO derives and declines to
adopt; hardness and turbidity had WHO acceptability values WHO does not
set; and the nitrogen-basis limits were the floor of their conversions, so
a sample complying as nitrate was failed as nitrogen. A national limit is
reported as provisional, with the WHO figure it was carried across from
named beside it.

The district consistency check reads the boundary polygons. It was judged
against hand-drawn boxes that overlap on half the country and miss a tenth
of it, while the polygons every other part of the toolkit uses sat in the
same package; the boxes are deleted. A seam between two independently
simplified chiefdom rings no longer swallows a point: one named tolerance
closes it, and beyond that the lookup answers nothing rather than placing
the withheld Maforki wedge confidently in Kono.

A hole in a map unit is cut out of it rather than painted over it. Every
interior ring became a filled polygon carrying its parent's code, and
thirteen of them were drawn on top of the unit they should have exposed:
the dolerite dykes in Kono, Koinadugu and Falaba, and the igneous aquifer
around Kamakwie, disappeared behind the ground meant to reveal them. Both
bundled layers are rebuilt with their holes: 34 in the geology and 10 in
the hydrogeology. An earlier note here said the rebuild had to wait for the
raw downloads, but the BGS source had been committed all along, and the
USGS mirror is reachable. The rebuild found that three Precambrian holes
clipped at the window's edge had been dropped, because only a hole's first
vertex was tested and it lay on the edge its outer ring shares. On the
national geology map the lake near 11°35′W, 7°35′N is now water rather
than an outline over granite.

The worked examples' reports are what the code writes today. Report text
changed after they were last regenerated, so the committed reports still
quoted WHO turbidity and hardness values WHO does not set, judged
districts by the deleted boxes and blamed handpumps for a corroded
submersible. Nothing caught it, because the examples test compared file
names; it now compares the text of every report as well.

#### The fixes, reviewed

With every roadmap item ticked, the commits that ticked them were reviewed
area by area, each finding reproduced in both engines and each fix written
against a test that failed on the code as it was. Sixty-nine were found.
The parity suite that holds the browser to the package grew from 623
checks to 1,298 on the way. The five things the fixes deliberately left
open are closed in the next section.

A pumping test no longer rests its yield on a result it refused. When every
fit was disqualified the fallback picked the best R squared over all of
them, so a recovery line meeting t/t' = 1 at 60 percent of its drawdown
could carry a yield of 0.99 m3/h; a fit whose own result is wrong is now
never adopted, and with nothing left the yield is pending and says why.
The yield range left out nothing either, so Dr Timbo's "0.39 m3/h (0.28 to
1.2)" took its top from that refused line; it is 0.22 to 0.71, and a range
now always contains the yield it qualifies. A level the sheet itself shows
cannot be right - below the pump, below the hole - makes the yield
indicative and no longer sets the pump intake, which had put Kuntolo's at
67 m from a reading below the bottom of a 70 m hole. An hourly block is
placed by its heading, so a four-hour test read every few minutes no longer
ends at 226 minutes and gets called short; a step test whose clock
restarts keeps its length; the step table keeps the sheet's step numbers.
Both apps now give the design the one intake the pumping report prints.

A drill-target map no longer passes its star to the runner-up when the
best point has no position, and a survey either side of 12 degrees W is
drawn in one UTM zone instead of on a 660 km map. The tie between the top
two points is decided once, on the project's own margin, and read by the
text, the map and the study-area overlay, so a report can no longer call
two points indistinguishable over a map that stars one; the summary,
conclusions, recommendations and preference table ("=1st") carry it too,
and "listed first by name only" is said only of equal scores. Minimum
aquifer thicknesses are labelled as minima rather than contoured, the
ground profile follows the section's rules (Rokel's straight slope across
20.7 km of unlevelled ground is refused), captions describe what was
drawn, and a refused map names what is actually missing. Nothing below a
sounding's depth of investigation is reported as resolved, and a drilling
depth cut back to it reads as a minimum; the sheets' own warnings, such as
overlap readings that disagree by a factor of two, reach Annex A; a Wenner
survey is described in its own terms.

A laboratory sheet is read as the laboratory wrote it. A filled
detection-limit column had turned "Present", "TNTC" and ">50" into "not
detected", so a sample with E. coli present was graded safe to drink;
bounds and non-detects written with a unit or a label (">50 mg/L", "ND (DL
0.05)", "Absent/100 mL") were read as measured numbers. Both are read as
what they are, bounds are graded through the same limit hierarchy as
measured values, and the combined nitrate and nitrite rule reads either
basis. A national-limit failure no longer claims the WHO health values are
met when something could not be graded, treatment advice follows the
parameter and the direction of the exceedance ("Sulphate" no longer gets
the low-pH advice), and the facies sentence no longer says sodium replaced
calcium in a water whose calcium and magnesium are two thirds of the
cations.

A design document says what the design is. The completion and handover
reports promised a gravel pack in a 19 mm annulus the design had left
empty and listed a generated casing string as completed work; they now
describe the fill the design places and call the construction designed
unless the log records it installed. Every fracture zone a description
names is read, in the usual wordings, so "fractures at 30-31 m and 33-34 m"
screens both; a pump intake inside a screen is no longer lifted above the
level the pumping test reached; a grout written "0-20" is 20 m; "Water
strike 1: 12 m" is a strike and a rest water level is not; the basis
describes only the screens that are built; an as-built record keeps its
screens as recorded. The Depth Spine draws the drawing's lithology bands.

The browser's geophysical report described every site as crystalline
basement, the Bullom sands included, because nothing gave it a geology
paragraph; it is now worked out from the map under the site, word for word
as the package writes it. Two report builds started together no longer put
dark-theme figures into a client document. The browser places and frames a
report's area as the package does, so Karene and Falaba get their maps and
captions carry full chiefdom names, and in both engines a sheet saying
"Western Area" or "Port Loko District" gets its map. A longitude typed in
degrees without its sign is read as west, with a note, instead of placing
the site in central Africa. The study-area tint and the GeoLibre export
keep the holes the rebuilt layers now carry.

#### What the review left open

A laboratory that names a pathogen is read as having named one.
"Salmonella: Present" had become an unknown determinand: not evaluable, so
it kept the sample from "suitable", but not a failure either, so the
verdict asked for the units and detection limits to be confirmed while the
laboratory had reported Salmonella in the water. The only thing that
could have told the code it was microbiological was its unit, and a
heterotrophic plate count in CFU/mL - which WHO does not treat as a health
parameter - would have failed on the same rule. Both engines now recognise
the faecal-oral pathogens by name: any count, "Present" or lower bound is a
health failure with its own treatment line (shock chlorination, a sanitary
inspection, re-sampling for the pathogen and for E. coli); none counted,
"Absent" or "<1" is the requirement met; a coarser detection limit cannot
show that the organism is absent. WHO sets no guideline value for a
pathogen, and the row says that rather than quoting one. A plate count
names no organism and stays an open question.

The short water-quality sentence in the completion and handover summaries
said the WHO values had "not been shown to be met", or that the results
were incomplete, and named nothing; it now says what is unresolved, as the
verdict in the quality section does.

A step test whose clock restarts at each step is recorded as lasting as
long as its steps together: the Kuntolo sheet read that way pumped for 158
minutes, and the test details row said 60. The overview and the step
drawdown figure put each step where it was pumped instead of stacking all
three on the first hour.

The labels on a drill-target map are placed apart. Each used to be written
to the right of its peg, so a dense survey printed its labels through each
other and through the neighbouring pegs; both engines now place the target
first and the rest by rank, each at the nearest place round its peg that
covers nothing, then further out on a leader line. When the full labels do
not all fit, the grade line, which the table carries for every point, gives
way everywhere but at the target, and the caption says the grade is
printed where the map has room. On the Rokel map this moves B (2)'s label
back inside the right-hand neatline, where the browser already had it.

The browser's readiness gate refuses a position outside Sierra Leone, as
the Python's does: the site page flagged such a position and the report
went out unstamped. A latitude and longitude typed into the site boxes is
recorded on the gate as degrees, where it read "-13 mE, 8 mN".

#### A note on the sixteen districts

The shipped district polygons are the pre-2017 fourteen, from
geoBoundaries; Karene and Falaba have no polygon of their own. A point
is still placed in one of the sixteen current districts, because the
lookup goes through the chiefdom polygons and the crosswalk, which is
more accurate than a dissolved district layer would be.

Deriving sixteen district polygons by dissolving the chiefdoms was
tried and does not work on this data, and the reason is worth recording
so it is not tried again: `web/build_geodata.py` simplifies each
chiefdom ring independently, so neighbouring chiefdoms no longer share
vertices and their common boundary does not cancel. Measured on the
committed layer, the boundary left after cancelling shared edges is
760 km for Bo against a true district perimeter of 470 km, and 772 km
for Kono against 374 km - roughly half of it internal seams. A correct
dissolve needs a real geometric union over unsimplified source geometry,
which means the raw geoBoundaries download this repository does not
carry.

Confirmed national standards, current supplier quotations, client report
formats, local calibration outcomes and authoritative boundary ownership
still require source material from the programme. Existing provisional
inputs retain their labels.
