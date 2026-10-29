"""Guideline and standard values for drinking water parameters.

The bundled table (``data/who_guidelines.csv``) carries WHO Guidelines
for Drinking-water Quality values (4th edition with addenda) split
into health based and acceptability values, plus a Sierra Leone
standard column. Where a confirmed national value is not to hand the
national column mirrors the WHO/regional figure; confirm the values
against the current Sierra Leone Standards Bureau specification and
edit the CSV (or pass a custom file) - no code change is needed.

Range values such as pH are written ``6.5-8.5`` and evaluated as an
allowed interval.
"""

from __future__ import annotations

import csv
import functools
import io
import re
from dataclasses import dataclass
from pathlib import Path

from .._resources import bundled_text
from ..units import _normalise as normalise_unit_text
from ..units import comparable, convert, nitrogen_species, parse_unit

_RANGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$")


@dataclass
class Limit:
    """A guideline limit: either a maximum or an allowed range."""

    maximum: float | None = None
    minimum: float | None = None

    @classmethod
    def parse(cls, text: str) -> Limit | None:
        text = (text or "").strip()
        if not text:
            return None
        match = _RANGE_RE.match(text)
        if match:
            return cls(minimum=float(match.group(1)), maximum=float(match.group(2)))
        try:
            return cls(maximum=float(text))
        except ValueError:
            return None

    def exceeded_by(self, value: float) -> bool:
        if self.minimum is not None and value < self.minimum:
            return True
        if self.maximum is not None and value > self.maximum:  # noqa: SIM103 - mirrors the minimum
            return True
        return False

    def __str__(self) -> str:
        if self.minimum is not None:
            return f"{self.minimum:g}-{self.maximum:g}"
        if self.maximum is not None:
            return f"{self.maximum:g}"
        return ""


@dataclass
class StandardEntry:
    parameter: str
    unit: str
    who_health: Limit | None
    who_aesthetic: Limit | None
    sl_standard: Limit | None
    category: str
    note: str
    #: Where the national value came from. ``"provisional"`` means it has not
    #: been checked against the Sierra Leone Standards Bureau specification -
    #: it is a WHO figure carried across, or one adopted from regional
    #: practice. Set it to the issuing specification once confirmed.
    sl_source: str = ""

    @property
    def sl_provisional(self) -> bool:
        """Whether the national value is unconfirmed against the SLSB spec."""
        return self.sl_standard is not None and self.sl_source == "provisional"


#: Said wherever a national verdict is shown, while any national value is
#: still provisional. A compliance failure against an unconfirmed limit is a
#: prompt to check the specification, not a finding to put in front of a
#: regulator.
PROVISIONAL_NATIONAL_NOTE = (
    "The national column in the standards table is provisional: its values "
    "are WHO guideline figures carried across, or limits adopted from "
    "regional practice, and have not been confirmed against the Sierra Leone "
    "Standards Bureau drinking water specification. Confirm the figures "
    "before treating a national exceedance as a compliance finding."
)


def provisional_national_parameters(
    table: dict[str, StandardEntry] | None = None,
) -> list[str]:
    """Parameters whose national limit is still unconfirmed."""
    entries = (table or load_standards()).values()
    return sorted(e.parameter for e in entries if e.sl_provisional)


