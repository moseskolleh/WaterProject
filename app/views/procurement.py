"""Procurement: the contract, what was measured and the payment certificate."""

from __future__ import annotations

import streamlit as st

from groundwater.procurement import (
    certify,
    Contract,
    contract_from_estimate,
    contract_summary,
    ContractLine,
    Measurement,
    Variation,
)
from groundwater.reporting.procurement import (
    build_payment_certificate,
    PaymentCertificateInputs,
)

from shared import (
    app_config,
    offer_download,
    report_gate,
    workdir,
    _working,
)

def render() -> None:
    st.header("Procurement: planned against actual")
    st.caption(
        "A bill of quantities is an estimate until somebody signs it, and a "
        "contract afterwards. This page tracks what was measured against what "
        "was authorised, records the variation orders that move the line, and "
        "produces the interim payment certificate. Work that was done but "
        "nobody authorised is shown and withheld - not because it was "
        "unnecessary, but because paying for it is a decision somebody signs."
    )

    _estimate = st.session_state.get("cost_estimate")
    _contract_lines = st.session_state.get("proc_contract_lines")
    if _contract_lines is None and _estimate is not None:
        st.info(
            "The cost estimate from the Costing page is not a contract until "
            "it is awarded. Freeze it here and the certificate is measured "
            "against the frozen copy, so a later change to the design cannot "
            "move what was signed."
        )
    a1, a2, a3 = st.columns([2, 1, 1])
    _ref = a1.text_input("Contract reference", key="proc_ref",
                         placeholder="WSD/2024/017")
    _retention = a2.number_input("Retention (%)", min_value=0.0, max_value=25.0,
                                 value=10.0, step=0.5, key="proc_retention")
    _advance = a3.number_input("Advance (%)", min_value=0.0, max_value=50.0,
                               value=0.0, step=5.0, key="proc_advance")
    if _estimate is not None and st.button("Award this estimate as the contract",
                                           key="proc_award"):
        _frozen = contract_from_estimate(
            _estimate, ref=_ref or "(unreferenced)",
            contractor=st.session_state.get("meta_contractor", ""),
            client=st.session_state.get("meta_client", ""),
            retention_percent=_retention, advance_percent=_advance)
        st.session_state["proc_contract_lines"] = [
            line.as_dict() for line in _frozen.lines]
        st.success(
            f"Contract frozen at ${_frozen.sum_usd:,.0f} across "
            f"{len(_frozen.lines)} lines, at the contract price (the estimate's "
            "cost rates plus overheads and margin).")
        _contract_lines = st.session_state["proc_contract_lines"]

    if not _contract_lines:
        st.info(
            "No contract yet. Build a cost estimate on the Costing & BoQ page, "
            "then award it here."
        )
    else:
        _contract = Contract(
            ref=_ref or "(unreferenced)",
            contractor=st.session_state.get("meta_contractor", ""),
            client=st.session_state.get("meta_client", ""),
            lines=[ContractLine(
                code=row["code"], item=row["item"], unit=row["unit"],
                quantity=float(row["quantity"]),
                rate_usd=float(row["rate_usd"]),
                stage=row.get("stage", ""), category=row.get("category", ""))
                for row in _contract_lines],
            retention_percent=_retention, advance_percent=_advance)
        st.metric("Contract sum", f"${_contract.sum_usd:,.0f}")

        st.subheader("Measured to date")
        st.caption(
            "Cumulative quantities, not increments: this is everything done "
            "so far on each line. The certificate works out what is new."
        )
        _measured_rows = st.data_editor(
            st.session_state.get("proc_measured") or [
                {"Code": line.code, "Item": line.item, "Unit": line.unit,
                 "Contract": line.quantity, "Measured to date": 0.0}
                for line in _contract.lines],
            key="proc_measure_editor", hide_index=True, width="stretch",
            disabled=["Code", "Item", "Unit", "Contract"],
        )
        st.session_state["proc_measured"] = (
            _measured_rows.to_dict("records")
            if hasattr(_measured_rows, "to_dict") else list(_measured_rows))

        st.subheader("Variation orders")
        st.caption(
            "A variation is what makes extra work payable. It needs a reason "
            "and a name: an unsigned variation is a request, not an "
            "instruction."
        )
        _variation_rows = st.data_editor(
            st.session_state.get("proc_variations") or [
                {"Ref": "", "Date": "", "Code": "", "Quantity change": 0.0,
                 "New rate (USD)": None, "Reason": "", "Authorised by": ""}],
            key="proc_variation_editor", hide_index=True, width="stretch",
            num_rows="dynamic",
        )
        st.session_state["proc_variations"] = (
            _variation_rows.to_dict("records")
            if hasattr(_variation_rows, "to_dict") else list(_variation_rows))

        st.subheader("Certificate")
        c1, c2, c3 = st.columns(3)
        _number = c1.number_input("Certificate number", min_value=1, step=1,
                                  value=1, key="proc_number")
        _cert_date = c2.text_input("Date", key="proc_date",
                                   placeholder="2024-04-01")
        _previous = c3.number_input(
            "Previously certified (USD)", min_value=0.0, step=100.0, value=0.0,
            key="proc_previous",
            help="Everything net-certified on earlier certificates. Leave it "
                 "at zero on a later certificate and the contractor is paid "
                 "for that work twice.")

        _measurements = [
            Measurement(code=str(row.get("Code") or ""),
                        quantity=float(row.get("Measured to date") or 0.0))
            for row in st.session_state["proc_measured"]
            if str(row.get("Code") or "").strip()
        ]
        _variations = [
            Variation(
                ref=str(row.get("Ref") or ""), date=str(row.get("Date") or ""),
                code=str(row.get("Code") or ""),
                quantity_delta=float(row.get("Quantity change") or 0.0),
                rate_usd=(float(row["New rate (USD)"])
                          if row.get("New rate (USD)") not in (None, "") else None),
                reason=str(row.get("Reason") or ""),
                authorised_by=str(row.get("Authorised by") or ""))
            for row in st.session_state["proc_variations"]
            if str(row.get("Code") or "").strip()
        ]
        _certificate = certify(
            _contract, _measurements, number=int(_number),
            date=_cert_date or "(undated)", variations=_variations,
            previously_certified_usd=float(_previous))

        for _problem in _certificate.problems:
            st.warning(_problem)
        st.success(_certificate.summary)
        st.dataframe(
            [{"": label, " ": value}
             for label, value in contract_summary(_contract, _certificate)],
            hide_index=True, width="stretch",
        )
        if _certificate.overmeasure_usd:
            st.error(
                f"${_certificate.overmeasure_usd:,.0f} of work has been "
                "measured but not authorised, so it is not certified here. "
                "Record a variation order against those lines and it becomes "
                "payable on the next certificate."
            )
        st.dataframe(
            [{"Code": line.code, "Item": line.item, "Unit": line.unit,
              "Contract": line.contract_quantity,
              "Varied": line.variation_quantity,
              "Authorised": line.authorised_quantity,
              "Measured": line.measured_quantity,
              "Payable": line.payable_quantity,
              "Rate": round(line.rate_usd, 2),
              "Amount (USD)": round(line.payable_amount_usd),
              "% done": round(line.percent_complete)
              if line.percent_complete is not None else None}
             for line in _certificate.lines],
            hide_index=True, width="stretch",
        )
        if st.button("Build interim payment certificate (.docx)",
                     key="proc_build"):
            with _working("Building the certificate..."):
                _path = build_payment_certificate(
                    PaymentCertificateInputs(
                        contract=_contract, certificate=_certificate,
                        prepared_by=st.session_state.get("meta_supervisor", ""),
                        readiness=report_gate("procurement")),
                    workdir() / f"IPC_{int(_number)}.docx", app_config())
            offer_download(_path,
                           f"Interim payment certificate {int(_number)}")
