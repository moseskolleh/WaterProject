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

11. **Identifiers minted with the old check character (added when the
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

12. **Choices made in the drilling log reader, the supervision record and
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

13. **Choices made in the desk study, the survey plan, the water point
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
