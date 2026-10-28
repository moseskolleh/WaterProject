"""The rising main material, chosen from the water (PLAN.md step 7.2).

A galvanised iron rising main and its rods corrode quickly in aggressive
water, and a corroded main is a leading cause of a handpump failing early
(``quality/corrosivity.py``; RWSN, Stop the Rot). The design used to say
nothing about the rising main, and the bill of quantities priced the one
the handpump line carries (PMP1, for example an India Mark II with its rods
and rising main) whatever the water. This module reads the water quality assessment
and says what the design specifies for the rising main and how often it is
inspected, and why.

No second classification is made here. The water is aggressive when either
of the toolkit's existing rules says so:

* the corrosivity classification of ``quality/corrosivity.py`` (its
  ``is_aggressive``): a Ryznar index above 7.0, a Langelier index below
  -0.5 or an aggressive index below 10;
* the pH rule of the handpump corrosion check and the post-construction
  checklist (``supervision/field_checks.py``, after RWSN's Stop the Rot):
  a pH below 6.5.

Where it is, the design specifies the rules' ``aggressive_rising_main_material``
in place of their ``rising_main_material`` and the shorter of the two
inspection intervals; the bill of quantities prices the difference
(``costing/model.py``). Where no sample is loaded, or the sample cannot give
the indices and its pH is not below 6.5, the design keeps the standard
material, says that the choice rests on no chemistry, and still inspects at
the shorter interval: the
inspection is what would find the corrosion a sample was not there to
predict. The materials and both intervals are settings
(``data/defaults.json``), and the intervals are a choice made here, not a
standard (QUESTIONS.md item 12).

:func:`rising_main_choice` has a twin of the same name in camel case in
gwt-core.js, and parity holds them to one another.
"""

from __future__ import annotations

from ..config import DesignRules
from ..quality.corrosivity import _ph_text, _value, assess_corrosivity
from ..registry import trim_field
from ..text import phrase

__all__ = ["CHEMISTRY_STATES", "PH_CORROSIVE_BELOW", "rising_main_choice"]

#: What the water says about the rising main: ``aggressive`` (by the indices,
#: by the pH, or both), ``not_aggressive``, ``incomplete`` (a sample whose
#: indices could not be computed and whose pH is not below the limit) and
#: ``none`` (no water quality analysis loaded).
CHEMISTRY_STATES = ("aggressive", "not_aggressive", "incomplete", "none")

#: The pH under which galvanised iron rising mains and rods corrode quickly:
#: the handpump corrosion check's rule (supervision/field_checks.py, RWSN
#: Stop the Rot), which the post-construction checklist applies too.
PH_CORROSIVE_BELOW = 6.5


def _same_material(a: str, b: str) -> bool:
    """Whether two material names are the same material, ignoring case and
    the blanks at their ends ("Stainless steel" is "stainless steel"), as
    sameMaterial in gwt-core.js takes them."""
    return trim_field(a).lower() == trim_field(b).lower()


def _sample_name(sample) -> str:
    """How the sample is named after "The water sample": by its identifier
    and its date, as the laboratory sheet writes them."""
    ident = trim_field(getattr(sample, "sample_id", "") or "")
    when = trim_field(getattr(sample, "sample_date", "") or "")
    if ident and when:
        return phrase("rising_main.sample_named", id=ident, date=when)
    if ident:
        return phrase("rising_main.sample_undated", id=ident)
    if when:
        return phrase("rising_main.sample_unnamed", date=when)
    return phrase("rising_main.sample_anonymous")


def _signed(value: float) -> str:
    """The Langelier index with its sign, to two decimals ("+0.12", "-2.74");
    nought, negative or not, is "+0.00", as signedIndex writes it."""
    return f"-{-value:.2f}" if value < 0 else f"+{abs(value):.2f}"


