# Third-party notices

The toolkit's own source code is MIT licensed (see `LICENSE`). The datasets
and documents distributed with it are not: they keep their own terms, and one
of them is copyleft. This file lists each one, what it is used for, and what
its licence requires.

Where a licence could not be evidenced from the material in this repository,
the entry says **unverified — needs confirmation** rather than assuming a
permissive one. Those entries are work to do, not statements of fact.

The machine-readable version of this table is
[`data_provenance.yaml`](data_provenance.yaml); it carries a SHA-256 for each
committed file so a silent substitution is detectable.

## Bundled data

### BGS Africa Groundwater Atlas — Sierra Leone hydrogeology · **CC BY-SA 4.0**

| | |
|---|---|
| **Files** | `WaterProjectFiles/SierraLeone_BGS_Hydrogeology/SierraLeone_HG.{shp,shx,dbf,prj,cpg}`; derived: `src/groundwater/data/sl_hydrogeology_bgs.geojson`; embedded in `docs/js/gwt-data.js` and `docs/wasm/index.html` |
| **Source** | Africa Groundwater Atlas country hydrogeology maps, v1.2 user guide; Ó Dochartaigh, B. 2021, BGS Open Report OR/21/063 |
| **Licence** | CC BY-SA 4.0 — evidenced by the licence text committed at `WaterProjectFiles/SierraLeone_BGS_Hydrogeology/AfricaGroundwaterAtlasCountryMap-LicenceInformation_V1.2.txt` |
| **Required attribution** | "British Geological Survey. 2019/2021. Africa Groundwater Atlas Country Hydrogeology Maps. Africa Groundwater Atlas (https://www2.bgs.ac.uk/africagroundwateratlas/index.cfm)" — the wording the licence prescribes |
| **Changes made** | Reprojected and converted to GeoJSON, clipped to the Sierra Leone window, line-simplified and reclassified by `web/build_geodata.py`. The licence requires changes to be indicated; they are, here and in the file's own `description` field. |

> **ShareAlike propagates.** The derived GeoJSON declares itself CC BY-SA 4.0
> in its own `description` field, and anything built from it inherits that.
> That includes the two published web bundles, which embed it verbatim. Do not
> relicense them, and do not add terms that restrict what CC BY-SA 4.0 permits.

### geoBoundaries — Sierra Leone ADM0 / ADM2 / ADM3 · **CC BY 4.0**

| | |
|---|---|
| **Files** | `src/groundwater/data/sl_admin_geoboundaries.geojson`, `src/groundwater/data/sl_chiefdoms_geoboundaries.geojson` |
| **Source** | geoBoundaries gbOpen, `geoBoundaries-SLE-ADM0/ADM2/ADM3_simplified.geojson`, https://github.com/wmgeolab/geoBoundaries — **release version unrecorded, needs confirmation** |
| **Licence** | CC BY 4.0 — asserted in the files' own attribution fields and at `web/build_geodata.py` |
| **Required attribution** | "Runfola, D. et al. (2020). geoBoundaries: A global database of political administrative boundaries. PLoS ONE 15(4): e0231866. CC BY 4.0" |
| **Changes made** | Clipped, simplified, and each chiefdom tagged with its parent district. The merged "Koya" feature is split by longitude into two chiefdoms (`split_koya_feature`). The district set predates the 2017 creation of Karene and Falaba, so it carries 14 districts; the file's own `description` says so. |

### USGS Geologic Map of Africa · **US Government work, public domain**

| | |
|---|---|
| **Files** | `src/groundwater/data/sl_geology_usgs.geojson` |
| **Source** | `geo2_7g`, USGS Open-File Report 97-470A, 1:5,000,000, obtained via the github.com/Heed725/Africa_Geology_Data_Shapefile mirror |
| **Licence** | Public domain as a work of the US Government — asserted at `web/build_geodata.py`. **The mirror's own terms are unverified;** prefer re-retrieval from pubs.usgs.gov to remove the dependency on a third party. |
| **Required attribution** | "United States Geological Survey (1997). Geologic Map of Africa, Open-File Report 97-470A." |
| **Changes made** | Clipped to the Sierra Leone window and line-simplified. |

### Statistics Sierra Leone — 2015 Population and Housing Census · **unverified — needs confirmation**

