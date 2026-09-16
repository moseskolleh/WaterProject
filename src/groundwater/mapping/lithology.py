"""What the geology polygons are made of, rather than how old they are.

The bundled geological layer is the USGS Geologic Map of Africa at
1:5,000,000, and it carries seven classes for the whole country. They are
ages: "Paleozoic Igneous", "Precambrian", "Holocene". A driller cannot
use an age. What decides whether a borehole yields is the lithology -
whether the rock weathers to a regolith that stores water, whether it
fractures, whether it is porous in itself - and the USGS classes say
nothing about any of that.

They are also, in one case, wrong. The single polygon the USGS layer
calls "Paleozoic Igneous" is the Freetown peninsula, and the rock there
is the Freetown Layered Complex: a Jurassic layered gabbro, about 193
million years old, which is Mesozoic. A reader told "Paleozoic Igneous"
has been given a wrong age and no rock.

So this module annotates. It does not reclassify: the polygon and its
boundary still come from the 1:5M layer and are no more accurate for
being better named. What it adds is the formation name and lithology
from the Geology of Sierra Leone map (MoWR/SALWACO 2017, 1:600,000),
which this repository commits and the geophysical report already cites
in its prose, and a note on what that lithology means for drilling.

Where the two sources disagree on age, both are shown. Quietly rewriting
somebody else's dataset leaves a reader unable to tell what they are
looking at, which is a worse failure than the wrong age.
"""

from __future__ import annotations

import csv
import functools
import io
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

#: Which districts count as which region in the crosswalk. A coarse USGS
#: class covers different formations in different parts of the country,
#: so a row applies only where its region says it does.
_REGIONS: dict[str, tuple[str, ...]] = {
    "Western Area": ("western area", "western area urban", "western area rural"),
    "coastal plain": ("bonthe", "moyamba", "port loko", "kambia", "pujehun"),
    "north and centre": ("bombali", "tonkolili", "koinadugu", "karene", "falaba"),
    "interior": (),  # the default: everything the others do not claim
}

LITHOLOGY_CREDIT = (
    "Lithology: Geology of Sierra Leone (Fileccia et al. 2017, MoWR/SALWACO, "
    "1:600,000)"
)


@dataclass(frozen=True)
class Lithology:
    """What one geological class is, where this row applies."""

    usgs_code: str
    region: str
    formation_code: str
    formation_name: str
    lithology: str
    aquifer_character: str
    era_actual: str
    usgs_era_wrong: bool
    #: ``legend`` (quoted from the committed 2017 map) or ``published``
    #: (established regional geology, no source committed here)
    basis: str

    @property
    def codes(self) -> list[str]:
        return [c for c in self.formation_code.split(";") if c]

    def legend_label(self, usgs_unit: str, usgs_code: str) -> str:
        """The name to put in a map key.

        The formation first, because that is the thing a reader needs,
        then its own code, then the USGS code the polygon was actually
        drawn from. The last of those is not decoration: a 1:600,000 name
        sitting on a 1:5,000,000 line invites the reader to trust the line
        at 1:600,000, and the key has to stay traceable to the layer that
        drew it. The figure's footnote carries the rest of the argument.
        """
        if not self.formation_name:
            return usgs_unit
        parts = [self.formation_name]
        codes = [c for c in (self.formation_code.replace(";", ", "), ) if c]
        if usgs_code:
            codes.append(f"USGS {usgs_code}")
        if codes:
            parts.append(f"({'; '.join(codes)})")
        return " ".join(parts)

    def provenance_note(self, usgs_unit: str) -> str:
        """One line a figure can carry about this class, if it has earned one."""
        if not self.usgs_era_wrong:
            return ""
        return (
            f"The source layer dates this polygon as {usgs_unit}; it is the "
            f"{self.formation_name}, {self.era_actual}. The boundary is the "
            "1:5,000,000 one either way."
        )


def region_of(district: str | None) -> str:
    """Which crosswalk region a district belongs to."""
    name = (district or "").strip().lower()
    for region, members in _REGIONS.items():
        if name in members:
            return region
    return "interior"


@functools.lru_cache(maxsize=1)
def _rows() -> tuple[Lithology, ...]:
    text = (
        resources.files("groundwater") / "data" / "sl_lithology_usgs_crosswalk.csv"
    ).read_text(encoding="utf-8")
    return _parse(text)


def _parse(text: str) -> tuple[Lithology, ...]:
    body = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    out = []
    for row in csv.DictReader(io.StringIO(body)):
        out.append(
            Lithology(
                usgs_code=row["usgs_code"].strip(),
                region=row["region"].strip(),
                formation_code=row["formation_code"].strip(),
                formation_name=row["formation_name"].strip(),
                lithology=row["lithology"].strip(),
                aquifer_character=row["aquifer_character"].strip(),
                era_actual=row["era_actual"].strip(),
                usgs_era_wrong=row["usgs_era_wrong"].strip().lower() == "yes",
                basis=row["basis"].strip(),
            )
        )
    return tuple(out)


def load_crosswalk(path: str | Path | None = None) -> tuple[Lithology, ...]:
    """The lithology crosswalk, from the bundle or a replacement file."""
    if path is None:
        return _rows()
    return _parse(Path(path).read_text(encoding="utf-8"))


def lithology_for(
    usgs_code: str,
    district: str | None = None,
    path: str | Path | None = None,
) -> Lithology | None:
    """What the ground is, for one USGS class in one district.

    Falls back from the district's own region to ``all``, and returns
    ``None`` when the crosswalk has nothing to say - which is the honest
    answer for a class nobody has annotated, and leaves the map showing
    the source's own wording rather than a guess.

    With no district at all - a national map, which has no one region to
    choose by - a regional row still applies if every row for the class
    agrees on what the formation is. The layer's ``Pi`` has only ever been
    the Freetown Complex and both ``Qe`` rows are the Bullom Group, so
    naming them nationally is not a guess. Where the rows disagree, the
    source's own wording is the only honest key entry. The prose then
    comes from the first matching row, so ``describe`` without a district
    gives one region's wording for a formation the rows agree on.
    """
    rows = load_crosswalk(path)
    if district:
        region = region_of(district)
        for wanted in (region, "all"):
            for row in rows:
                if row.usgs_code == usgs_code and row.region == wanted:
                    return row
        # a class annotated for somewhere else in the country: better to
        # say nothing than to claim the Freetown gabbro is under Kono
        return None

    matching = [row for row in rows if row.usgs_code == usgs_code]
    for row in matching:
        if row.region == "all":
            return row
    agreed = {(row.formation_name, row.formation_code) for row in matching}
    return matching[0] if len(agreed) == 1 else None


def describe(usgs_code: str, district: str | None = None) -> str:
    """A sentence for a report: the formation, the rock, and what it means."""
    row = lithology_for(usgs_code, district)
    if row is None:
        return ""
    parts = [f"{row.formation_name} ({row.formation_code.replace(';', ', ')})"
             if row.formation_code else row.formation_name]
    if row.era_actual:
        parts.append(row.era_actual)
    sentence = ", ".join(parts) + f". {row.lithology}. {row.aquifer_character}."
    if row.basis == "published":
        sentence += (
            " (Formation assignment from the regional literature rather than "
            "from a source committed with this toolkit.)"
        )
    return sentence