_ALIASES = {
    "ec": "electrical conductivity",
    "conductivity": "electrical conductivity",
    "total dissolved solids": "tds",
    "hardness": "total hardness",
    "nitrate": "nitrate (as no3)",
    "no3": "nitrate (as no3)",
    "nitrite": "nitrite (as no2)",
    "no2": "nitrite (as no2)",
    "ammonia": "ammonia (as n)",
    "ammonium": "ammonia (as n)",
    "nh3": "ammonia (as n)",
    "nh4": "ammonia (as n)",
    "chromium": "chromium (total)",
    "cr": "chromium (total)",
    "faecal coliforms": "e. coli",
    "fecal coliforms": "e. coli",
    "e.coli": "e. coli",
    "escherichia coli": "e. coli",
    "coliforms": "total coliforms",
    "sulphate": "sulfate",
    "so4": "sulfate",
    "aluminum": "aluminium",
    # the spellings a Sierra Leone certificate actually carries
    "total alkalinity": "alkalinity",
    "alkalinity (as caco3)": "alkalinity",
    "alkalinity as caco3": "alkalinity",
    "total alkalinity as caco3": "alkalinity",
    "total iron": "iron",
    "iron (total)": "iron",
    "total dissolved solid": "tds",
    "dissolved solids": "tds",
    "specific conductance": "electrical conductivity",
    "ph value": "ph",
    "color": "colour",
    "true colour": "colour",
    "apparent colour": "colour",
    "thermotolerant coliforms": "e. coli",
    "thermotolerant coliform": "e. coli",
    "faecal coliform": "e. coli",
    "fecal coliform": "e. coli",
    "total coliform": "total coliforms",
    "residual chlorine": "free chlorine",
    "chlorine residual": "free chlorine",
    "free residual chlorine": "free chlorine",
    "nitrate-n": "nitrate (as n)",
    "nitrate n": "nitrate (as n)",
    "nitrate as n": "nitrate (as n)",
    "nitrate nitrogen": "nitrate (as n)",
    "no3-n": "nitrate (as n)",
    "nitrite-n": "nitrite (as n)",
    "nitrite n": "nitrite (as n)",
    "nitrite as n": "nitrite (as n)",
    "nitrite nitrogen": "nitrite (as n)",
    "no2-n": "nitrite (as n)",
    "orthophosphate": "phosphate",
    "phosphate (as po4)": "phosphate",
    "po4": "phosphate",
    "silica (as sio2)": "silica",
    "sio2": "silica",
    "tss": "total suspended solids",
    "suspended solids": "total suspended solids",
    "co3": "carbonate",
    "hco3": "bicarbonate",
}

# "Iron (Fe)", "Turbidity (NTU)", "Conductivity (EC)", "Temperature (°C)":
# a trailing bracket that is a symbol or a unit, not a basis ("(as NO3)")
# and not the table's own qualifier ("(total)")
_TRAILING_QUALIFIER_RE = re.compile(r"\s*\((?!\s*as\s)[^)]*\)\s*$")

#: A trailing bracket after a name, and what it holds.
_TRAILING_BRACKET_RE = re.compile(r"^(?P<base>.+?)\s*\((?P<inside>[^()]*)\)$")

#: Nitrogen named as the basis anywhere in that bracket: "Nitrate (NO3-N)",
#: "(N)", "(NO3 as N)", "(as NO3-N)", "(nitrogen)", and a unit with its
#: basis, "(mg/L as N)", "(mg N/L)" or "(mgN/L)". A bracket that held
#: anything but an ion and N was stripped like a symbol, so "Nitrate (mg/L
#: as N)" was held to the 50 mg/L guideline for nitrate as the ion, where 20
#: mg/L as N is 88.5 mg/L as nitrate. Its word boundaries, and the next
#: one's, are ASCII ones, as the browser's are.
_NITROGEN_NAMED_RE = re.compile(
    r"\b(?:(?:no3|no2|nh4|nh3)\s*-{0,2}\s*)?(?:n|nitrogen)\b|[muµμ]gn/", re.ASCII)

#: An ion's formula in that bracket, which must be the name's own.
_NITROGEN_ION_RE = re.compile(r"\b(no3|no2|nh4|nh3)", re.ASCII)

#: An en dash, an em dash and the minus sign, which a name or a unit writes
#: for a hyphen: "Nitrate (NO3-N)" typed with a minus sign.
_DASHES_RE = re.compile("[–—−]")

#: The table key each name takes when it is reported as nitrogen, and the
#: ion a qualifier may name for it. A qualifier naming another ion ("Nitrite
#: (NO3-N)") contradicts the name, and is left to resolve to nothing.
_AS_NITROGEN_KEYS = {
    "nitrate": ("nitrate (as n)", ("no3",)),
    "nitrite": ("nitrite (as n)", ("no2",)),
    "ammonia": ("ammonia (as n)", ("nh3", "nh4")),
    "ammonium": ("ammonia (as n)", ("nh3", "nh4")),
}


