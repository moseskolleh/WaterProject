"""Produce the reference values the browser app is checked against.

Runs the Python toolkit over the bundled sample workbooks and writes
``tests/webapp/reference.json``. ``tests/webapp/parity.mjs`` then runs the
same inputs through the JavaScript engine in headless Chromium and
compares the two, so the standalone web app cannot silently drift away
from the package it was ported from.

    python tests/webapp/make_reference.py            # regenerate the file
    python tests/webapp/make_reference.py --check    # verify it, don't rewrite
    node tests/webapp/parity.mjs

The committed file is checked in so ``parity.mjs`` runs without a Python
environment, and ``--check`` is what CI uses to keep it honest.

Producing the file needs the ``extract`` extra (``pip install -e
'.[dev,extract]'``): one of the reference values is what the Python PDF
reader makes of an unruled field sheet, and that reader is pdfplumber
backed. Reading the file needs nothing.

``--check`` compares within a tolerance rather than byte for byte. The
inversion and the Theis fit go through LAPACK, which is not bit
reproducible across BLAS builds: the same input gives 1.4021310045105808
on one machine and 1.4021310045105801 on another. Those last digits carry
no information about the toolkit, so requiring them to match would make CI
fail on a runner upgrade while a genuine change of a millimetre in a
screen depth slipped through. The tolerance is tight enough that any real
change in behaviour still fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Everything but main() is in the package beside this file, tests/webapp/reference:
# build() in reference/build.py, a module for each section of the file it
# fills, and in reference/common.py what the sections and --check share.
# This file stays the one to run, and the one other code loads.
#
# tests/test_ves_range.py and tests/test_pumping_spread.py load it by its
# path, with tests/webapp nowhere on sys.path, so its own folder goes there
# before the package is imported. Run as a script, or imported by
# tests/fuzz/engines.py and tests/test_desk_study.py, the folder is there
# already and nothing is added.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from reference.build import build  # noqa: E402
from reference.common import (  # noqa: E402
    CHECK_RTOL,
    DATA,
    OUT,
    PC_RTOL,
    RANGE_RTOL,
    REPO,
    drifted,
    pc_tolerated,
    range_tolerated,
)
from reference.lineaments import LINEAMENT_GENERATED  # noqa: E402
from reference.survey_plan import PLAN_CASES, _desk_terrain, _l1_run  # noqa: E402

# The names other code takes from this file, whichever module holds them now:
# tests/fuzz/engines.py compares the two engines with drifted;
# tests/test_ves_range.py and tests/test_pumping_spread.py hold
# range_tolerated and pc_tolerated; and tests/test_desk_study.py lays the desk
# study's terrain with _l1_run and _desk_terrain over LINEAMENT_GENERATED and
# PLAN_CASES. A name wanted from here that is not in this list is one import
# from its module away.
__all__ = [
    "CHECK_RTOL",
    "DATA",
    "LINEAMENT_GENERATED",
    "OUT",
    "PC_RTOL",
    "PLAN_CASES",
    "RANGE_RTOL",
    "REPO",
    "_desk_terrain",
    "_l1_run",
    "build",
    "drifted",
    "main",
    "pc_tolerated",
    "range_tolerated",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="compare the committed file against a fresh run instead of "
             "rewriting it; exit non-zero if anything really moved",
    )
    args = parser.parse_args()
    fresh = build()

    if not args.check:
        OUT.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {OUT}")
        return 0

    if not OUT.exists():
        print(f"{OUT} is missing; run this without --check to create it")
        return 1
    committed = json.loads(OUT.read_text(encoding="utf-8"))
    differences = [d for d in drifted(fresh, committed)
                   if not range_tolerated(*d) and not pc_tolerated(*d, committed)]
    if not differences:
        print(f"{OUT} agrees with this toolkit to {CHECK_RTOL:g} relative "
              "(the range of models to RANGE_RTOL, a badly fitting large-diameter "
              "fit to PC_RTOL)")
        return 0
    print(f"{OUT} disagrees with this toolkit in {len(differences)} place(s):")
    for path, a, b in differences[:20]:
        print(f"  {path.lstrip('.')}: fresh {a!r} vs committed {b!r}")
    print("\nIf the change is intended, regenerate with:\n"
          "  python tests/webapp/make_reference.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