| | |
|---|---|
| **Files** | `src/groundwater/data/sl_population_district.csv`, `sl_population_chiefdom.csv`, and the derived `sl_chiefdom_district.csv` and `sl_census_crosswalk.csv` |
| **Source** | 2015 PHC, "Distribution of Total Population by Regions, Districts and Chiefdoms"; the chiefdom table via the github.com/timothy-horton/SL_Map mirror |
| **Licence** | **Unverified.** Official government statistics; no licence statement was found in this repository or asserted upstream. Confirm with Statistics Sierra Leone before redistributing. |
| **Required attribution** | "Statistics Sierra Leone (2015). Population and Housing Census." |
| **Notes** | District totals sum to the official 7,092,113, which the build asserts. The intermediary mirror's terms are separately unverified. |

### WHO Guidelines for Drinking-water Quality · **values only, see notes**

| | |
|---|---|
| **Files** | `src/groundwater/data/who_guidelines.csv` |
| **Source** | WHO Guidelines for Drinking-water Quality, 4th edition incorporating the 1st and 2nd addenda |
| **Licence** | The table holds guideline *values*, transcribed as short factual figures, not WHO text. The publication itself is CC BY-NC-SA 3.0 IGO. **Confirm before redistributing any WHO prose.** |
| **Required attribution** | "World Health Organization. Guidelines for Drinking-water Quality, 4th edition." |
| **Notes** | The `sl_standard` column is marked `provisional` wherever it is a WHO figure carried across rather than a confirmed Sierra Leone Standards Bureau value; see `QUESTIONS.md`. |

### Water Point Data Exchange (WPdx+) · **CC BY 4.0 (nothing committed)**

| | |
|---|---|
| **Files** | none — fetched at runtime from `data.waterpointdata.org`, or supplied by the user as CSV |
| **Licence** | CC BY 4.0, as asserted at `src/groundwater/waterpoints.py`. **Not independently verified against wpdx.org's terms.** |
| **Required attribution** | "Water Point Data Exchange (WPdx+), CC BY 4.0, https://www.waterpointdata.org" |
| **Notes** | Nothing is redistributed, so there is no obligation on this repository; the notice is for downstream users of exported data. |

## Reference documents

`WaterProjectFiles/` holds nine third-party publications (about 23 MB) that
the toolkit's methods are grounded in — RWSN/Skat drilling and supervision
guides, a UNICEF procurement toolkit, and the MoWR-SALWACO geology map.

**No redistribution grant for any of them has been established.** Unlike the
BGS folder, none carries a licence file, and nothing in this repository states
a right to republish them. Being the source of a method is provenance, not
permission.

Until each one is checked against its publisher's terms, treat this directory
as unverified for redistribution. The options, in rough order of preference:

1. Replace each PDF with a citation and a link, keeping the bibliography in
   `src/groundwater/reporting/citations.py` (which already carries most of
   them) and dropping the binaries. This also removes 23 MB from every clone.
2. Obtain and commit written permission or the applicable licence per document.
3. Keep them in a private working repository rather than a published one.

| Document | Apparent publisher | Redistribution right |
|---|---|---|
| Borehole Drilling – Planning, Contracting & Management: Introduction | RWSN / Skat | unverified |
| Professional Water Well Drilling | RWSN / Skat | unverified |
| Supervising Water Well Drilling: A guide for supervisors | RWSN / Skat | unverified |
| Procurement and Contract Management of Drilled Well Construction | UNICEF / RWSN | unverified |
| Costing and Pricing: A Guide for Water Well Drilling Enterprises | RWSN / Skat | unverified |
| Borehole Costing Model V2.8 BETA & Quick Start Guide | RWSN / Skat | unverified |
| WASH Funders Infrastructure Checklists: Boreholes and Handpumps | unattributed in file | unverified |
| Geology of Sierra Leone (MoWR-SALWACO 2017) | Government of Sierra Leone | unverified |
| Africa Groundwater Atlas Country Maps User Guide (OR/21/063) | British Geological Survey | **CC BY-SA 4.0** — the one document whose licence is evidenced |

## Software dependencies

Runtime dependencies are declared in `pyproject.toml` and installed from PyPI;
they are not vendored here and keep their own licences (numpy, scipy,
matplotlib, openpyxl, python-docx, PyYAML: BSD or MIT; streamlit: Apache-2.0).
The browser app vendors no third-party JavaScript: `docs/js/*.js` is written
for this project, and the Depth Spine workspace bundles React (MIT) into
`src/groundwater/depth_spine/frontend/` and `static/workspace.html` at build
time.
