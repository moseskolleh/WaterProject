# Depth Spine — a redesigned borehole workspace

Direction **2a Depth Spine** from the Groundwater Investigation Toolkit
redesign study, built for real, with the **2b sign-off layer** as a strip on each stage's rail
rather than a second application. Three stages: Design, Water quality,
Costing & BoQ.

```
ui/depth-spine/          React + Vite + TypeScript frontend
  src/domain/            the model — pure functions, no React
    types.ts             borehole, VES layers, lithology, construction, hydraulics
    sample.ts            Dr Timbo BH-01
    scale.ts             THE depth <-> pixel mapping (10 px/m). Nothing else converts.
    derive.ts            safe yield, pump setting, open area, gravel pack, checks
    quality.ts           WHO comparison, ionic balance, Piper/Stiff, LSI, verdict
    costing.ts           RWSN bill of quantities, cost vs price, programme estimate
    decision.ts          the sign-off ledger
  src/components/
    Workspace.tsx        shell: stage nav carrying each stage's decision state
    SignOff.tsx          accept / override-with-reason, shared by all three stages
    stages/              DesignStage, WaterQualityStage, CostingStage
    columns/             DepthRuler, Ves, Lithology, Construction, Hydraulics
    charts/              GuidelineSpine, PiperDiagram, StiffDiagram
    useScreenDrag.ts     pointer + keyboard manipulation of the screen
  src/streamlit/bridge.ts   Streamlit component postMessage protocol
  dist/                  committed build (Streamlit Cloud cannot run npm)

src/groundwater/depth_spine/
  __init__.py            the Streamlit component wrapper
  samples.py             Dr Timbo BH-01 and its analysis, in Python

app/depth_spine_app.py   preview and test harness, renders the ledger
```

## Running it

```bash
# Frontend
cd ui/depth-spine && npm install && npm run dev   # http://localhost:5173
cd ui/depth-spine && npm run build                # writes ui/depth-spine/dist

# Streamlit preview, from the repository root
streamlit run app/depth_spine_app.py

# Against the Vite dev server, for hot reload
DEPTH_SPINE_DEV=1 streamlit run app/depth_spine_app.py
```

This runs alongside `app/streamlit_app.py` rather than replacing it. For a
Streamlit Community Cloud preview, point a second app at
`app/depth_spine_app.py`. `ui/depth-spine/dist` is deliberately **not**
gitignored — the cloud runner has no npm, so the built frontend has to be
committed. Rebuild and commit it whenever the frontend changes.

## Design — the Depth Spine

There is a single depth↔pixel mapping (`ui/depth-spine/src/domain/scale.ts`, 10 px/m) and every
column calls it. That is what makes the alignment true rather than drawn: a
screen that misses a water strike cannot be rendered as though it hits one.

The screened interval is the only editable thing. Drag either green handle, drag
the body of the screen to move it whole, or focus a handle and use the arrow keys
— 0.1 m a press, 1 m with Shift. Each change re-derives:

| Output | Rule |
| --- | --- |
| Screen length, open area | Slot geometry: 6 rows of 1.0 × 50 mm slots at 16 mm pitch on 125 mm uPVC → 4.8 %. The percentage is a property of the slotting, so the tile also shows m² over the current length, which does move. |
| Pump setting | 2 m above the base of the screen, capped clear of the sump. |
| Submergence | Pump setting − pumping level; flagged below 3 m. |
| Gravel pack | Screen top − 4 m to screen base + 3 m. |
| Sump | 3 m below the screen, capped at TD − 2 m. |
| Strike verdict | Which of the three water strikes the screen — or the pack — still connects. |
| Safe yield / T | Cooper-Jacob: T = 2.3Q/4πΔs; safe yield = test rate × safety factor. |
| Live checks | Six checks re-evaluated on every change; four are geometric and move with the handles. |

## Water quality — the guideline as the spine

Same idea, different axis: every determinand is drawn as a multiple of *its own*
guideline value on one shared log scale, so compliance is a line crossed rather
than two numbers compared. Determinands with a pass/fail guideline (E. coli,
total coliforms) get a "not detected" pill instead of a meaningless bar.

Everything on the page is computed from the analysis:

- **Ionic balance** from meq/L, against a ±5 % acceptance limit. It runs at
  −3.0 %, which is what licenses the rest of the page.
- **Piper** — a real trilinear construction. The gap between the triangles equals
  their side length, which is what puts the diamond's lower vertex at apex height
  and makes the 60° projection rays land correctly.
- **Stiff** — meq/L, Na+K / Ca / Mg against Cl / HCO₃ / SO₄.
- **Langelier Saturation Index** — −2.0 here, i.e. strongly undersaturated. That
  is the derived decision that matters commercially: specify stainless or uPVC
  rising main, because galvanised iron will corrode in this water and push the
  iron figure up further. It also answers the check that direction 2e showed
  blocked on "needs pH + EC from §6".
- **Verdict** — health-based or microbiological exceedance ⇒ not potable;
  acceptability-only exceedance ⇒ potable with a caveat. Iron at 0.40 mg/L
  against 0.3 puts this sample in the middle case.

## Costing — the BoQ the design actually drives

This closes the loop the prototype's hint text promises. Quantities are
functions of the borehole and the current screen interval, not typed in:
plain casing = screen top + sump; screen = screened length; gravel pack and
grout = annulus volume × interval; rising main = pump setting depth. Change the
screen on the Design stage and those lines move, highlighted in the table.

Cost and price are kept apart, as the RWSN method insists: unit rates are the
contractor's **cost** and are editable inline; overhead and margin are applied
once, in the rail, to produce the **price**. The unit borehole comes out at
US$ 8,953 cost / US$ 9,870 price, next to the US$ 9,850 in the design study.
Breakdowns by stage and by resource, and a 12-borehole programme estimate with
shared mobilisation and expected dry attempts, all follow from the same numbers.

## The sign-off layer

Each stage's rail ends with the decision. Accepting is one press; overriding
costs a value and a reason, because the override is what ends up in front of the
client with a name on it. A signed record carries the certified value, the
toolkit's recommendation, the reason, the signatory, the timestamp, and whether
a check was still flagged at the time. Editing the design reopens the design and
costing decisions — a signature has to belong to the numbers that were in front
of the person when they gave it. The header shows the ledger state as a dot per
stage, and the whole ledger is the component's return value in Python.

## Where this departs from the design study, and why

1. **The mockup's headline check is arithmetically wrong.** It shows a green
   "Screen brackets all 3 strikes — 28–40 m covers 26.5, 33.0 and 38.5 m", but
   26.5 m is above the screen top of 28 m, exactly as the mockup itself draws it.
   Rather than reproduce a false check, the verdict has three states: all strikes
   screened; strikes outside the screen but inside the gravel pack (the real case
   at 26.5 m — the pack is continuous, so that inflow still drains to the screen,
   and this is what the baseline shows); or strikes outside both, a genuine miss
   that turns the card amber. Dragging the screen down 6 m still breaks it.

2. **The ruler is aligned to the tracks.** In the prototype the depth ruler sits
   20 px — 2 m — above the columns it labels, because it has no column heading.
   On a screen whose whole premise is depth registration that could not stand.

3. **Layer bar widths are computed, not hand-placed.** VES bar width is a
   log-linear function of resistivity fitted to the prototype's widths; two bars
   land within about 5 px of where they were drawn.

4. **Lithology names dodge the strike callouts.** Both live in the same lane. The
   prototype hand-nudged them; here a name shifts automatically when a strike
   would overprint it, so it survives different strike depths.

5. **One check added to the design stage.** "Screen inside the fractured
   interval" — the prototype's five checks contain nothing that responds to the
   top handle, so dragging the screen out of the aquifer gave no feedback.

6. **Water quality and costing are new screens.** The design study never drew
   them; it listed them as the next thing to build. They follow 2a's grammar —
   dark instrument surface, evidence left, derived decisions right, one shared
   axis where the domain has one.

7. **`Plan` and `Tables` are placeholders.** They are tabs in the prototype with
   no content behind them. `Section` is the spine and is fully built.

## Not built

Programme-scale siting (2c), the living report (2d) and phone field capture (2e)
are separate surfaces. The costing stage carries a small multi-borehole estimate,
which is the part of 2c that belongs to a cost model rather than to a map.