def normalise_parameter(name: str) -> str:
    """The standards-table key a certificate's parameter name refers to.

    Every laboratory writes the same determinand differently ("Iron (Fe)",
    "Total iron", "Nitrate (NO3)", "pH value"). The assessment is
    fail-closed - an unknown name makes the whole sample "not proven safe" -
    so name resolution is load-bearing, and it used to know only the
    template's own spellings.
    """
    key = _DASHES_RE.sub("-", re.sub(r"\s+", " ", str(name or "").strip().lower()))
    if key in _ALIASES:
        return _ALIASES[key]
    bracket = _TRAILING_BRACKET_RE.match(key)
    if (bracket and bracket.group("base") in _AS_NITROGEN_KEYS
            and _NITROGEN_NAMED_RE.search(bracket.group("inside"))):
        # reported as nitrogen: the table's entry for nitrogen, unless the
        # bracket names another ion's ("Nitrite (NO3-N)"), which contradicts
        # the name and is left to resolve to nothing
        as_n, ions = _AS_NITROGEN_KEYS[bracket.group("base")]
        named = _NITROGEN_ION_RE.findall(bracket.group("inside"))
        return as_n if all(ion in ions for ion in named) else key
    stripped = _TRAILING_QUALIFIER_RE.sub("", key)
    if stripped != key:
        # "chromium (total)" strips to "chromium", which the aliases map
        # straight back; "iron (fe)" strips to "iron", a table key
        return _ALIASES.get(stripped, stripped)
    return key


#: Faecal-oral pathogens a laboratory may name on a certificate: the bacteria,
#: viruses and protozoa the faecal indicator E. coli stands for. WHO sets no
#: guideline value for any of them, because drinking water must carry none
#: and the indicator is the routine check. They are recognised by name, not
#: by unit: a count in CFU is as likely to be a heterotrophic plate count,
#: which has no health significance, and reading every CFU count as a
#: pathogen would turn that into a health failure.
_FAECAL_PATHOGEN_RE = re.compile(
    r"\b(salmonella|s\.? ?typhi|typhoid|shigella|vibrio cholerae|v\.? ?cholerae"
    r"|cholera|campylobacter|yersinia|e\.? ?coli o157|cryptosporidium|giardia"
    r"|entamoeba histolytica|cyclospora|hepatitis [ae]\b|rotavirus|norovirus"
    r"|enterovirus|adenovirus|astrovirus)"
)


def faecal_pathogen(name: str) -> str:
    """The faecal pathogen a parameter name refers to, or ``""``.

    "Salmonella spp.", "Vibrio cholerae O1" and "Cryptosporidium oocysts"
    all name one; "E. coli" is the indicator and has its own table entry,
    and "Heterotrophic plate count" names no organism at all.
    """
    match = _FAECAL_PATHOGEN_RE.search(re.sub(r"\s+", " ", str(name or "").lower()))
    return match.group(1) if match else ""


#: "(as NO3)", and a unit with its basis, "(mg/L as NO3)"
_PARAMETER_BASIS_RE = re.compile(r"\((?:[^()]*\s)?as\s+([^()]+?)\s*\)")


def _parameter_basis(parameter: str) -> str:
    """The chemical basis a parameter name states: "Nitrate (as NO3)" -> "no3"."""
    text = _DASHES_RE.sub("-", str(parameter or "").lower())
    match = _PARAMETER_BASIS_RE.search(text)
    if not match:
        return ""
    basis = match.group(1).replace(" ", "")
    # "as NO3-N" is nitrogen, as units.py reads a unit's basis
    return "n" if re.fullmatch(r"(?:no3|no2|nh4|nh3)-{0,2}n|nitrogen", basis) else basis


def _written_basis(parameter: str) -> str:
    """The basis a laboratory's name for a determinand states.

    What a bracket states after "as", or nitrogen for a name that resolves to
    an entry for nitrogen ("Nitrate-N", "Nitrate (NO3-N)", "Nitrate (mg N/L)").
    Read from "as" alone, "Nitrate-N" stated no basis, so in "mg/L as NO3" it
    was converted onto nitrogen and passed at 44 mg/L, about four times the
    guideline if the name is right.
    """
    return _parameter_basis(parameter) or (
        "n" if normalise_parameter(parameter) in AS_NITROGEN else "")


