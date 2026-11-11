"""Procurement, planned against actual: the "procurement" entry of
``reference.json``.
"""

from __future__ import annotations

from .common import clean


def fill_procurement(out: dict) -> None:
    """Fill "procurement": certificates over contracts built here.

    It fills ``out`` in place, where build() calls it: build.py says why."""
    # Procurement: planned against actual, and what that makes payable.
    from groundwater.procurement import (
        Contract as _Contract,
    )
    from groundwater.procurement import (
        ContractLine as _ContractLine,
    )
    from groundwater.procurement import (
        Measurement as _Measurement,
    )
    from groundwater.procurement import (
        Variation as _Variation,
    )
    from groundwater.procurement import certify as _certify
    from groundwater.procurement import contract_summary as _contract_summary

    def _proc_contract(**terms):
        return _Contract(
            ref="WSD/2024/017", contractor="WiNGiN", client="District Council",
            date="2024-02-01",
            lines=[
                _ContractLine("MOB", "Mobilisation", "sum", 1, 3000.0),
                _ContractLine("DRL-OB", "Drilling, overburden", "m", 20, 45.0),
                _ContractLine("DRL-RK", "Drilling, rock", "m", 25, 80.0),
                _ContractLine("CAS", "uPVC casing", "m", 45, 22.0),
            ],
            **terms)

    _proc_cases = {
        "clean": (_proc_contract(), [_Measurement("MOB", 1.0)], [], 1, 0.0),
        "overmeasured": (_proc_contract(),
                         [_Measurement("MOB", 1.0), _Measurement("DRL-RK", 42.0)],
                         [], 1, 0.0),
        "varied": (_proc_contract(),
                   [_Measurement("MOB", 1.0), _Measurement("DRL-RK", 42.0)],
                   [_Variation("VO-1", "2024-03-04", "DRL-RK", 17.0, None,
                               "deeper water", "M. Kolleh")], 2, 1500.0),
        "unsigned": (_proc_contract(), [_Measurement("GRAVEL", 12.0)],
                     [_Variation("VO-2", "2024-03-04", "CAS", 5.0)], 1, 0.0),
        "new_item": (_proc_contract(), [_Measurement("GRAVEL", 12.0)],
                     [_Variation("VO-3", "2024-03-04", "GRAVEL", 12.0, None,
                                 "gravel pack", "M. K.", "Gravel pack", "m3")],
                     1, 0.0),
        "advance": (_proc_contract(advance_percent=20.0, retention_percent=5.0),
                    [_Measurement("MOB", 1.0), _Measurement("DRL-OB", 20.0),
                     _Measurement("DRL-RK", 25.0), _Measurement("CAS", 45.0)],
                    [], 1, 0.0),
        "overpaid": (_proc_contract(retention_percent=0.0),
                     [_Measurement("MOB", 1.0)], [], 2, 5000.0),
        "negatives": (_proc_contract(), [_Measurement("CAS", -10.0)], [], 3, -5.0),
        # a rate-only variation is a variation; an omission beyond the line
        # authorises nothing; a duplicated code is valued once and named
        "repriced": (_proc_contract(),
                     [_Measurement("MOB", 1.0), _Measurement("CAS", 45.0)],
                     [_Variation("VO-4", "2024-03-04", "CAS", 0.0, 26.0,
                                 "supplier price", "Engineer")], 1, 0.0),
        "over_omitted": (_proc_contract(), [_Measurement("CAS", 10.0)],
                         [_Variation("VO-5", "2024-03-04", "CAS", -60.0, None,
                                     "redesign", "Engineer")], 1, 0.0),
        "duplicate": (_Contract(ref="DUP", lines=[
                          _ContractLine("CAS", "uPVC casing 6 in", "m", 10, 22.0),
                          _ContractLine("CAS", "uPVC casing 4 in", "m", 10, 22.0)]),
                      [_Measurement("CAS", 10.0)], [], 1, 0.0),
    }
    out["procurement"] = {}
    for _label, (_ct, _ms, _vs, _no, _prev) in _proc_cases.items():
        _cert = _certify(_ct, _ms, number=_no, date="2024-04-01",
                         variations=_vs, previously_certified_usd=_prev)
        out["procurement"][_label] = clean({
            "certificate": _cert.as_dict(),
            "summary_rows": _contract_summary(_ct, _cert),
        })
