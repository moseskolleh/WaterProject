"""The survey's own figures: the "survey_figures" entry of
``reference.json``.
"""

from __future__ import annotations

import numpy as np

from groundwater.geo import geographic_to_utm
from groundwater.models import SiteMetadata
from groundwater.siting import assess_siting
from groundwater.ves.interpret import interpret_model

from .common import clean


# ------------------------------------------------ the survey's own figures

#: The spacings of the synthetic soundings below. Their readings are a plain
#: ramp: nothing here reads them but the pseudo-section's station order.
_SURVEY_AB2 = [1, 1.5, 2, 3, 4, 6, 8, 10, 15, 20, 25, 32, 40, 50, 65, 80, 100.0]
_E, _N = 178000.0, 1000000.0

#: Each case is a list of stations: (id, easting, northing, elevation,
#: resistivities, thicknesses). parity.mjs builds the same surveys.
SURVEY_CASES = {
    # the best point (VES 3) carries no position
    "nopos": [
        ("VES 1", _E, _N, 70.0, [320, 150, 4200], [2.5, 6]),
        ("VES 2", _E + 80, _N + 40, 72.0, [320, 160, 4200], [2.5, 5]),
        ("VES 3", None, None, None, [320, 60, 4200], [2.5, 20]),
    ],
    "noposall": [
        ("VES 1", None, None, None, [320, 150, 4200], [2.5, 6]),
        ("VES 2", None, None, None, [320, 60, 4200], [2.5, 20]),
    ],
    # 75.3 against 71.1: a tie on a five-point margin, not on three
    "margin": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 80, _N + 40, 72.0, [320, 60, 4200], [2.5, 12.5]),
    ],
    # 75.3 and 75.3, with a third point elsewhere
    "tie": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 80, _N + 40, 72.0, [320, 60, 4200], [2.5, 16]),
        ("VES 3", _E + 30, _N + 120, 71.0, [320, 400, 4200], [2.5, 4]),
    ],
    # levels missing at two of four stations
    "levels": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 100, _N, None, [320, 60, 4200], [2.5, 16]),
        ("VES 3", _E + 200, _N, None, [320, 60, 4200], [2.5, 16]),
        ("VES 4", _E + 300, _N, 64.0, [320, 60, 4200], [2.5, 16]),
    ],
    # a gap wider than ten depths of investigation between VES 2 and VES 3
    "gap": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 100, _N, 71.0, [320, 60, 4200], [2.5, 14]),
        ("VES 3", _E + 5000, _N, 64.0, [320, 60, 4200], [2.5, 12]),
    ],
    # Rokel's two pegs, 20.7 km apart and neither reaching basement
    "far": [
        ("A (1)", 708958.0, 926355.0, 71.0, [320, 60], [2.5]),
        ("B (2)", 727012.0, 916125.0, 68.0, [320, 70], [3.0]),
    ],
    "onepoint": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E, _N, 71.0, [320, 60, 4200], [2.5, 14]),
        ("VES 3", _E, _N, 72.0, [320, 60, 4200], [2.5, 12]),
    ],
    "shared": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E, _N, 71.0, [320, 60, 4200], [2.5, 14]),
        ("VES 3", _E + 100, _N + 30, 72.0, [320, 60, 4200], [2.5, 12]),
    ],
    # two soundings both called VES 1
    "sameid": [
        ("VES 1", _E, _N, 70.0, [320, 150, 4200], [2.5, 5]),
        ("VES 1", _E + 100, _N, 71.0, [320, 60, 4200], [2.5, 15]),
        ("VES 2", _E + 200, _N, 72.0, [320, 160, 4200], [2.5, 5]),
    ],
    "collinear": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 100, _N, 71.0, [320, 60, 4200], [2.5, 14]),
        ("VES 3", _E + 200, _N, 72.0, [320, 60, 4200], [2.5, 12]),
    ],
    # due north, and the same pegs as a handheld GPS reads them, a few tens
    # of centimetres east or west: both run from VES 1 northwards
    "northsouth": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E, _N + 100, 71.0, [320, 60, 4200], [2.5, 14]),
        ("VES 3", _E, _N + 200, 72.0, [320, 60, 4200], [2.5, 12]),
    ],
    "nsjitter": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 0.3, _N + 100, 71.0, [320, 60, 4200], [2.5, 14]),
        ("VES 3", _E - 0.1, _N + 200, 72.0, [320, 60, 4200], [2.5, 12]),
    ],
    # every water zone open below the depth of investigation
    "open": [
        ("VES 1", _E, _N, 70.0, [320, 60], [2.5]),
        ("VES 2", _E + 100, _N + 30, 71.0, [320, 70], [3.0]),
        ("VES 3", _E + 40, _N + 120, 72.0, [320, 65], [2.0]),
    ],
    # one of three open
    "someopen": [
        ("VES 1", _E, _N, 70.0, [320, 60], [2.5]),
        ("VES 2", _E + 100, _N + 30, 71.0, [320, 70, 4200], [3.0, 14]),
        ("VES 3", _E + 40, _N + 120, 72.0, [320, 65, 4200], [2.0, 18]),
    ],
    # a basement at 61 m under a 50 m depth of investigation
    "deepbase": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 58.5]),
        ("VES 2", _E + 100, _N + 30, 71.0, [320, 60, 4200], [2.5, 16]),
    ],
}