#: The ions whose nitrogen each entry may be reported as: "Nitrite" in
#: "mg/L as NO3-N" names one determinand and another's nitrogen.
_NITROGEN_IONS = {
    "nitrate (as no3)": ("no3",), "nitrate (as n)": ("no3",),
    "nitrite (as no2)": ("no2",), "nitrite (as n)": ("no2",),
    "ammonia (as n)": ("nh3", "nh4"),
}


#: Molar masses, g/mol, to three decimals: the figures the ionic balance and
#: the hazard index already used, and calcium carbonate's 100.087, on which
#: the corrosivity indices' 2.497 from calcium to CaCO3 rests.
MOLAR_MASS = {
    "N": 14.007, "NO3": 62.004, "NO2": 46.005, "Ca": 40.078, "Mg": 24.305,
    "CaCO3": 100.087, "HCO3": 61.017, "CO3": 60.009,
}

#: The basis an entry's values are written on, where its name does not say:
#: calcium is reported as the element, so "mg/L as Ca" is its own scale.
_NATIVE_BASIS = {"calcium": "ca", "magnesium": "mg", "bicarbonate": "hco3",
                 "carbonate": "co3"}

#: What puts a value stated on one chemical basis onto the basis its entry
#: is written on, and that basis as a remark names it. Each is a ratio of
#: molar masses, so it is a conversion rather than an assumption: 10 mg/L as
#: N is 10 x 62.004 / 14.007 = 44.27 mg/L as NO3, and 50 mg/L of calcium as
#: CaCO3 is 50 x 40.078 / 100.087 = 20.02 mg/L of calcium. A bicarbonate as
#: CaCO3 carries two equivalents per mole of CaCO3. Calcium and magnesium
#: as CaCO3 used to be taken at face value, 2.5 and 4.1 times the element,
#: and a balanced analysis was flagged as an unreliable one. Nothing is put
#: onto the entries for nitrogen: every name that reaches one states
#: nitrogen, so a unit as the ion contradicts it and is refused.
_BASIS_FACTORS: dict[tuple[str, str], tuple[float, str]] = {
    ("nitrate (as no3)", "n"): (MOLAR_MASS["NO3"] / MOLAR_MASS["N"], "NO3"),
    ("nitrite (as no2)", "n"): (MOLAR_MASS["NO2"] / MOLAR_MASS["N"], "NO2"),
    ("calcium", "caco3"): (MOLAR_MASS["Ca"] / MOLAR_MASS["CaCO3"], "Ca"),
    ("magnesium", "caco3"): (MOLAR_MASS["Mg"] / MOLAR_MASS["CaCO3"], "Mg"),
    ("bicarbonate", "caco3"): (2 * MOLAR_MASS["HCO3"] / MOLAR_MASS["CaCO3"], "HCO3"),
    ("carbonate", "caco3"): (MOLAR_MASS["CO3"] / MOLAR_MASS["CaCO3"], "CO3"),
}

#: The entries a value reported as nitrogen is graded on, and the ion's
#: entry, factor and formula that put it on the ion's scale. The row is
#: graded against the as-N guideline; the charge balance, the hazard index
#: and the water quality index are written for the ion, and read it there.
AS_NITROGEN = {
    "nitrate (as n)": ("nitrate (as no3)", MOLAR_MASS["NO3"] / MOLAR_MASS["N"], "NO3"),
    "nitrite (as n)": ("nitrite (as no2)", MOLAR_MASS["NO2"] / MOLAR_MASS["N"], "NO2"),
}


def index_key(key: str) -> str:
    """The key the indices read a result under: the ion's, for nitrogen."""
    return AS_NITROGEN[key][0] if key in AS_NITROGEN else key


def basis_conversion(reported_unit: str, entry: StandardEntry) -> tuple[float, str] | None:
    """``(factor, basis)``: what puts the unit's basis on the entry's.

    The factor a value in ``reported_unit`` is multiplied by and the basis
    it is put on, for the remark and the flag of a row
    :func:`to_standard_unit` converted; ``None`` where no factor is known.
    """
    source = parse_unit(str(reported_unit or ""))
    if source is None or not source.basis:
        return None
    return _BASIS_FACTORS.get((normalise_parameter(entry.parameter), source.basis))


