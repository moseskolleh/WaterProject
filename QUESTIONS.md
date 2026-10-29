# Open items needing project input

The system runs end to end on the bundled sample data. These items
need real project inputs or decisions to finish calibrating it.

1. **Sample drilling logs and laboratory water quality results.** The
   Dr. Timbo drilling intervals and times are transcribed from the
   completion report, but the lithology descriptions are illustrative
   reconstructions and the water quality workbook is synthetic. Real
   examples will let the parsers and the design rules be verified
   against actual practice (see `examples/README.md` for exactly what
   is verbatim and what is filler).

2. **Native IPI2Win data files.** The importer currently reads the
   model tables (N, rho, h, z, ERR) transcribed into Excel/CSV, since
   the survey report only shows those tables. With native `.dat`/model
   files an exact-format reader can be added.

3. **Discharge rates for pumping tests where the sheet does not record
   them.** The Kuntolo step test parses and plots, but transmissivity,
   well efficiency and safe yield stay pending until the three step
   discharges are supplied (enter them in the template's discharge row,
   in the example script, or in the web interface).

4. **Logo and branding details for report headers.** The reports use a
   neutral house style (white background, one accent colour). Set the
   organisation name, contact block and logo path in `HouseStyle`
   (`config.py` or a project `config.yaml`) once branding is decided.

5. **Client-specific report formats.** The five templates follow the
   Rokel survey report and the WiNGiN completion report structures.
   Any client or ministry format that must be matched exactly can be
   added as a variant builder in `groundwater/reporting/`.

6. **Sierra Leone national standard values (added during the build).**
   The national column in `groundwater/data/who_guidelines.csv`
   currently mirrors WHO/regional practice values. Please confirm the
   figures against the current Sierra Leone Standards Bureau drinking
   water specification and edit the CSV where they differ.

7. **District placement rests on simplified chiefdom polygons (added
   during the build, revised since).** The consistency checker no
   longer uses bounding boxes. It places a point in a chiefdom from the
   bundled geoBoundaries chiefdom polygons
   (`groundwater/data/sl_chiefdoms_geoboundaries.geojson`) and reads the
   current district, Karene and Falaba included, off the crosswalk in
   `groundwater/data/sl_chiefdom_district.csv` - the same lookup the
   maps and the coverage ranking use. `sl_districts.csv` is still
   bundled, but only for the district and province names the apps
   offer; nothing checks a point against its boxes. Two limits remain.
   `web/build_geodata.py` simplifies each chiefdom ring on its own
   (Douglas-Peucker, 0.0008 degrees), so neighbours no longer share a
   border exactly; a point outside every ring but within 50 m of one is
   placed on that chiefdom, and a point further out is reported as
   unplaced rather than guessed. And the detached Maforki fragment,
   which lies against Mafindor in Kono, is withheld for review
   (`groundwater/data/boundary_review.geojson`), so a borehole on that
   ground cannot be placed. The seams are a build choice rather than a
   gap in the data: simplifying each shared border once, as a line both
   neighbours use, would close them from the same source. What input
   would improve it: the OCHA COD-AB boundaries from HDX, which carry
   the sixteen current districts in the geometry rather than through a
   crosswalk; the geoBoundaries release the bundled layer came from,
   which `data_provenance.yaml` records as unrecorded; and a gazetteer
   or Statistics Sierra Leone source that confirms where the Maforki
   fragment and the chiefdom-to-district crosswalk belong.

8. **Costing unit rates are indicative (added with the costing
   module).** The catalogue in
   `groundwater/data/borehole_cost_items.csv` follows the RWSN cost
   structure and lands near the RWSN worked example (about 130 USD per
   metre for a 50 m borehole), but the individual rates are
   placeholders. Replace them with current Sierra Leone quotations
   (drilling contractors, casing suppliers, laboratories) and confirm
   the default exchange rate (23 SLE per USD) and whether GST (15
   percent) applies to the contracts in question.

