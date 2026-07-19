"""Dar-Zarrouk parameters and protective-capacity classification."""

import numpy as np

from groundwater.models import LayeredModel
from groundwater.ves import interpret_model


def test_dar_zarrouk_values_and_protective_capacity():
    # topsoil 200 ohm-m / 5 m; weathered zone 50 ohm-m / 15 m; basement 3000
    model = LayeredModel(
        resistivities=np.array([200.0, 50.0, 3000.0]),
        thicknesses=np.array([5.0, 15.0]),
        sounding_id="VES-1",
    )
    interp = interpret_model(None, model)
    # S = 5/200 + 15/50 = 0.325 S ; T = 5*200 + 15*50 = 1750 ohm m2
    assert abs(interp.longitudinal_conductance_s - 0.325) < 1e-6
    assert abs(interp.transverse_resistance_t - 1750.0) < 1e-6
    assert interp.protective_capacity == "moderate"  # 0.2 <= S < 0.7
    assert "Dar-Zarrouk" in interp.narrative


def test_protective_capacity_bands():
    # a thick conductive clay cap gives a high longitudinal conductance
    model = LayeredModel(
        resistivities=np.array([10.0, 3000.0]),
        thicknesses=np.array([20.0]),  # S = 20/10 = 2.0 -> "good"
        sounding_id="VES-2",
    )
    interp = interpret_model(None, model)
    assert abs(interp.longitudinal_conductance_s - 2.0) < 1e-6
    assert interp.protective_capacity == "good"

    # thin resistive cover -> poor protection
    model2 = LayeredModel(
        resistivities=np.array([1000.0, 3000.0]),
        thicknesses=np.array([2.0]),  # S = 0.002 -> "poor"
        sounding_id="VES-3",
    )
    assert interpret_model(None, model2).protective_capacity == "poor"
