# Depth Spine — a redesigned borehole workspace

Direction **2a Depth Spine** from the toolkit redesign study, built against the
real package. One shared depth axis for the whole borehole: evidence on the
left, derived decisions on the right, and the screened intervals directly
manipulable. The **2b sign-off layer** sits on each stage's rail rather than
being a second application.

It runs alongside the existing toolkit, not in place of it:

```bash
streamlit run app/depth_spine_app.py     # app/streamlit_app.py is untouched
```

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

app/depth_spine_app.py              the preview app and the round-trip
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

## Changes to existing code

Two, both small and additive:

1. **`design/designer.py`** takes an optional `screens_m`, the analyst's screen
   placement. The rest of the string is assembled by the same rules and the same
   checks still run, so an analyst-placed screen is validated exactly like a
   generated one. Intervals that do not fit are clipped or dropped **with a
   flag** rather than silently moved. The generated path is unchanged, and a
   test asserts it.

2. **`web/build_demo.py`** skips this package when inlining the browser demo. A
   Streamlit custom component serves a built frontend from disk over HTTP, which
   the in-browser runtime cannot do, so shipping it there would only add weight
   that cannot run.

## Data

The workspace reads the bundled sample projects through the normal ingestion
chain — no fixtures. Dr. Timbo's Residence, BH-1: 70 m in Western Area Rural,
strikes at 12 and 30 m, four generated screens, safe yield 0.97 m³/h (0.28 to
1.2), and water that is **not** suitable for drinking on manganese and total
coliforms, in water the toolkit classes as strongly corrosive. Kuntolo and Rokel
carry a step test and a VES survey respectively, so they have no section to draw
and are not offered.

## Rebuilding the frontend

```bash
cd ui/depth-spine && npm install && npm run build     # writes ui/depth-spine/dist
DEPTH_SPINE_DEV=1 streamlit run app/depth_spine_app.py   # against the Vite dev server
```

`ui/depth-spine/dist` is committed on purpose, and its `.gitignore` negates the
repository-root `dist/` rule: Streamlit Community Cloud has no npm, so the
component serves that directory as-is. Rebuild and commit it whenever the UI
changes.

## Not built

Programme-scale siting (2c), the living report (2d) and phone field capture (2e)
are separate surfaces. The section is the spine; `Plan` and `Tables` were empty
tabs in the study and are not implemented. There is no VES column, because no
bundled project has both a sounding and a drilled hole — it belongs here once
one does.
