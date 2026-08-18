"""The interim payment certificate.

The document a contractor is paid against, so everything that reduces the
payment appears on its face with its own line: what was authorised, what was
measured, what the difference is, and every deduction between the value of
the work and the figure at the bottom. A certificate that shows only the
bottom figure is one nobody can check, and one nobody can check is one
nobody can dispute.

Where the valuation found a problem it is printed before the money rather
than after it. The certificate is still issued - work has been done and the
contractor has to be paid for it - but the person signing sees first what
the figure below rests on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pathlib import Path

from ..config import Config
from ..models import SiteMetadata
from ..procurement import Certificate, Contract, contract_summary
from .context import add_area_section
from .docx_utils import ReportBuilder

__all__ = ["PaymentCertificateInputs", "build_payment_certificate"]


@dataclass
class PaymentCertificateInputs:
    contract: Contract
    certificate: Certificate
    prepared_by: str = ""
    prepared_role: str = "Supervising engineer"
    readiness: Any = None
    #: The works being paid for are at a place. Supply the site and a
    #: figures directory and the certificate carries a map of it.
    site: SiteMetadata | None = None
    figures_dir: Path = Path(".")


def build_payment_certificate(inputs: PaymentCertificateInputs,
                              out_path, config: Config | None = None):
    contract = inputs.contract
    certificate = inputs.certificate
    rb = ReportBuilder(config.style if config else None,
                       title=f"Interim Payment Certificate {certificate.number}")

    rb.cover(
        [f"Interim Payment Certificate No. {certificate.number}"],
        [contract.ref, contract.contractor or ""],
        [("Date", certificate.date),
         ("Due on this certificate", f"${certificate.due_now_usd:,.0f}")],
    )
    rb.provisional_stamp(inputs.readiness)

    if certificate.problems:
        rb.heading("Before the figures")
        rb.paragraph(
            "The valuation below could not be made cleanly. Each item here "
            "reduces or holds back money, and the certificate is issued with "
            "them showing rather than resolved silently.", bold=True)
        rb.bullets(certificate.problems)

    if inputs.site is not None:
        add_area_section(rb, inputs.site, Path(inputs.figures_dir),
                         config.style if config else None,
                         heading="Where the works are")

    rb.heading("Summary")
    rb.table([[label, value] for label, value in
              contract_summary(contract, certificate)],
             header=["", ""], col_widths_cm=[8.0, 7.0])
    if certificate.overpaid_usd:
        rb.paragraph(
            f"Certificates already issued exceed the value of the work by "
            f"${certificate.overpaid_usd:,.0f}. Nothing is due on this "
            "certificate. Recovering the difference is a credit note to be "
            "agreed, not a negative payment.", bold=True)

    rb.heading("Measurement")
    rb.table(
        [[line.code, line.item, line.unit,
          f"{line.contract_quantity:g}",
          f"{line.variation_quantity:+g}" if line.variation_quantity else "-",
          f"{line.measured_quantity:g}",
          f"{line.payable_quantity:g}",
          f"{line.rate_usd:,.2f}",
          f"{line.payable_amount_usd:,.0f}"]
         for line in certificate.lines],
        header=["Code", "Item", "Unit", "Contract", "Varied", "Measured",
                "Payable", "Rate (USD)", "Amount (USD)"],
        caption="Work measured to date and what is payable on it",
        col_widths_cm=[1.6, 4.2, 1.2, 1.6, 1.4, 1.6, 1.5, 1.6, 1.8],
        font_size_pt=8.5,
    )

    overmeasured = [line for line in certificate.lines
                    if line.overmeasure_quantity > 0]
    if overmeasured:
        rb.heading("Measured beyond what was authorised")
        rb.paragraph(
            "The quantities below have been done but not authorised, so they "
            "are not certified here. That is not a judgement on whether the "
            "work was necessary - it usually was - but on whether anybody has "
            "yet signed for it. A variation order authorising them makes them "
            "payable on the next certificate.", align="justify")
        rb.table(
            [[line.code, line.item,
              f"{line.authorised_quantity:g} {line.unit}",
              f"{line.measured_quantity:g} {line.unit}",
              f"{line.overmeasure_quantity:g} {line.unit}",
              f"{line.overmeasure_amount_usd:,.0f}"]
             for line in overmeasured],
            header=["Code", "Item", "Authorised", "Measured", "Excess",
                    "Value withheld (USD)"],
            col_widths_cm=[1.8, 4.6, 2.4, 2.4, 2.0, 2.4],
        )
        rb.paragraph(
            f"Total value measured but not certified: "
            f"${certificate.overmeasure_usd:,.0f}.", bold=True)

    varied = [line for line in certificate.lines if line.variation_refs]
    if varied:
        rb.heading("Variations included")
        rb.table(
            [[", ".join(line.variation_refs), line.code, line.item,
              f"{line.variation_quantity:+g} {line.unit}",
              f"{line.authorised_amount_usd - line.contract_amount_usd:+,.0f}"]
             for line in varied],
            header=["Reference", "Code", "Item", "Quantity", "Value (USD)"],
            col_widths_cm=[2.4, 1.8, 5.6, 2.6, 3.2],
        )

    rb.heading("Certification")
    rb.paragraph(
        f"The work described above has been measured and valued at "
        f"${certificate.gross_usd:,.0f}. After retention and previous "
        f"certificates, ${certificate.due_now_usd:,.0f} is due to "
        f"{contract.contractor or 'the contractor'} on this certificate.")
    rb.signature_block(
        name=inputs.prepared_by, role=inputs.prepared_role,
        organisation=(config.style.organisation if config else ""),
    )
    return rb.save(out_path)
