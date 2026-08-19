# GeoLibre and the spatial side of this toolkit

A research note: what [GeoLibre](https://geolibre.app/) is, what this
toolkit can and cannot do spatially today, and which GeoLibre features
are worth adopting — ordered by what they cost and what they return.

Sources: the GeoLibre documentation set in
[`opengeos/GeoLibre`](https://github.com/opengeos/GeoLibre) (`docs/`,
which is what builds geolibre.app), read August 2026. GeoLibre is MIT
licensed, same as this toolkit's source.

---

## 1. What GeoLibre is

A free, open-source, client-side GIS. One codebase runs as a web app, a
Tauri desktop app (Windows/macOS/Linux), native iOS and Android, and as
a Jupyter widget. Built on MapLibre GL JS, deck.gl, DuckDB-WASM Spatial
and Turf.js.

The parts that matter here:

| Capability | Why it matters to us |
|---|---|
| **1,000+ Whitebox geoprocessing tools compiled to WebAssembly** — ~100 hydrology, ~100 terrain, ~155 remote sensing, ~315 vector, ~255 raster, ~65 LiDAR | Real spatial analysis with no server and no Python. Runs on web, desktop *and* Android |
| **`.geolibre.json` project format** — a documented, plain JSON file | We can *write* one from Python with no dependency at all |
| **Python package (`geolibre`)** — anywidget, two-way project sync, `to_html()` | An interactive map inside Streamlit / a notebook, and a standalone offline HTML deliverable |
| **`postMessage` embed API + `@geolibre/embed`** | Drive an embedded map from our own browser app: fly to a site, highlight a point, `exportImage()` a PNG back into a report |
| **Reads COG, GeoParquet, PMTiles, FlatGeobuf, Zarr by HTTP range request** | Cloud-native layers off any static file server — including one behind our own auth, or a local one |
| **Self-hosting** — Docker, `GEOLIBRE_NO_EXTERNAL_CDN=1`, `GEOLIBRE_SHARE_URL=off` | An air-gapped or field-office deployment is a documented, supported configuration |
| **Field Collection + NMEA GNSS over Web Serial/Bluetooth** | Offline map-based capture with a real receiver, not a phone's ±5 m fix |
| **Story maps, Print Layout with Atlas, QGIS/ArcGIS project import, SLD/QML export** | Client-facing and client-interoperable deliverables |
| **MCP server (`geolibre-mcp`)** | Author project files headlessly from an AI client |

---

## 2. Where we stand spatially

Everything spatial this toolkit produces today is **a static picture**.

**Python** (`groundwater.mapping`)
- `maps.py` — matplotlib figures in projected UTM: site location,
  iso-resistivity, overburden thickness, suitability. Scale bar, north
  arrow, coordinate grid, zone note. Interpolation is `scipy.griddata`
  (linear, nearest fill), convex-hull masked for suitability.
- `regional.py` — bundled GeoJSON (geoBoundaries ADM2 and chiefdoms,
  USGS geology, BGS hydrogeology), hand-written ray-casting
  point-in-polygon, choropleth, portfolio and admin maps.
- `export.py` — GeoJSON **points** only; GeoPackage points when
  geopandas is installed.
- `geo.py` — our own Krueger-series UTM 28N/29N transform. Correct,
  dependency-free, and worth keeping.

**Browser** (`docs/js/gwt-charts.js`) — `mapProjection`, `siteMap`,
`thematicMap`: hand-rolled canvas/SVG. No map library anywhere in
`docs/`, `ui/` or `app/`.

So, concretely, what is missing:

1. **No interactive map at all.** Nobody can pan, zoom, click a VES
   station, or toggle a layer.
2. **No basemap or imagery.** A site location map on a blank grid cannot
   answer "is that a swamp, a village, a road, a quarry?"
3. **No terrain.** Which is the gap that costs the most, because siting
   in weathered/fractured basement is largely a topographic argument.
4. **No geoprocessing.** No buffer, overlay, watershed, viewshed or
   zonal statistics. The separation distances in
   `data/site_separation_distances.csv` are enforced as *numbers*, never
   as geometry.
5. **Surfaces are thrown away.** `iso_resistivity_map` builds a real
   interpolated grid and renders it to PNG. The grid itself is
   discarded.
6. **Coverage uses straight-line radii.** `SERVICE_RADIUS_M = 500` is a
   haversine circle, not a walk.
7. **440 KB of GeoJSON is embedded in `docs/js/gwt-data.js`** — which is
   also what drags the BGS CC BY-SA ShareAlike obligation into our
   bundle.

---

## 3. Four routes in, cheapest first

### Route A — "Open in GeoLibre" deep link (an afternoon)

We already write WGS84 GeoJSON. Add a button:

```
https://web.geolibre.app/?data=<geojson-url>&style=<style-url>
```

Cost: a URL. Return: every exported layer becomes pannable, zoomable,
measurable and identifiable on satellite imagery, with no code in our
tree. `?tool=` also deep-links a specific processing tool with its form
pre-filled.

### Route B — write `.geolibre.json` project files (a week) ← **best value**

The format is documented and plain JSON: `mapView`, `basemapStyleUrl`,
`layers[]`, `styles{}`, `legend`, `storymap`, `widgets[]`, `metadata`.
Writing one needs **no new dependency** — it fits the "no heavy GIS
dependencies" rule exactly as `export_geojson` does.

Emit `<site>.geolibre.json` beside the seven `.docx` reports, carrying:
VES stations styled by suitability grade, the borehole, the chiefdom
boundary, geology and hydrogeology, nearby WPDx points coloured by
functionality, sanitary protection buffers, a legend, and a camera
already framed on the site.

That single file opens unchanged in the web app, the desktop app, on
Android and iOS, and in a Jupyter widget. It becomes the eighth
deliverable — the one the client can *interrogate* rather than read.

Keep it behind one adapter module. The format is at `version 0.1.0` and
will move.

### Route C — the Python package in Streamlit and notebooks (a week)

```python
from geolibre import Map
m = Map(center=(-11.8, 8.5), zoom=9, layout="embed")
m.add_choropleth(coverage_geojson, column="people_per_point", scheme="quantile")
m.add_markers(portfolio_points)
m.to_html("coverage.html")   # standalone, offline, no server
```

Two wins. The coverage choropleth and portfolio map become live instead
of static, and `to_html()` produces an interactive map that works with
the cable pulled out — which is the standard the rest of this project
already holds itself to.

Also exposes `list_whitebox_tools()` / `run_whitebox_tool()` from
Python, so terrain analysis does not mean leaving the notebook.

### Route D — embed and drive it from our own web app (two to three weeks)

```ts
import { connect } from "@geolibre/embed";
const map = await connect(iframe, { origin: APP_ORIGIN });
await map.setView({ bbox: siteBbox });
await map.highlightFeature({ layerId: "ves", filter: { id: "VES-3" }, fit: true });
const png = await map.exportImage();   // straight into the .docx
```

This gives `docs/` a genuine interactive map without us writing a map
engine, and `exportImage()` closes the loop back into report generation.
Requires a deployment that names our origin in `GEOLIBRE_EMBED_ORIGINS`
— so, self-hosting. Use `layout=viewer` or `maponly` so an embed cannot
be steered into authoring.

---

## 4. The spatial features worth building

### Tier 1 — changes the analysis, not just the picture

**4.1 Terrain-informed siting.** `siting/suitability.py` scores four
VES-derived quantities and its own docstring invites calibration. Add
terrain components from Whitebox, which ships them:

- `Slope`, `Aspect`, `Hillshade`
- `D8`/`DInf FlowAccumulation`, `WetnessIndex` (TWI), `StreamOrder`
- `Watershed` / `Basin` delineation
- edge detection over hillshade for fracture lineaments

New components: `terrain_position` (valley bottom versus interfluve),
`wetness_index`, `distance_to_lineament`, `upslope_contributing_area`.
In basement terrain these are not decoration — valley bottoms and
lineament intersections are where the weathered profile thickens and
the fractures connect. Needs a DEM (SRTM or Copernicus 30 m COG) added
to `data_provenance.yaml` with its SHA-256, like everything else.

**4.2 Pre-survey screening — a lifecycle stage we do not cover.** The
toolkit currently begins when field data arrives. It has nothing to say
about *where to put the VES lines*. Terrain plus geology plus WPDx plus
settlements, binned to H3 or DGGS cells and ranked per chiefdom, answers
"where should the survey team go next week". This is new ground rather
than a better rendering of old ground.

**4.3 Walk-time service areas instead of circles.** GeoLibre has
isochrone / service-area tools. A 30-minute walk is the JMP basic-service
criterion — the indicator donors actually report against. Replacing the
500 m haversine circle in `waterpoints.py`, and the district ratio in
`coverage.py`, with population inside a walk isochrone turns "people per
functional water point" into "people within 30 minutes of a functional
improved source". Same data, an honest indicator.

**4.4 Gridded population.** `planning.py` says plainly that a uniform
growth rate cannot reorder the ranking. Gridded population (WorldPop,
GHSL) is a COG; GeoLibre reads COGs and does zonal statistics. Zonal
sum inside a service-area polygon gives population served without the
uniform-density assumption — which is exactly the fix that document
argues for. Add the raster to `data_provenance.yaml`.

**4.5 Sanitary protection zones as geometry.** Turn
`site_separation_distances.csv` into buffers — 20 m septic/latrine, 20 m
streams, 50 m existing boreholes, 1000 m dump or burial ground, 1000 m
coastline — drawn over imagery and intersected with mapped hazards.
`supervision/field_checks.py` keeps the numeric check; the map becomes
the evidence behind it, and encroachment becomes visible rather than
asserted. Good input to the readiness gate.

### Tier 2 — large gain, small change

**4.6 Write the interpolated surfaces as COGs.** `_interpolated_map`
already computes a 220×220 grid in UTM. Write it out as a Cloud
Optimized GeoTIFF as well as a PNG. Then it can be restyled, contoured,
zonal-summarised, and overlaid on imagery by anyone — and it unlocks
`split_map`, so iso-resistivity at a shallow and a deep AB/2 can be
compared with a swipe. That is a real geophysical interpretation aid we
do not have today.

**4.7 Registry as a time-tagged layer.** `registry.py` is an append-only
event stream with dates. Export it as time-tagged GeoJSON and the Time
Slider plugin animates borehole functionality over the programme's life.
Then **Emerging Hot Spot Analysis** (space-time cube plus Getis-Ord Gi\*)
classifies each area as a new, intensifying, persistent, diminishing or
sporadic failure cluster. That is a monitoring capability, shipped, that
we would otherwise have to write.

**4.8 Atlas map series.** Print Layout generates one page per feature.
For a 40-borehole programme (`costing/programme.py`), that is 40 framed
site maps with legend, scale bar and title block in one pass, instead of
40 calls to `site_location_map`.

**4.9 GeoParquet / PMTiles instead of embedded GeoJSON.** Converting the
bundled layers moves 440 KB of GeoJSON out of `gwt-data.js` and lets the
browser stream instead of embed. It also **contains the CC BY-SA
problem**: serving the BGS hydrogeology layer as its own PMTiles file
stops the ShareAlike obligation propagating into our JavaScript bundle
and the WASM page, which is a licensing simplification, not only a
performance one.

**4.10 DuckDB Spatial for the national join.** `coverage.py` does
ray-casting point-in-polygon in NumPy over a national WPDx pull.
`ST_Within` in DuckDB-WASM over GeoParquet is the same answer, faster,
and available in the browser.

### Tier 3 — deliverables and field workflow

**4.11 Story map for handover and donor reporting.** Scroll-driven
chapters over the live map, presenter view, printable PDF handout, and
standalone HTML export. "Where we surveyed, what we found, what we
built, who it serves." The handover `.docx` stays; this is the version
someone reads.

**4.12 Field Collection as the registry's capture surface.** Point/line/
polygon with a custom form and a photo, placed by device GPS or by tap,
written to GeoJSON, works offline. `registry.py` already merges events
by content, so two phones recording the same visit converge — the
capture surface is the piece that is missing, and GeoLibre has it,
including **external NMEA GNSS over Web Serial or Bluetooth**. That
matters when a wellhead position is being check-summed into an asset
identifier.

**4.13 Geotagged photos as an evidence layer.** Supervision produces
hundreds of site photographs. GeoLibre imports them as a point layer
from their EXIF GPS.

**4.14 QGIS / ArcGIS interoperability.** GeoLibre imports `.qgs`/`.qgz`
and `.aprx`/`.mapx`, and exports symbology as SLD, QML and Mapbox GL
JSON. Our house style can travel to the client's own GIS at handover
rather than stopping at a PNG.

**4.15 A "Groundwater" UI profile.** GeoLibre's UI profiles tailor which
menus, panels and data sources are visible, so a deployment can present
a focused subset. A drilling supervisor should not be handed a
thousand-tool GIS.

---

## 5. Guardrails

- **Keep GeoLibre out of the certification path.** The deterministic,
  parity-checked pipeline that produces byte-identical outputs is this
  project's strongest claim. GeoLibre belongs beside it as a viewer and
  an analysis companion, never underneath a report the readiness gate
  vouches for.
- **Version churn.** `.geolibre.json` is `0.1.0`, and GeoLibre 1.0 is
  new. One adapter module, so a format change is one file.
- **Network discipline.** Today exactly two features reach the network,
  both button-gated. Basemaps, imagery, isochrones, geocoding and
  elevation lookups all reach out. Every GeoLibre-backed feature must
  stay a button with an offline path — a local PMTiles or MBTiles
  basemap, or a blank background.
- **Bundle size against the PWA promise.** The service worker keeps the
  whole app on the device. A thousand-tool WASM catalogue is not free;
  measure before bundling, and prefer the desktop app where the toolbox
  is genuinely needed.
- **Licensing.** Prefer *referencing* the BGS CC BY-SA layer by URL over
  inlining it in a shared project file — ShareAlike travels with an
  inlined copy. Any new DEM or population raster goes into
  `data_provenance.yaml` and `THIRD_PARTY_NOTICES.md` with its licence
  and SHA-256, and reads **unverified — needs confirmation** until it is
  evidenced.
- **Credentials.** `redactCredentials()` runs on anything leaving the
  workspace; the Python package redacts by default. Our own rule — the
  API key never enters a saved project file — must hold for
  `.geolibre.json` too.

---

## 6. Suggested first three commits

1. ~~**`mapping/geolibre.py`** — build a `.geolibre.json` from the objects
   we already have (`MapPoint`, WPDx points, chiefdom polygons, geology,
   hydrogeology), styled and legended, camera framed. Pure stdlib
   `json`. Plus an "Open in GeoLibre" button in both apps.~~ **Done.**
   `src/groundwater/mapping/geolibre.py` and its port in
   `docs/js/gwt-geolibre.js`, held to each other by a parity test. Layer
   ids are stable slugs rather than the format's own random UUIDs, so
   the same data writes the same bytes twice; per-feature colours ride
   as simplestyle properties rather than in a renderer schema that is at
   version 0.1.0; each layer carries its own credit; and a `window_km`
   trims the national context layers the way the printed local maps are
   windowed (1085 kB down to 203 kB for a 40 km window).
2. **COG output from `_interpolated_map`** — write the iso-resistivity
   and overburden grids as GeoTIFF alongside the PNG. Small change,
   unlocks restyling, contouring, zonal statistics and split-map.
3. **Sanitary protection buffers** — generate buffer polygons from
   `site_separation_distances.csv` into the project file, so the
   separation checks in `supervision/field_checks.py` have a map behind
   them.

Each is self-contained, adds no required dependency, and is useful on
its own if the next one never happens.
