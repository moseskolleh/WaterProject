# Example datasets and scripts

`build_sample_data.py` writes the sample datasets into `data/` in the
standard template formats. The three run scripts exercise the full
pipeline and write their outputs into `projects/`.

## Provenance: what is real and what is illustrative

The sample files are transcriptions of two real project documents,
with clearly marked filler where the originals lack data. Keep this in
mind before quoting numbers from the generated example reports.

**Rokel geophysical survey (`data/rokel/`)** - transcribed verbatim
from the survey report for Rokel, Freetown (Living Water
International, December 2015):

- both Schlumberger VES data tables, including the leading zeros and
  the duplicate AB/2 readings at MN segment changes;
- the IPI2Win layered models and their ERR values;
- the header blocks, including the original copy-over error on VES 2
  (District "Port Loko" with coordinates in the Western Area). The
  consistency checker is expected to flag it; do not "fix" the file.
- The field supervisor name is replaced with a placeholder.

**Kuntolo step test (`data/kuntolo/`)** - transcribed verbatim from
the WiNGiN step test field sheet (Kuntoloh, ACF, April 2017): three
hourly steps, the recovery block, the incremental drawdown column as
recorded, and no discharge values (genuinely missing on the sheet).
The sheet's internal anomalies are preserved on purpose: early water
levels above the stated static level, and levels beyond the stated
borehole depth. The parser flags both. The borehole reference
`KTL-01` is a placeholder; the sheet leaves it blank.

**Dr. Timbo completion data (`data/dr_timbo/`)** - mixed:

- drilling intervals, times, penetration rates, water strikes (12 m
  and 30 m), grouting depth, dates and the constant discharge test
  readings (including the recovery column) are transcribed from the
  WiNGiN completion report;
- the discharge 2.93 m3/h comes from the report's bucket measurement;
- the **lithology descriptions are illustrative reconstructions**
  guided by the borehole diagram annotations ("Light Yellow Clayey
  Laterites", "Light Colour Granite", fracture zone marks) - the
  original log table leaves the sample description column empty;
- the **water quality workbook is synthetic** (typical basement
  groundwater with a few deliberate exceedances to exercise the
  assessment: low pH, iron, manganese, total coliforms).

## Scripts

| Script | What it shows |
|---|---|
| `run_rokel_geophysics.py` | parse -> consistency checks -> inversion -> interpretation -> drilling preference -> full geophysical survey report |
| `run_kuntolo_step_test.py` | the pending-discharge workflow: curves and available drawdown now, transmissivity and yield after discharges are supplied |
| `run_dr_timbo_completion.py` | drilling log -> borehole design and drawing -> pumping test analysis -> water quality assessment -> completion, water quality and handover reports |