def rising_main_choice(quality=None, rules: DesignRules | None = None) -> dict:
    """What the design specifies for the rising main, from the water.

    ``quality`` is the project's water quality assessment
    (:class:`~groundwater.quality.WaterQualityAssessment`, whose corrosivity
    is read as it stands), a bare
    :class:`~groundwater.models.WaterQualitySample` (assessed for corrosivity
    here), or ``None`` when no analysis is loaded. ``rules`` are the design
    rules, which name the materials and the two inspection intervals.

    The result says what the design specifies (``material``), what the
    handpump line of the bill includes (``standard``), whether the design
    replaced it (``upgraded``, which the bill of quantities prices), what the
    water says (``chemistry``, one of :data:`CHEMISTRY_STATES`), the sample
    and the values it was read from, the rising main's inspection interval
    in months (``inspection_months``, the named value the service rounds of
    step 7.3 read), and the ``statement`` that says all of it.
    """
    rules = rules or DesignRules()
    standard = rules.rising_main_material
    resistant = rules.aggressive_rising_main_material
    usual = rules.rising_main_inspection_months
    shorter = rules.aggressive_rising_main_inspection_months

    sample = None
    corrosivity = None
    if quality is not None:
        if hasattr(quality, "sample") and hasattr(quality, "corrosivity"):
            sample = quality.sample
            corrosivity = quality.corrosivity
            if corrosivity is None and sample is not None:
                corrosivity = assess_corrosivity(sample)
        else:
            sample = quality
            corrosivity = assess_corrosivity(sample)

    out: dict = {
        "material": standard, "standard": standard, "upgraded": False,
        "chemistry": "none", "sample": "", "ph": None, "lsi": None, "rsi": None,
        "aggressive_index": None, "classification": "", "by_indices": False,
        "by_ph": False, "inspection_months": shorter, "statement": "",
    }
    sentences: list[str] = []
    if sample is None or corrosivity is None:
        sentences.append(phrase("rising_main.no_sample"))
        sentences.append(phrase("rising_main.kept_unknown", standard=standard,
                                months=shorter))
        out["statement"] = " ".join(sentences)
        return out

    name = _sample_name(sample)
    # the pH the corrosivity indices were computed from, read the same way
    ph = _value(sample, "ph")
    lsi, rsi, ai = corrosivity.lsi, corrosivity.rsi, corrosivity.aggressive_index
    indices: dict | None = None
    if ph is not None and lsi is not None and rsi is not None and ai is not None:
        # the class as a sentence carries it ("rated strongly corrosive")
        rated = corrosivity.classification[:1].lower() + corrosivity.classification[1:]
        indices = {"rsi": rsi, "lsi": _signed(lsi), "ai": ai, "classification": rated}
    indexed = indices is not None
    by_indices = bool(indexed and corrosivity.is_aggressive)
    by_ph = ph is not None and ph < PH_CORROSIVE_BELOW
    out.update({
        "sample": name, "ph": ph, "lsi": lsi, "rsi": rsi, "aggressive_index": ai,
        "classification": corrosivity.classification if indexed else "",
        "by_indices": by_indices, "by_ph": by_ph,
    })

    if indices is not None and by_indices:
        sentences.append(phrase("rising_main.aggressive", sample=name, **indices))
    elif ph is not None and by_ph:
        sentences.append(phrase("rising_main.ph_low", sample=name, ph=_ph_text(ph)))
        sentences.append(phrase("rising_main.ph_low_indices", **indices) if indices is not None
                         else phrase("rising_main.ph_low_no_indices"))
    elif ph is not None and indices is not None:
        sentences.append(phrase("rising_main.not_aggressive", sample=name,
                                ph=_ph_text(ph), **indices))
    else:
        sentences.append(phrase("rising_main.no_indices", sample=name))

    if by_indices or by_ph:
        out["chemistry"] = "aggressive"
        out["inspection_months"] = shorter
        if _same_material(resistant, standard):
            sentences.append(phrase("rising_main.same_material", material=standard,
                                    months=shorter))
        else:
            out["material"] = resistant
            out["upgraded"] = True
            sentences.append(phrase("rising_main.specified", material=resistant,
                                    standard=standard, months=shorter, usual=usual))
            sentences.append(phrase("rising_main.alternative"))
    elif indexed:
        out["chemistry"] = "not_aggressive"
        out["inspection_months"] = usual
        sentences.append(phrase("rising_main.kept", standard=standard, months=usual))
    else:
        out["chemistry"] = "incomplete"
        sentences.append(phrase("rising_main.kept_unknown", standard=standard,
                                months=shorter))
    out["statement"] = " ".join(sentences)
    return out