def to_standard_unit(
    value: float, reported_unit: str, entry: StandardEntry,
    parameter: str | None = None,
) -> tuple[float | None, str]:
    """Put a reported value on the scale the standards table uses.

    Returns ``(converted, reason)``. ``converted`` is ``None`` when the value
    must not be used against this parameter's limits - an unreadable unit, or
    one that measures something else. That is never the same as zero, and a
    caller must drop the value rather than fall back to the raw number.

    ``reason`` is ``""`` on a clean conversion, ``"unit_assumed"`` when the
    laboratory reported no usable unit and the guideline's own was assumed,
    ``"unit_basis_converted"`` when the unit states a chemical basis the
    entry is not written on and a fixed factor puts it there
    (:data:`_BASIS_FACTORS`), ``"unit_basis_assumed"`` when one side names a
    chemical basis the other does not and nothing converts it, or an
    ``INDETERMINATE_REASONS`` code on refusal.

    ``parameter`` is the name as the laboratory wrote it. A basis that name
    states and the unit contradicts is refused, whichever of them is the
    entry's own: "Nitrate (as NO3)" in "mg/L as N", a name that resolves to
    nitrogen ("Nitrate-N", "Nitrate (NO3-N)") in "mg/L as NO3", and "Calcium
    (mg/L as CaCO3)" in "mg/L as Ca". So is a unit naming another ion's
    nitrogen, "Nitrite" in "mg/L as NO3-N". "Nitrate" in "mg/L as N" is
    converted. Without ``parameter`` the entry's own name speaks for the
    sheet, which refuses both.
    """
    reported = str(reported_unit or "").strip()
    guideline = str(entry.unit or "").strip()

    # "-", "n/a" and friends normalise away to nothing: they are how a sheet
    # writes "no unit here", so they take the no-unit path rather than the
    # unreadable one.
    if reported and not normalise_unit_text(reported):
        reported = ""

    if not reported:
        # No unit on the sheet. The guideline's own unit is the only reading
        # under which the number means anything; the assumption is recorded
        # rather than hidden.
        return float(value), "unit_assumed"
    if not guideline:
        # The standards table itself names no unit, so there is no scale to
        # convert onto and nothing to disagree about.
        return float(value), ""
    if normalise_unit_text(reported) == normalise_unit_text(guideline):
        # Written the same way: same scale, whether or not the unit module has
        # ever heard of the unit. Keeps a newly added guideline unit from
        # making every sample indeterminate.
        return float(value), ""

    source = parse_unit(reported)
    target = parse_unit(guideline)

    if target is not None and target.dimension == "ph":
        # pH is the one absolute scale here with no rival: there is no such
        # thing as pH in another unit, so a sheet carrying "mg/L" beside a pH
        # of 7.2 is a template artefact, not a different measurement.
        if source is None or source.dimension != "ph":
            return float(value), "unit_assumed"
        return float(value), ""

    if source is None or target is None:
        return None, "unit_unreadable"
    if not comparable(source, target):
        return None, "unit_mismatch"
    converted = convert(value, reported, guideline)
    if converted is None:  # pragma: no cover - comparable() already checked
        return None, "unit_mismatch"
    if source.basis and not target.basis:
        # The unit names a chemical reference the guideline's unit does not.
        # The parameter name often carries it instead, so look there before
        # deciding: "Nitrate (as NO3)" reported in "mg/L as N" is a different
        # number by a factor of 4.4, and grading it at face value passed a
        # sample at 44 mg/L as NO3 that the guideline puts over its limit.
        key = normalise_parameter(entry.parameter)
        species = nitrogen_species(reported)
        if species and species not in _NITROGEN_IONS.get(key, (species,)):
            # "Nitrite" in "mg/L as NO3-N": another ion's nitrogen
            return None, "unit_basis_conflict"
        written = _written_basis(entry.parameter if parameter is None else parameter)
        if written and written != source.basis:
            # the name and the unit state different bases, whichever of them
            # is the entry's own: "Nitrate-N" in "mg/L as NO3", and "Calcium
            # (mg/L as CaCO3)" in "mg/L as Ca"
            return None, "unit_basis_conflict"
        native = _parameter_basis(entry.parameter) or _NATIVE_BASIS.get(key, "")
        if source.basis == native:
            return converted, ""
        factor = basis_conversion(reported, entry)
        if factor is not None:
            return converted * factor[0], "unit_basis_converted"
        if native:
            return None, "unit_basis_conflict"
        # Nothing states the guideline's basis, so the reading is taken but
        # it is worth an analyst's eye: an 'as CaCO3' figure is about 2.5
        # times the same concentration expressed as the element.
        return converted, "unit_basis_assumed"
    if target.basis and not source.basis:
        return converted, "unit_basis_assumed"
    return converted, ""


