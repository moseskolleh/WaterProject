"""The shared figure context."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from groundwater.plotting import figure_context


def test_a_plot_that_fails_part_way_does_not_leave_its_figure_open():
    """pyplot keeps every figure until something closes it, and the web app
    runs for days: a plot function that raised after creating its figure
    used to leave it held. Figures the caller already had stay open."""
    kept = plt.figure()
    before = set(plt.get_fignums())
    try:
        with pytest.raises(ValueError, match="never filled in"), figure_context():
            plt.subplots()
            plt.figure()
            raise ValueError("a column the field sheet never filled in")
        assert set(plt.get_fignums()) == before
    finally:
        plt.close(kept)


def test_a_plot_that_succeeds_hands_its_figure_back_open():
    """Closing is for the failure path only: the caller saves or shows it."""
    with figure_context():
        fig, _ = plt.subplots()
    try:
        assert fig.number in plt.get_fignums()
    finally:
        plt.close(fig)
