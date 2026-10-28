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

11. **The sanitary inspection form, the E. coli grades and the risk
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

12. **The rising main material and its inspection intervals (added with
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

13. **The service rounds' intervals, their order and the round sheet's
   boxes (added with PLAN.md step 7.3).** The asset registry schedules a
   sanitary inspection every 6 months and a water quality sample every 12
   (`service.sanitary_inspection_months` and `service.water_sample_months`
   in `groundwater/data/defaults.json`), and a routine inspection of the
   pump and rising main at the interval item 12 sets for the rising main,
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