9. **Map data notes (updated when real datasets were bundled).** The
   maps now draw from real, freely licensed data: geology from the
   USGS Geologic Map of Africa (public domain, 1:5,000,000), aquifer
   type and productivity from the BGS Africa Groundwater Atlas
   country map (CC BY-SA 4.0, source shapefile committed under
   `WaterProjectFiles/SierraLeone_BGS_Hydrogeology/`), and boundaries
   from geoBoundaries (CC BY 4.0). Two known limits: (a) the
   geoBoundaries district set predates the 2017 creation of Karene
   and Falaba (14 districts; the maps say so) - the OCHA COD-AB
   dataset on HDX has the 16 district version if boundary accuracy
   there matters; (b) the USGS geology is continental scale - the
   detailed 28 formation Geology of Sierra Leone map (Ministry of
   Water Resources/SALWACO 2017, PDF in `WaterProjectFiles/`) is the
   reference for local formations, and if its GIS data can be
   obtained from SALGRID it can replace the bundled layer via
   `web/build_geodata.py`.

10. **Supervision checklists may need project tailoring (added with
   the supervision module).** The stages and items in
   `groundwater/data/supervision_checklists.csv` follow the RWSN/
   UNICEF supervision guidance and the WASH funders checklists. Items
   can be added, reworded or re-flagged as critical in the CSV to
   match the client's contract conditions; the minimum separation
   distances table mirrors regional practice (FGN/NWRI 2010) and
   should be checked against the Sierra Leone Ministry of Water
   Resources requirements.

11. **Three choices in the VES inversion want a geophysicist's
   confirmation (added with the VES audit).** None is a published
   standard; each is stated where it is made
   (`groundwater/ves/forward.py` and `groundwater/ves/inversion.py`)
   with what it was measured to do. (a) The quadrature stops where the
   tail it leaves is 1e-8 of the least resistivity in the model, which
   left at most 3.1e-8 over 2932 models at 10 to 150,000 ohm-m. (b) A
   fit is labelled converged when the Gauss-Newton step from where it
   stopped would lower its sum of squared log residuals by at most
   1e-6 of itself; the label errs towards "not converged" in an
   equivalence valley. (c) A sounding is fitted with at most half as
   many layers as it has spacings, so a model keeps one degree of
   freedom; keeping two would refuse three layers to soundings of six
   and seven spacings.

12. **The sanitary inspection form, the E. coli grades and the risk
   matrix (added with PLAN.md step 7.5).** The form in
   `groundwater/data/sanitary_inspection.csv` is WHO's ten-question form
   for a tubewell with a handpump (Guidelines for Drinking-water Quality,
   2nd edition, Volume 3, 1997). Nobody working on the toolkit had a copy
   of the volume, so the wording was written from the form as field
   manuals commonly reproduce it. Four things need someone with the
   documents: (a) check the questions against the volume, against WHO's
   newer sanitary inspection packages for small water supplies, which
   revised the forms, and against any form the Ministry of Water
   Resources or the district councils use, and say which one Sierra Leone
   programmes should fill in; (b) confirm the score bands (0 to 2 low, 3
   to 5 intermediate, 6 to 8 high, 9 and 10 very high) and the grades of
   an E. coli count per 100 mL (A none, B 1 to 10, C 11 to 100, D 101 to
   1000, E over 1000) in `sanitary_risk.yaml`; (c) check the cells of the
   risk-to-health matrix in the same file against WHO's figure. They are a
   choice made here, each the worse of the two sides' own risk words, and
   the toolkit never states "no risk"; correct a cell and both apps
   follow; (d) say whether forms for other sources (a protected spring, a
   hand-dug well, a piped scheme) are wanted, since only the tubewell form
   is bundled.

