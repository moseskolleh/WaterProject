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

12. **Two choices in the VES interpretation want a geophysicist's
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

13. **Four choices in the pumping test reader and analysis want a
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

14. **Three choices in the water quality reader and the borehole design
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
