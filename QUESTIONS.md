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

7. **District extents are approximate (added during the build).** The
   consistency checker uses approximate bounding boxes
   (`groundwater/data/sl_districts.csv`) good enough to catch gross
   copy-over errors. For boundary-accurate checks, supply district
   polygons (GADM/HDX GeoJSON) and the checker can use them directly.
   An upgrade to the 16-district OCHA COD-AB boundaries was attempted
   (July 2026) but no reachable source carries them: HDX and the ITOS
   geoservices are blocked from the development environment and every
   geoBoundaries variant (gbOpen, gbHumanitarian, gbAuthoritative)
   still ships the pre-2017 14 districts. When the OCHA file
   (`sle_admbnda_adm2` from data.humdata.org/dataset/cod-ab-sle) can
   be downloaded, feed it through `web/build_geodata.py` to replace
   `sl_admin_geoboundaries.geojson` and refresh the bounding boxes.

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
