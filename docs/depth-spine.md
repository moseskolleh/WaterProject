# Depth Spine — a redesigned borehole workspace

Direction **2a Depth Spine** from the toolkit redesign study, built against the
real package. One shared depth axis for the whole borehole: evidence on the
left, derived decisions on the right, and the screened intervals directly
manipulable. The **2b sign-off layer** sits on each stage's rail rather than
being a second application.

It is a page in the main app — **Investigation → Depth Spine** — sharing the
project's session state with every other page:

```bash
streamlit run app/streamlit_app.py
```

The drilling log the Borehole design page parsed is the hole the spine draws;
the pumping test and the water quality analysis fill in the other two stages as
they are loaded, and the page says which are still missing rather than showing
an empty tab. Screens placed on the section are written back to
``st.session_state.borehole_design``, so the design drawing, the Costing & BoQ
page and the completion report all follow from the same object — a screen moved
here is a screen moved everywhere.

## Two renderings, one workspace

The workspace draws two ways, because two deployments support different things:

| | Streamlit app | Browser demo (WebAssembly) |
| --- | --- | --- |
| Rendered by | the custom component | `st.iframe` / `st.components.v1.html` |
| Screens edited by | dragging the handles | typing the intervals |
| Everything else | identical | identical |

A custom component serves its frontend from disk over HTTP, which the
in-browser runtime has no way to do. So `npm run build:inline` produces a
second, self-contained build — all CSS and JS inlined, the payload baked in —
which the demo puts in an iframe. It carries no handles, because there is no
Python on the other end to re-derive an interval, and the page offers the same
edit as numbers instead. The figures are the same figures: both renderings draw
the payload `build_view` produced.

The static build ships **inside the package**, at
`groundwater/depth_spine/static/workspace.html`, because the demo mounts the
package into a filesystem where `ui/` does not exist.

## The rule this is built on

**The browser computes no hydrogeology.** Every figure the workspace shows —
the design, the safe yield, the guideline comparison, the corrosivity indices,
the bill of quantities — is produced by `groundwater.*`, the same functions that
produce the .docx reports. The frontend owns the depth-to-pixel mapping and the
pointer, and nothing else.

That is why moving a screen goes back to Python. Dragging updates the drawing
locally, because a pointer has to feel attached to what it is dragging; on
release the intervals are handed to `design_borehole(screens_m=...)` and the
casing string, annulus, flags and bill of quantities all come back re-derived.
The round-trip costs a Streamlit rerun. The alternative — a second
implementation of the design rules in TypeScript — costs correctness, which is
worse.

```
ui/depth-spine/                     React + Vite + TypeScript frontend
  src/domain/view.ts                types for the payload — types only, no logic
  src/domain/scale.ts               THE depth <-> pixel mapping, built per hole
  src/components/                   Workspace, stages, columns, charts, SignOff
  dist/                             committed build (Streamlit Cloud has no npm)

src/groundwater/depth_spine/
  view.py                           builds the payload from the analysis objects
  projects.py                       loads the bundled samples via normal ingestion
  __init__.py                       the component wrapper

app/streamlit_app.py                the Depth Spine page and the round-trip
tests/test_depth_spine.py           payload, override and clipping behaviour
```

## What each stage shows

**Design.** The cuttings log, the casing string and the water levels on one
axis, at a scale computed from the hole so a 70 m borehole and a 30 m borehole
both fill the track. The safe yield is shown as a band, never a bare number,
because `recommend_yield` rests on an assumed storativity, effective radius and
seasonal decline — the envelope is the honest output and the toolkit already
computes it. Transmissivity is listed by method so agreement is visible rather
than claimed. Flags are the toolkit's own `DataFlag` objects, codes and all, so
what is on screen is what a reviewer reads in the report.

A pumping level is only drawn as a pumping level when `analyse_pumping_test`
found one — the last readings agreeing within 5 cm. When it did not, as in the
Dr. Timbo test, the line is labelled the deepest level reached and says so.

**Water quality.** Every determinand as a multiple of its own binding limit on
one shared log axis, so compliance is a line crossed rather than two numbers
compared. The limits come from `data/who_guidelines.csv` and the ratio is
computed in `view.py`, so the browser never parses a limit string. All three
kinds of exceedance are kept distinct — health-based, national standard and
acceptability — because a national limit exceeded is a compliance failure, not
a matter of taste. Piper and Stiff are drawn from the milliequivalents the ionic
balance already computed, so the diagrams and the balance check cannot disagree.
Corrosivity shows all four indices the toolkit computes, classified as it
classifies them.

