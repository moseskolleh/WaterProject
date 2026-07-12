"""Schlumberger segment handling and optional curve splicing.

At MN segment changes the same AB/2 is read with the old and new MN,
and the two readings differ slightly (electrode geometry and lateral
heterogeneity). Both readings are kept in the raw data. For plotting
and for inversion with the ideal gradient forward model the segments
can be spliced into one smooth curve: each segment after the first is
scaled by the ratio of overlapping readings (multiplicative shift,
standard practice), then overlapping points are merged by geometric
mean.
"""

from __future__ import annotations

import numpy as np

from ..models import VESSounding

__all__ = ["splice_segments"]


def splice_segments(
    sounding: VESSounding, mode: str = "merge"
) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """Combine a segmented Schlumberger sounding into a single curve.

    Parameters
    ----------
    sounding:
        The sounding with possible duplicate AB/2 readings at segment
        changes.
    mode:
        "merge" (default) keeps every segment at its measured level and
        merges duplicate AB/2 readings by geometric mean. This honours
        the absolute values of the deep branch that drive the aquifer
        interpretation and matches how IPI2Win treats the data.
        "first" applies multiplicative shifts so overlaps coincide,
        anchored to the first (smallest MN) segment; "last" anchors to
        the deepest segment. Shifted modes give a visually smooth
        curve but redistribute any overlap jump onto the other
        segments, so they are offered for plotting rather than as the
        inversion default.

    Returns
    -------
    ab2, rho:
        Strictly increasing AB/2 and the combined apparent resistivity.
    shifts:
        The multiplicative shift applied to each segment (all 1.0 for
        "merge"; values far from 1 in the shifted modes indicate noisy
        overlaps).
    """
    segments = sounding.segments()
    if len(segments) <= 1:
        order = np.argsort(sounding.ab2, kind="stable")
        return sounding.ab2[order], sounding.rho_app[order], [1.0]

    if mode == "merge":
        shifts = [1.0] * len(segments)
    else:
        shifts = [1.0]
        # cumulative shift so each segment matches the (already shifted) previous
        for i in range(1, len(segments)):
            prev_idx = segments[i - 1]
            cur_idx = segments[i]
            prev_ab2 = sounding.ab2[prev_idx]
            cur_ab2 = sounding.ab2[cur_idx]
            common = np.intersect1d(prev_ab2, cur_ab2)
            if len(common) == 0:
                shifts.append(shifts[-1])
                continue
            ratios = []
            for value in common:
                r_prev = sounding.rho_app[prev_idx][prev_ab2 == value]
                r_cur = sounding.rho_app[cur_idx][cur_ab2 == value]
                ratios.append(np.mean(r_prev) / np.mean(r_cur))
            # geometric mean of overlap ratios
            shifts.append(shifts[i - 1] * float(np.exp(np.mean(np.log(ratios)))))
        if mode == "last":
            shifts = [s / shifts[-1] for s in shifts]

    ab2_all, rho_all = [], []
    for shift, idx in zip(shifts, segments):
        ab2_all.extend(sounding.ab2[idx])
        rho_all.extend(sounding.rho_app[idx] * shift)
    ab2_all = np.asarray(ab2_all)
    rho_all = np.asarray(rho_all)

    # merge duplicates by geometric mean
    unique = np.unique(ab2_all)
    rho_merged = np.array(
        [np.exp(np.mean(np.log(rho_all[ab2_all == u]))) for u in unique]
    )
    return unique, rho_merged, shifts