def _zone_straddle():
    """Three soundings either side of 12 W, each recorded in its own zone."""
    stations = []
    for k, lon in enumerate((-12.0036, -11.9964, -11.995)):
        utm = geographic_to_utm(8.9, lon)
        stations.append((f"VES {k + 1}", utm.easting, utm.northing, 30.0 + k,
                         [320, 55 + 9 * k, 4200], [2.5 + 0.4 * k, 14 + 5.5 * k]))
    return stations


def _survey(stations, array_type="schlumberger"):
    from groundwater.models import LayeredModel, VESSounding

    soundings, interps = [], []
    for sid, e, n, z, rho, h in stations:
        site = SiteMetadata(community="Kuntolo", district="Bombali",
                            easting=e, northing=n, elevation_m=z)
        ab2 = np.array(_SURVEY_AB2)
        sounding = VESSounding(
            site=site, sounding_id=sid, ab2=ab2, mn=np.full(ab2.size, 0.5),
            rho_app=100.0 + 10.0 * np.arange(ab2.size), array_type=array_type)
        model = LayeredModel(resistivities=np.array(rho, float),
                             thicknesses=np.array(h, float), sounding_id=sid,
                             fit_error_percent=0.5)
        soundings.append(sounding)
        interps.append(interpret_model(sounding, model))
    return soundings, interps