**Costing & BoQ.** `inputs_from_design` already ties quantities to the design;
this stage makes that visible. Move a screen and the casing, screen and gravel
pack lines follow, because both come from the same `BoreholeDesign`. Cost and
price stay apart as the RWSN method insists: direct cost, then overheads, then
margin, with the contingency shown separately. Assumptions the estimate filled
in are listed rather than hidden.

**Sign-off.** Accepting is one press; overriding costs a value and a reason,
because the override is what ends up in front of the client with a name on it.
Moving a screen reopens the design and costing decisions — a signature has to
belong to the numbers that were in front of the person when they gave it.

## Colours

The workspace keeps the study's dark canvas - a borehole section is a drawing,
and the lithology, casing and water lines read better against it than against
paper white - but the accent is the house accent, not the study's teal. The
tokens are generated:

```bash
python web/make_theme.py     # .streamlit/config.toml + ui/depth-spine/src/tokens.css
cd ui/depth-spine && npm run build:all && cd - && python web/build_demo.py
```

`HouseStyle.accent_color` is the one source. The app theme takes it neat; the
workspace needs it lightened, which is done in Oklab so the hue survives, and
every pair is checked against WCAG AA before anything is written. Water moves
from blue to cyan in the same change: with the accent now on the house blue, a
water level and a button would otherwise have been the same hue, and in a
section drawing that is a real ambiguity rather than a tidiness point. The hues
that encode what a thing *is* - pump orange, screen green, the lithology fills -
are the study's own and stay put.

## Changes to existing code

Three, all small and additive:

1. **`design/designer.py`** takes an optional `screens_m`, the analyst's screen
   placement. The rest of the string is assembled by the same rules and the same
   checks still run, so an analyst-placed screen is validated exactly like a
   generated one. Intervals that do not fit are clipped or dropped **with a
   flag** rather than silently moved. The generated path is unchanged, and a
   test asserts it.

2. **`web/build_demo.py`** inlines `.html` files from the package, so the static
   workspace travels into the demo bundle (about 250 KB). Importing the package
   no longer requires either build — the component is declared on first use —
   so the demo can import it and use the static path.

3. **`_next_step` in `app/streamlit_app.py`** takes an optional `key`. It
   derived the widget key from the destination page alone, so two pages routing
   to the same next page collided; the Depth Spine and Borehole design pages both
   lead to Costing & BoQ.

## Data

The workspace reads whatever the project has loaded — an uploaded workbook, a
bundled sample, or a reloaded project file — through the app's normal ingestion.
Nothing is fixture data. With the bundled Dr. Timbo's Residence sample loaded,
BH-1 is 70 m in Western Area Rural, strikes at 12 and 30 m, four generated
screens, safe yield 0.97 m³/h (0.28 to 1.2), and water that is **not** suitable
for drinking on manganese and total coliforms, in water the toolkit classes as
strongly corrosive.

`depth_spine/projects.py` loads the bundled samples through the same ingestion
chain without the app, for scripts and for the tests. Kuntolo and Rokel carry a
step test and a VES survey respectively, so they have no logged hole to draw a
section for and it declines to offer them.

## Rebuilding the frontend

```bash
cd ui/depth-spine && npm install
npm run build         # the component  -> ui/depth-spine/dist
npm run build:inline  # the static page -> src/groundwater/depth_spine/static/
npm run build:all     # both — run this before committing a UI change
python web/build_demo.py   # then refresh the demo bundle

DEPTH_SPINE_DEV=1 streamlit run app/streamlit_app.py  # against the Vite dev server
```

Both builds are committed, for the same reason: neither Streamlit Community
Cloud nor GitHub Pages can run npm.

`ui/depth-spine/dist` is committed on purpose, and its `.gitignore` negates the
repository-root `dist/` rule.

## Not built

Programme-scale siting (2c), the living report (2d) and phone field capture (2e)
are separate surfaces. The section is the spine; `Plan` and `Tables` were empty
tabs in the study and are not implemented. There is no VES column, because no
bundled project has both a sounding and a drilled hole — it belongs here once
one does.
