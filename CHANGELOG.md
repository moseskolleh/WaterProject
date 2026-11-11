# Changelog

One section per version, newest first. Each section lists its entries by
their headings, in the order its file holds them; the full text of each is in
`changelog/<version>.md` under the same heading (changelog/unreleased.md for
"Unreleased"). PLAN.md step 0.4 closed the long "changes pending release"
entry as 0.3.0: in changelog/0.3.0.md everything below the Stage 0 notes is
that entry, kept as it was written.

To add an entry, write it at the top of changelog/unreleased.md and add its
heading as the first bullet under "Unreleased" here. To cut a release, rename
changelog/unreleased.md to `changelog/<version>.md`, change its title and the
sentence under it to name the version, rename the section and its link here
to match, and start a new changelog/unreleased.md under a new "Unreleased"
section.
tests/test_changelog.py holds each list to its file, and
.github/workflows/release.yml builds a release's notes from its section.

## Unreleased

Full text: [changelog/unreleased.md](changelog/unreleased.md)

- The browser app redesigned: quiet colour, sentence case, the borehole's steps first
- The three largest browser scripts are written as parts and joined
- make_reference.py is an entry file over a package, a module for each section
- The changelog is an index, with each version's text in a file of its own
- Clean house: the stranded pull requests closed, the dependencies brought level
- The Theis fit is one search in both engines, finished at the minimum
- Fitted transmissivities in the pumping prose print to three figures
- Links that go to a page, and less before the first paint (PLAN.md steps 1.4 and 1.5)
- A saved survey reopens without inverting it again (PLAN.md step 1.6)
- The Streamlit app runs only the page on screen (PLAN.md step 1.1)
- Projects are stored in IndexedDB (PLAN.md step 1.3)
- One source for the words and defaults both engines use (PLAN.md step 1.7)
- The two engines held to each other on generated field sheets (PLAN.md step 1.8)
- Type and lint checks for the code that had none (PLAN.md step 1.9)
- One engine or two: two (PLAN.md step 1.10)
- A pumping test co-pilot (PLAN.md step 2.1)
- A VES co-pilot (PLAN.md step 2.2)
- Photo evidence with provenance (PLAN.md step 2.4)
- A field kit for crews without a device (PLAN.md step 2.5)
- A drilling log co-pilot (PLAN.md step 2.3)
- VES: a range of models, not one (PLAN.md step 3.1)
- The pumping test given a spread, a flow regime and a large-diameter fit (PLAN.md step 3.2)
- The browser engine's Bessel functions, and a fuzz sample that stays put
- The chance of a working borehole (PLAN.md step 3.3)
- The cost as a distribution (PLAN.md step 3.4)
- The value of one more measurement (PLAN.md step 3.5)
- One way of reporting uncertainty (PLAN.md step 3.6)
- Reading an elevation model the operator supplies (PLAN.md step 4.1, part a)
- Terrain analysis in both engines (PLAN.md step 4.1, part b)
- Terrain pages in both apps (PLAN.md step 4.1, part c)
- The fuzz suite tells a knife edge from a divergence
- Lineament candidates in both engines (PLAN.md step 4.2, part a)
- Lineament candidates drawn in both apps (PLAN.md step 4.2, part b)
- A survey plan across the lineament candidates (PLAN.md step 4.3)
- Sums added as the browser adds them
- What a desk study says, in both engines (PLAN.md step 4.4, part a)
- The desk study, the eleventh document (PLAN.md step 4.4, part b)
- A ledger of predictions and outcomes (PLAN.md step 5.1, part a)
- The ledger in both apps (PLAN.md step 5.1, part b)
- The calibration in both engines (PLAN.md step 5.2, part a)
- The calibration report in both apps (PLAN.md step 5.2, part b)
- Calibration sets in both engines (PLAN.md step 5.3, part a)
- A calibration set in force, in both engines (PLAN.md step 5.3, part b)
- Calibration sets on the Portfolio page, in both apps (PLAN.md step 5.3, part c)
- The VES quadrature, short soundings and what "converged" means
- Sanitary inspection, in both engines and both apps (PLAN.md step 7.5)
- The rising main chosen from the water (PLAN.md step 7.2)
- The VES potential integral under a thick conductive cover, and two VES sentences in the catalogue
- What the VES readers take from a sheet, and a resistive layer over water read as cover rather than bedrock
- Drilling logs in feet, the supervision record, the readiness gate and the asset registry
- Earlier projects in degrees, the survey plan's lookup, the water point reader and the plan year
- Service rounds, in both engines and both apps (PLAN.md step 7.3)
- Scanned sheets, the Depth Spine's price and limit line, and the traverse's direction
- How long boreholes keep working, in both engines and both apps (PLAN.md step 7.4)
- Pooled evidence without pooled data (PLAN.md step 5.5)
- What the pumping test readers take from a sheet, when a level has stabilised, and the yield search's floor
- Reports from the plate and by SMS (PLAN.md step 7.1)
- What a laboratory sheet's units and bases say, a clock read as a quantity, and the gravel pack under the seal
- Contractor scorecards (PLAN.md step 6.3)
- Documents that can be verified, in both engines and both apps (PLAN.md step 8.1)
- One evidence bundle for each borehole, in both engines and both apps (PLAN.md step 8.3)
- Accessibility in the browser app (PLAN.md step 9.4)
- What a dry hole costs under no water, no pay, ties in the siting and the value of a measurement, and the water layer's resistivity
- Where to drill next, within a budget (PLAN.md step 6.1)
- A forecast recorded again with no log loaded, two projects at one village's points, which copy a pool keeps, the definition of success the calibration scores at, and numbers a hand-edited file holds
- Copies that name two boreholes, a scorecard borehole saved before its ledger had an identity, and numbers too large to hold
- What is still open from these steps

## 0.3.0

Full text: [changelog/0.3.0.md](changelog/0.3.0.md)

- The release
- The browser engine runs in a worker (PLAN.md step 1.2)
- PR #52's performance work, carried onto main (step 0.1)
- PR #54, landed as three parts (step 0.1)
- PR #17's wizard fix, ported (step 0.1)
- One command for the checks, and a CI that checks more (steps 0.2 and 0.6)
- A performance baseline (step 0.3)
- The small untruths (step 0.5)
- What this release leaves open
- The repair roadmap