13. **The rising main material and its inspection intervals (added with
   PLAN.md step 7.2).** Where the water is aggressive (by the corrosivity
   classification, or a pH below 6.5) the design specifies a stainless
   steel rising main in place of the galvanised iron one the handpump line
   of the cost catalogue includes, and inspects it every 6 months rather
   than every 12. All four values are settings in
   `groundwater/data/defaults.json` (`design.rising_main_material`,
   `aggressive_rising_main_material`, `rising_main_inspection_months` and
   `aggressive_rising_main_inspection_months`), and each is a choice made
   here, not a standard. Four things need the owner or someone with field
   records: (a) confirm the two intervals, or give the ones the programme's
   mechanics work to; (b) say whether a borehole whose water has not been
   analysed should be inspected at the shorter interval, as it is now,
   until a sample says otherwise; (c) say whether stainless steel (which
   replaces the India Mark II's steel main and rods like for like) or uPVC
   (for a pump made to take a uPVC main) should be the material the design
   specifies and prices, since the catalogue prices only stainless steel and
   a uPVC choice is flagged unpriced; (d) replace the placeholder rate of
   row RSM1 in `groundwater/data/borehole_cost_items.csv` (USD 20 a metre,
   extra over the handpump line, with no quotation behind it, as item 8
   says of the other rates) with a current quotation, and add a uPVC row if
   uPVC is wanted. The Ryznar classes and the aggressive-index cut the
   classification uses are not cited in `references.yaml`, and the -0.5
   margin on the Langelier index has no source in the toolkit; a reference
   for each, or a corrected value, would close that too.

14. **Two choices in the VES interpretation want a geophysicist's
   confirmation (added with the VES reading audit).** Both are stated
   in `groundwater/ves/interpret.py`. (a) A layer at or over the fresh
   basement edge is taken as basement only where no layer below it in
   the fitted model is conductive ground, which the rules read as any
   layer under both the 800 ohm-m top of the water-bearing window and
   the edge: water-bearing ground and clay-rich saprolite alike. Over
   such ground it is read as a resistive cover (a duricrust or a dry
   layer). The fitted model is believed for this below the depth of
   investigation too, so a conductive layer the model puts deeper than
   the sounding sees still makes the layer above it a cover. (b) A water
   zone whose two rounded ends meet (exactly 1 m on two half metres,
   such as 3.5 to 4.5 m) ends 1 m below its rounded top, "4 m to 5 m",
   rather than being widened at both ends.

15. **Identifiers minted with the old check character (added when the
   check character was corrected to ISO 7064 MOD 37,36).** Until this
   change the asset identifier's last character was worked out with the
   running sum reduced modulo 37 instead of 36, so it did not follow the
   standard and let about one single mistyped character in 680 through.
   New identifiers are minted with the standard's character. An
   identifier minted before is still read as itself, in both apps and
   from saved project files, and is never renamed or refused, because
   plates carrying it may already be fixed to headworks and a history is
   filed under it; looking it up says it carries the older character
   and what the standard's would be. Two costs follow. While both are
   accepted, about one single mistyped character in 36 of any identifier
   matches the older character and is accepted with that note instead
   of refused. And a project with no saved asset record mints its
   identifier afresh, now with the standard's character, so a plate
   printed from it before this change carries a different last
   character from what the apps show (the district and position code are
   the same). PLAN.md step 7.1's SMS reports have nobody to read the
   note, so the plan holds a report naming an identifier that checks only
   against the older character for a person to confirm. Decide: whether
   any plates were made with the old character; if none were, whether to
   stop accepting it; if some were, whether to re-mark them (a new plate
   carries the same position code and a new last character, and the
   history would need to move to it) and when to stop accepting the old
   character.

16. **Choices made in the drilling log reader, the supervision record and
   the registry (added with the same fixes).** Each is stated where it is
   applied and wants confirming: a depth with no unit of its own is read
   in its column header's unit, else in feet when every unit the sheet
   names for a depth or a penetration rate is feet, and refused when the
   sheet names both (so a metric log with one strike note in feet, or a
   rate column in minutes per foot, has its unlabelled total depth
   refused); depths converted from feet are kept to the centimetre; a
   strike refused as deeper than the hole keeps the drilling log from
   being called complete but is not a reading without a unit; a
   supervision record is held back while any critical item has no
   answer, in every stage, so a record issued at the end of one stage is
   provisional until the last is answered (whether a stage's record
   should be judged on its own stage alone is the owner's call); on one
   day a borehole's records are read commissioned, visits, failure,
   repair or return to service, then decommissioned; and a decommissioned
   borehole returns to service only through a new commissioning record,
   not through a repair or a "returned to service" logged after it.

17. **Choices made in the desk study, the survey plan, the water point
   reader and the planning view (added with the fixes to them).** Each
   is stated where it is applied and wants confirming: an earlier
   project whose easting and northing hold a longitude and a latitude is
   no position in the portfolio and the desk study, which names it and
   asks for it to be converted, rather than being placed by reading the
   pair as degrees (neither app reads a position from such a pair on the
   project's own pages); a survey plan whose water points were looked up
   over less than the service radius and the largest separation distance
   from a water point (550 m) says so and asks for another lookup, rather
   than fetching more points itself; a fractional install year is read
   as its whole part (2009.6 as 2009) and 0 or less as unrecorded; and a
   survey dated after the year planned for is left out of the age and the
   recent count for that year, rather than the plan year being refused
   when it is earlier than the inventory's survey dates.

18. **The service rounds' intervals, their order and the round sheet's
   boxes (added with PLAN.md step 7.3).** The asset registry schedules a
   sanitary inspection every 6 months and a water quality sample every 12
   (`service.sanitary_inspection_months` and `service.water_sample_months`
   in `groundwater/data/defaults.json`), and a routine inspection of the
   pump and rising main at the interval item 13 sets for the rising main,
   or at its shorter interval where a record carries none; a visit is
   overdue 30 days after it falls due (`service.grace_days`). Each is a
   choice made here, not a standard: the 6 and 12 months were the
   registry's defaults before this step, and the 30 days its grace. Four
   things need the programme: (a) confirm the intervals and the grace, or
   give the ones its district surveillance plan sets; (b) say whether a
   repair that pulled the pump and the rising main should count as a
   routine inspection, as no repair does now; (c) say whether the order of
   a round (a nearest-neighbour walk in straight lines from the stop due
   the longest, ties to the lower identifier) is good enough, or whether
   the mechanics' own route, or the roads, should set it; (d) confirm the
   boxes the round sheet prints for each visit (`readings_routine`,
   `readings_sample` and `readings_visit` in
   `groundwater/data/text/rounds.yaml`), which are this sheet's choice and
   follow no published form.

19. **Choices made in the sheet extraction, the Depth Spine and the
   traverse (added with the fixes to them).** Each is stated where it is
   applied and wants confirming: a cell under a numeric heading passes
   the review only when it is one number with, at most, one of the units
   m, cm, mm, min, s, h, hr, %, ohm, ohm-m, m3/h, l/s or m/min after it,
   so "<0.01" and "45 ft" are held back for a person to confirm; a line of
   one phrase is never part of a table, which keeps a caption and a note
   out but would also split a table at a reading with only one cell
   filled, or at a wrapped heading's second line; the filled VES template
   carries a sheet's resistances, MN/2 and K under headings the VES reader
   reads, rather than the extraction working out the apparent resistivity
   itself, and a Wenner sheet is not put into the template (which is the
   Schlumberger sheet); on the guideline chart a value below a range is
   drawn at the bottom of the range over the value (pH 5.9 at 1.10 times
   its limit), which is one way of putting it past the line, and a value
   of zero or less under a range has no place on the chart; a traverse
   within a degree of north-south runs northwards, and its bearing is
   printed as 0 rather than 360 just west of north; and the two apps'
   Costing pages start at different mobilisation distances (100 km in the
   Streamlit app, 0 km in the browser), which the Depth Spine's price now
   follows in each - whether they should start at the same distance is
   the owner's call.

20. **How the registry is read as a time to the first failure (added with
   PLAN.md step 7.4).** Both apps' Asset registry pages estimate how long
   boreholes keep working from their records by Kaplan and Meier's
   method. The method and its band are published (the works are in
   `groundwater/data/text/references.yaml`), but how the registry's records
   are read into it is a choice made here, and so are two settings. Five
   things need the programme or someone who keeps the records: (a) say
   whether a repair or a return to service with no failure recorded before
   it should count as the first failure, on its own date, as it does now,
   or whether some repairs are preventive and should not; (b) say whether a
   sanitary inspection, a routine inspection and a water sample should
   each count as a report that the borehole was working, as they do now,
   on the reasoning that a visit that found it broken would have recorded
   the failure; (c) say whether a borehole decommissioned without a failure
   recorded should be censored on that day, as it is now, or counted as a
   failure; (d) confirm the minimum of five boreholes followed before a
   group is judged (`survival.min_at_risk` in
   `groundwater/data/defaults.json`), the same number the ledger's hit
   rates use and the plan sets for the contractor scorecards; (e) confirm
   the times the table of numbers at risk states (`survival.at_risk_years`:
   0, 1, 2, 3, 5 and 10 years). The water chemistry grouping reads the
   corrosivity each record carries from its design's rising main, so a
   borehole whose project was saved before step 7.3 counts as "not known"
   until its project is opened and saved again with its water sample.

21. **Pooling calibration sets between organisations (added with PLAN.md
   step 5.5).** Each of these is a choice made here, stated where it is
   made (`groundwater/calibration_sets.py`), and wants the owner's
   confirmation. (a) A set is issued under CC BY 4.0
   (`ledger.set_licence`), and only sets issued under that same licence
   are pooled, since the toolkit cannot read what another allows; say
   whether the programme's partners want another licence, or a list of
   licences that may be pooled together. (b) A pooled edge is the mean of
   the sets' fitted edges, weighted by the boreholes behind each, taken on
   a logarithmic scale; it is not an edge fitted to the pooled layers,
   which the set files do not carry, and it says nothing of the layers it
   misreads. Carrying each unit's layer resistivities in the file would
   let a pooled edge be fitted as one set's is, at the cost of a larger
   file. (c) Each set's evidence-adjusted count is the one its own fit
   expected, and the pooled count is their sum, not a fit to all the
   boreholes together. (d) The suitability weights are not pooled. (e)
   Two sets that name the same organisation are pooled with a warning
   rather than refused; an organisation may run two programmes with
   separate ledgers, but one that pools two of its own sets fitted at
   different times counts its earlier boreholes twice. (f) A set saved
   before step 5.5 declares no licence and is refused for pooling; it can
   still be put in force.

22. **Four choices in the pumping test reader and analysis want a
   hydrogeologist's confirmation (added with the pumping test audit).**
   None is a standard; each is stated where it is made
   (`groundwater/units.py`, `groundwater/ingestion/pumping.py` and
   `groundwater/hydraulics/analysis.py`). (a) The pumped level is called
   stabilised, and a recharge boundary or leakage indicated, where its
   fitted line moves by less than 0.01 m over the last half log cycle and
   its slope there is under half the slope over the log cycle before
   (`stabilised_span_log10` and `stabilised_slope_ratio`); a Cooper-Jacob
   window that takes in such a tail is not adopted. (b) A time written as
   two numbers with a colon, "5:30", is hours and minutes, as Excel reads
   it typed into a cell, unless the column header names minutes and
   seconds. (c) An earliest pumping reading written as a clock past the
   first hour is taken for a time of day, and the sheet is refused. (d)
   A recovery whose first time comes at or after the minute the pump
   stopped is taken to be on the test's clock and moved back to the stop,
   unless its header or heading says "stop", "shut" or "off".

23. **Reports from the plate and by SMS (added with PLAN.md step 7.1).**
   A plate printed with a report address links to the browser app's
   report page, and both apps import reports sent by SMS. Six things need
   the programme: (a) give the address the browser app is served from
   (`service.report_url` in `groundwater/data/defaults.json`, blank until
   it is set; it must be https, as a browser keeps an app for use with no
   network only from a secure address), and say whether the plate should
   also print an SMS number and the message's form, which it does not now
   because no number is known here; (b) confirm the SMS words (WORKING,
   BROKEN, SLOW, and TASTE, COLOUR, COLOR or BAD for bad taste or colour,
   in `groundwater/data/text/fault_reports.yaml`) and give the words in
   Krio and the other languages people will text in, which are not
   guessed here (step 9.2); (c) say whether a report from somebody at the
   pump that it is working should make the borehole "Working", as it does
   now, in the way a report that it is broken makes it "Not working", or
   whether only a mechanic's visit should; (d) say whether a report that
   it is slow, or that the water tastes or looks wrong, should make a
   visit or a water sample due at once, as neither does now; (e) confirm
   that a report by SMS whose identifier the registry reads only with a
   note is held until a person confirms it, and say whether a report from
   a known sender (the area mechanic's number) should be taken without
   one; (f) confirm that the reports waiting on a phone belong to that
   browser rather than to a project file, so that saving a project does
   not keep them and *Reset everything* deletes them.

24. **Three choices in the water quality reader and the borehole design
   want confirmation (added with the water quality, units and design
   audit).** None is a standard; each is stated where it is made
   (`groundwater/ingestion/waterquality.py`, `groundwater/quality/assess.py`
   and `groundwater/design/designer.py`). (a) A unit in the result
   column's header ("Result (ug/L)") is the unit of every row whose own
   unit cell is blank, and a row that unit cannot measure, such as E. coli
   under "Result (mg/L)", is refused rather than read in its guideline's
   unit; a laboratory chemist may prefer the header to bind only the rows
   it can measure. (b) "Present" or "TNTC" in a unit that cannot be read
   is graded as a count above zero, while a number in such a unit is still
   refused: zero is zero on every count scale, but 12 of an unknown unit
   cannot be put against a limit that is not zero. (c) The top screen the
   design places is kept the gravel pack's height
   (`gravel_pack_above_top_screen_m`) below the foot of the seal, so the
   pack is never shortened to fit a screen; the alternative, a screen at
   the seal's foot with a shorter pack, is what the design did before and
   what a screen set by hand still gets, with a warning. A hydrogeologist
   should confirm which a Sierra Leone contract wants.

25. **Contractor scorecards (added with PLAN.md step 6.3).** Each of these
   is a choice made here, stated where it is made
   (`groundwater/scorecards.py`, `groundwater/config.py`) and in the
   report, and wants the owner's confirmation. (a) A contractor is
   ranked, and its dry holes judged against the forecast, only on at least
   five boreholes forecast before drilling whose outcome is known
   (`ledger.scorecard_min_boreholes`), the plan's own floor. With five
   boreholes each forecast at a 70 percent chance, anything from none of
   them dry to three is within the range, so five allows a ranking rather
   than settling one. (b) The ranking measure is the dry holes found less
   the number the forecasts expected, for each forecast borehole. It sets
   a contractor against the ground it was sent to, as the survey forecast
   it, which a plain dry-hole rate does not; it also charges the
   contractor with the survey's errors. Say whether another measure, or
   none, is wanted. (c) The range is a binomial's at the forecasts' mean
   chance, as the calibration report judges its band. The count of dry
   holes on forecasts of different chances is a Poisson binomial, whose
   variance is smaller, and its range could be worked out exactly instead.
   (d) The acceptance checks counted are the supervision checklist's items
   in the stages from mobilisation to demobilisation
   (`ledger.scorecard_stages`): procurement, the pre-contract inspection
   and siting come before the contract is let or are the client's, and
   the handover and the monitoring after it are not the drilling
   contractor's alone. Say whether the programme's contracts put other
   stages on the contractor. (e) A log's completion date written in
   figures alone is not read, even where only one reading is possible,
   so that the dates read are not only those late in their month.

26. **What a document's manifest lists, and how it is marked (added with
   PLAN.md step 8.1).** Every document either app writes carries a
   manifest, a code in its footers and, under a cover, a QR symbol of the
   code. Each of these is a choice made here, not a standard, and wants the
   programme's confirmation: (a) the code is the first 40 bits of a
   SHA-256 in eight Crockford base-32 characters and an ISO 7064 MOD 37,36
   check character, as the asset identifier has; 40 bits names one issue
   among the few a programme makes, and the full hash behind it is what is
   checked, but two different documents can share a code once in about a
   million million; (b) the QR symbol is at error-correction level H and
   2.6 cm across, at the foot of the cover, and the plate carries none, so
   that the one symbol on the headworks is the borehole's; (c) a document
   about the borehole lists as its evidence every sheet the project holds
   (not only the ones that report reads) and the photographs it embeds, a
   calibration report the project files pooled, a round sheet those of the
   register, and the field kit and the desk study none; a photograph is
   listed by the hash its provenance record took of the file as it
   arrived, not of the copy the project keeps; (d) the day a document is
   issued is the day it is built, from the device's clock, and a worked
   example built by a script gives none; (e) a copy is checked against
   the issue records of the project files given, and until documents are
   signed (step 8.2) a copy rewritten throughout is caught by nothing
   else. Say whether a document should also be issued on a day the user
   names, whether its evidence should be narrowed to the sheets it reads,
   and where the programme keeps the issue records it checks against.

27. **What an evidence bundle carries, and what counts as confirming it
   (added with PLAN.md step 8.3).** The Handover page of either app, and
   `groundwater bundle`, put one borehole's evidence into one .zip. Each of
   these is a choice made here, not a standard, and wants the programme's
   confirmation: (a) `raw/` holds the sheets the project holds as they
   were uploaded, and not the photographs, because the apps keep a smaller
   copy of each rather than the file as it arrived (the documents list
   each photograph by the hash of the file as it arrived, and the check
   names them as evidence the bundle does not carry); (b) `reports/` holds
   the documents the project issued in the session, the latest under each
   file name, and those the user adds, and leaves out the calibration
   report and the round sheets unless added, since they are about many
   boreholes; `figures/` holds what the documents embed, taken out of
   them; neither app writes `tables/` yet; (c) the documents taken
   together are as ready as the least ready of those that had a
   certification gate, so one provisional report makes the bundle
   provisional; (d) a file counts as confirmed from outside the bundle
   when an issue record given holds a document's hash, when a confirmed
   document lists a file's SHA-256 (a sheet as evidence, a figure as a
   part), or when it is the README or a folder's note exactly as the
   toolkit writes it, and a bundle is "verified" only when every file is
   confirmed, so a bundle with a processed table in it never is; (e) the
   bundle's own hash is printed but kept nowhere, so a check confirms its
   contents, not that the project made this bundle; (f) every entry is
   stored, not compressed, and dated 1980-01-01, so that both engines
   write the same bytes; a file's name keeps the last part of its path,
   with what a folder cannot hold made an underscore, and a second file
   under a name already taken is numbered, as `sheet (2).xlsx`. Say
   whether the photographs as the project keeps them, the calibration
   set's own file or the project file should go in, whether a processed
   table should be allowed to rest on the bundle's manifest alone, and
   where the programme keeps a bundle's hash.

28. **Two choices in the costing and the siting score want confirmation
   (added with the costing, siting and decisions audit).** Each is stated
   where it is made (`groundwater/costing/model.py` and
   `groundwater/siting/suitability.py`). (a) The no water, no pay price
   of a successful borehole carries each expected failure as a dry
   attempt: the siting, set-up and drilling lines, marked up as the
   borehole is, without the journey from the base. That is how the
   programme estimate, the cost distribution and the value of one more
   measurement already count a dry hole. RWSN's pricing guide (Costing
   and Pricing, Publication 2014-12, in `WaterProjectFiles/`) tells a
   driller paid only for successful wells to "increase the price of each
   successful well to cover your costs". It gives no formula. What a
   failure costs depends on what has been done to the hole by the time it
   is judged, and the same guide warns that "when mud drilling in
   sediments you will only know if you have been successful once you have
   installed your casing and screens". A contract that judges success
   after the test, or a hole mud-drilled in the coastal sediments, puts
   more into each failure. The price of a failure is a parameter
   (`failed_attempt_usd`); neither app asks for it. Passing the borehole's
   own price reproduces the earlier figure, the price over the success
   rate, which priced every failure as a completed and equipped borehole.
   (b) Two points are tied when the gap between their weighted scores,
   taken to the tenth of a point the reports print it to, is under the
   margin. So a real gap of 2.96 is not a tie on a 3-point margin, where
   before it was. The alternative, printing the gap to more places, would
   keep it a tie and say "2.96".