def survey_figures_reference(rokel_interps) -> dict:
    """What the survey's own figures say, case by case.

    The maps and sections are drawn by different code in each engine, but
    what they claim is decided once: which point is starred, whether two
    points tie, which figures are refused and why, the chainages, the zone
    everything is drawn in and the captions. No parity check read any of
    it, and the browser's suitability map, section and ground profile drifted
    from the package's without a failing test.
    """
    from groundwater.config import VESConfig
    from groundwater.mapping import (
        ground_profile_state,
        spacing_name,
        suitability_map_state,
        survey_zone,
        traverse_profile,
    )
    from groundwater.mapping.maps import (
        interpolated_label,
        points_enclose_an_area,
        suitability_label,
        suitability_map_note,
    )
    from groundwater.mapping.subsurface import bearing_text, spacing_note
    from groundwater.reporting.geophysical import (
        _SUBSURFACE_MAPS,
        _drawn_depth_text,
        _ground_profile_caption,
        _pseudosection_caption,
        _study_area_caption,
        _subsurface_caption,
        _subsurface_points,
        _suitability_caption,
    )
    from groundwater.siting import ranking_tie, suitability_map_points
    from groundwater.ves.plots import model_depth_m

    def refusal(fn):
        try:
            fn()
        except ValueError as exc:
            return str(exc)
        return None

    def suitability(interps, tie_points=3.0):
        cfg = VESConfig(ranking_tie_points=tie_points)
        suit = assess_siting(interps, cfg)
        tie = bool(ranking_tie(suit, within_points=cfg.ranking_tie_points))
        zone = survey_zone(interps)
        points = suitability_map_points(suit, zone)
        ranking = [s.sounding_id for s in suit]
        state = suitability_map_state(points, tie=tie, ranking=ranking)
        marked = [i.sounding_id for i in interps if i.site_easting is not None]
        return {
            "state": clean(state),
            "caption": _suitability_caption(state) if points else None,
            "note": suitability_map_note(state),
            "labels": [suitability_label(p, p.rank == 1 and not state["tie"])
                       for p in points],
            "compact_labels": [
                suitability_label(p, p.rank == 1 and not state["tie"], compact=True)
                for p in points],
            "eastings": [clean(p.easting) for p in points],
            "zone": zone,
            "study_area": _study_area_caption(
                "Kuntolo", marked, ranking[0], ranking[:2], tie),
        }

    def maps(interps):
        zone = survey_zone(interps) or 28
        out = {}
        for fn, key, _name, what in _SUBSURFACE_MAPS:
            reason = refusal(lambda fn=fn: plt_close(fn(interps, zone)))
            entry = {"reason": reason}
            if reason is None:
                points = _subsurface_points(key, interps, zone)
                surface = len(points) >= 3 and points_enclose_an_area(
                    [p.easting for p in points], [p.northing for p in points])
                entry["caption"] = _subsurface_caption(what, points)[0]
                entry["minimum"] = [p.minimum for p in points]
                if key != "protective_capacity":
                    entry["labels"] = [interpolated_label(p, surface) for p in points]
            out[key] = entry
        return out

    def traverse(interps):
        try:
            profile = traverse_profile(interps)
        except ValueError as exc:
            return {"reason": str(exc)}
        return {
            "reason": None,
            "labels": list(profile.labels),
            "chainage_m": clean(profile.chainage_m),
            "indices": list(profile.indices),
            "length_m": clean(profile.length_m),
            "bearing_deg": clean(profile.bearing_deg),
            # as a section title prints it: just west of north is 0, not 360
            "bearing_text": bearing_text(profile.bearing_deg),
            # the model each station takes, by position in the list
            "layer2_rho": [clean(interps[k].model.resistivities[1])
                           for k in profile.indices],
        }

    def ground(interps):
        levelled = [i for i in interps if i.site_easting is not None
                    and i.site_northing is not None and i.site_elevation_m is not None]
        if len(levelled) < 2:
            # the report says nothing: there is no profile to be missing
            return {"reason": None, "silent": True}
        try:
            state = ground_profile_state(interps)
        except ValueError as exc:
            return {"reason": str(exc)}
        if state["reason"]:
            return {"reason": state["reason"]}
        return {
            "reason": None,
            "caption": _ground_profile_caption(state),
            "chainage_m": clean(state["chainage_m"]),
            "open_gaps": clean(state["open_gaps"]),
            "max_gap_m": clean(state["max_gap_m"]),
        }

    cases = dict(SURVEY_CASES, zones=_zone_straddle())
    # the stations travel with the answers, so the browser builds the very
    # same surveys rather than a copy of them typed out again
    out: dict = {"cases": {}, "inputs": clean(cases), "ab2": _SURVEY_AB2}
    for name, stations in cases.items():
        soundings, interps = _survey(stations)
        entry = {
            "suitability": suitability(interps),
            "traverse": traverse(interps),
            "ground": ground(interps),
            "maps": maps(interps),
            "model_depth": [clean(model_depth_m(i.model, i.investigation_depth_m))
                            for i in interps],
            "drawn_depth": [_drawn_depth_text(i.model, i) for i in interps],
        }
        if name == "margin":
            entry["suitability_margin5"] = suitability(interps, tie_points=5.0)
        out["cases"][name] = entry
    # a Wenner survey: the spacing is a, not AB/2
    wenner, interps = _survey(SURVEY_CASES["collinear"], array_type="wenner")
    profile = traverse_profile(interps)
    spacing = spacing_name(wenner)
    out["wenner"] = {
        "spacing": spacing,
        "note": spacing_note(spacing),
        "caption": _pseudosection_caption(spacing, profile),
    }
    out["rokel_drawn_depth"] = [_drawn_depth_text(i.model, i) for i in rokel_interps]
    return out


def plt_close(fig):
    """Close a figure a map function returned rather than saved."""
    import matplotlib.pyplot as plt

    plt.close(fig)