def canonical_values(
    sample, table: dict[str, StandardEntry] | None = None
) -> dict[str, float]:
    """Every measured result in the sample, on the standards table's scale.

    Keyed by normalised parameter name. A result whose unit cannot be
    reconciled with its guideline is *left out* rather than passed through
    raw: the aggregate indices built on these numbers - the water quality
    index, the hazard index, the ionic balance, the corrosivity indices -
    all assume mg/L, and a sample reported in ug/L quietly produced a hazard
    index a thousand times too high and an "unsuitable for drinking" rating
    for clean water.
    """
    table = table if table is not None else load_standards()
    values: dict[str, float] = {}
    as_nitrogen: dict[str, float] = {}
    for result in getattr(sample, "results", []):
        if result.value is None:
            continue
        key = normalise_parameter(result.parameter)
        entry = table.get(key)
        if entry is None:
            # No guideline entry, so no declared scale to convert onto. The
            # value is carried as written; nothing downstream has a limit for
            # it either.
            values[key] = float(result.value)
            continue
        converted, _ = to_standard_unit(float(result.value), result.unit, entry,
                                        result.parameter)
        if converted is None:
            continue
        if key in AS_NITROGEN:
            # Nitrate and nitrite reported as nitrogen go on the ion's scale,
            # under the ion's key: the meq factor, the reference dose and the
            # water quality index's exclusion are written for the ion. Kept
            # out, nitrate as N left a balanced analysis 10 percent short, the
            # hazard index without its nitrate, and the index led by nitrite.
            ion, factor, _ = AS_NITROGEN[key]
            as_nitrogen[ion] = converted * factor
            continue
        values[key] = converted
    for ion, value in as_nitrogen.items():
        # a certificate that reports both forms is not counted twice
        values.setdefault(ion, value)
    return values


@functools.lru_cache(maxsize=1)
def _bundled_rows() -> tuple[dict, ...]:
    """The bundled CSV, parsed once per process.

    assess_sample used to open and parse the file about twenty-six times
    per sample (once per ion the ionic balance and the corrosivity indices
    asked for); the portfolio and the Streamlit pages assess every borehole
    on each rerun, and the Pyodide build pays for file IO dearly. Callers
    still get fresh StandardEntry objects, so a table they edit stays theirs.
    """
    return tuple(csv.DictReader(io.StringIO(bundled_text("who_guidelines.csv"))))


def load_standards(path: str | Path | None = None) -> dict[str, StandardEntry]:
    """Load the standards table keyed by normalised parameter name."""
    if path is None:
        rows = _bundled_rows()
    else:
        rows = list(csv.DictReader(io.StringIO(bundled_text("who_guidelines.csv", path))))
    table: dict[str, StandardEntry] = {}
    for row in rows:
        entry = StandardEntry(
            parameter=row["parameter"],
            unit=row["unit"],
            who_health=Limit.parse(row.get("who_health_gv", "")),
            who_aesthetic=Limit.parse(row.get("who_aesthetic", "")),
            sl_standard=Limit.parse(row.get("sl_standard", "")),
            category=row.get("category", ""),
            note=row.get("note", ""),
            sl_source=(row.get("sl_source") or "").strip(),
        )
        table[normalise_parameter(entry.parameter)] = entry
    return table
