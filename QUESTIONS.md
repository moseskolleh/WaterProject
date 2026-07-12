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
