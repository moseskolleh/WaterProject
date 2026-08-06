"""What was priced, what was built, and what is actually payable.

A bill of quantities is an estimate until somebody signs it, and from then
on it is a contract. The gap between the two is where drilling programmes
lose money, and almost always in the same three ways.

**Work is measured that nobody authorised.** A hole priced for 45 metres is
drilled to 62 because the water was deeper, which is a perfectly good reason
- but 17 metres of drilling is not payable because it happened. It is
payable because somebody with authority agreed to it, in writing, before the
certificate. So measured quantity and authorised quantity are separate
numbers here, only the lower one is paid, and the difference is reported as
an overmeasure with the line named rather than quietly paid or quietly
dropped.

**The same work is paid twice.** An interim certificate values everything
done to date and then subtracts everything already certified. Get the
subtraction wrong and the contractor is paid twice for the same metres.
Certificates are therefore numbered, each one carries what came before it,
and a certificate that would pay less than nothing is refused rather than
issued as a negative.

**Retention is forgotten.** A share of every certificate is withheld against
defects and released later. It is not a discount and it is not the client's
money; it is the contractor's, held. Both halves are tracked, and the total
held is capped at the agreed share of the contract sum.

Everything here is append-only for the same reason the asset registry is: a
variation that can be edited after a certificate has been paid against it is
not a record of anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

__all__ = [
    "Certificate",
    "Contract",
    "ContractLine",
    "LineValuation",
    "Measurement",
    "Variation",
    "certify",
    "contract_from_estimate",
    "contract_summary",
    "value_work",
]


@dataclass(frozen=True)
class ContractLine:
    """One priced line of the signed bill of quantities."""

    code: str
    item: str
    unit: str
    quantity: float
    rate_usd: float
    stage: str = ""
    category: str = ""

    @property
    def amount_usd(self) -> float:
        return self.quantity * self.rate_usd

    def as_dict(self) -> dict:
        return {"code": self.code, "item": self.item, "unit": self.unit,
                "quantity": self.quantity, "rate_usd": self.rate_usd,
                "stage": self.stage, "category": self.category,
                "amount_usd": self.amount_usd}


@dataclass(frozen=True)
class Variation:
    """An authorised change to a contract line.

    ``quantity_delta`` is added to the contract quantity - negative to omit
    work. ``rate_usd`` replaces the rate where a variation changes it, and
    is required for a code the contract does not already carry, because
    there is nothing to price new work against otherwise.
    """

    ref: str
    date: str
    code: str
    quantity_delta: float = 0.0
    rate_usd: Optional[float] = None
    reason: str = ""
    authorised_by: str = ""
    item: str = ""
    unit: str = ""

    def as_dict(self) -> dict:
        return {"ref": self.ref, "date": self.date, "code": self.code,
                "quantity_delta": self.quantity_delta, "rate_usd": self.rate_usd,
                "reason": self.reason, "authorised_by": self.authorised_by,
                "item": self.item, "unit": self.unit}


@dataclass(frozen=True)
class Measurement:
    """Cumulative quantity of a line completed to date."""

    code: str
    quantity: float
    date: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {"code": self.code, "quantity": self.quantity,
                "date": self.date, "note": self.note}


@dataclass
class Contract:
    """The signed bill of quantities and the terms that value it."""

    ref: str
    lines: list[ContractLine]
    contractor: str = ""
    client: str = ""
    date: str = ""
    #: Withheld from each certificate against defects. It is the
    #: contractor's money, held, not a discount.
    retention_percent: float = 10.0
    #: The most that may be held at any time, as a share of the contract sum.
    retention_cap_percent: float = 5.0
    #: Paid before work starts and recovered pro rata from certificates.
    advance_percent: float = 0.0

    @property
    def sum_usd(self) -> float:
        return sum(line.amount_usd for line in self.lines)

    @property
    def advance_usd(self) -> float:
        return self.sum_usd * self.advance_percent / 100.0

    def line(self, code: str) -> Optional[ContractLine]:
        for entry in self.lines:
            if entry.code == code:
                return entry
        return None

    def as_dict(self) -> dict:
        return {"ref": self.ref, "contractor": self.contractor,
                "client": self.client, "date": self.date,
                "retention_percent": self.retention_percent,
                "retention_cap_percent": self.retention_cap_percent,
                "advance_percent": self.advance_percent,
                "sum_usd": self.sum_usd,
                "lines": [line.as_dict() for line in self.lines]}


def contract_from_estimate(estimate, ref: str, **terms) -> Contract:
    """Freeze a cost estimate into a contract.

    The estimate keeps moving as the design changes; a contract does not.
    This takes the copy that gets signed, so a later change to the design
    cannot silently change what a certificate is measured against.
    """
    lines = [
        ContractLine(code=item.code, item=item.item, unit=item.unit,
                     quantity=float(item.quantity),
                     rate_usd=float(item.unit_cost_usd),
                     stage=item.stage, category=item.category)
        for item in estimate.items
    ]
    return Contract(ref=ref, lines=lines, **terms)


# ---------------------------------------------------------------------------
# Valuing the work
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LineValuation:
    """One line of a valuation: priced, authorised, measured, payable."""

    code: str
    item: str
    unit: str
    rate_usd: float
    contract_quantity: float
    variation_quantity: float
    measured_quantity: float
    in_contract: bool
    variation_refs: tuple[str, ...] = ()

    @property
    def authorised_quantity(self) -> float:
        return self.contract_quantity + self.variation_quantity

    @property
    def payable_quantity(self) -> float:
        """Never more than was authorised, and never less than nothing."""
        return max(min(self.measured_quantity, self.authorised_quantity), 0.0)

    @property
    def overmeasure_quantity(self) -> float:
        """Measured beyond what anybody authorised. Reported, not paid."""
        return max(self.measured_quantity - self.authorised_quantity, 0.0)

    @property
    def contract_amount_usd(self) -> float:
        return self.contract_quantity * self.rate_usd

    @property
    def authorised_amount_usd(self) -> float:
        return self.authorised_quantity * self.rate_usd

    @property
    def payable_amount_usd(self) -> float:
        return self.payable_quantity * self.rate_usd

    @property
    def overmeasure_amount_usd(self) -> float:
        return self.overmeasure_quantity * self.rate_usd

    @property
    def percent_complete(self) -> Optional[float]:
        if not self.authorised_quantity:
            return None
        return self.payable_quantity / self.authorised_quantity * 100.0

    def as_dict(self) -> dict:
        return {
            "code": self.code, "item": self.item, "unit": self.unit,
            "rate_usd": self.rate_usd,
            "contract_quantity": self.contract_quantity,
            "variation_quantity": self.variation_quantity,
            "authorised_quantity": self.authorised_quantity,
            "measured_quantity": self.measured_quantity,
            "payable_quantity": self.payable_quantity,
            "overmeasure_quantity": self.overmeasure_quantity,
            "contract_amount_usd": self.contract_amount_usd,
            "authorised_amount_usd": self.authorised_amount_usd,
            "payable_amount_usd": self.payable_amount_usd,
            "overmeasure_amount_usd": self.overmeasure_amount_usd,
            "percent_complete": self.percent_complete,
            "in_contract": self.in_contract,
            "variation_refs": list(self.variation_refs),
        }


def value_work(contract: Contract, measurements: Iterable[Measurement],
               variations: Iterable[Variation] = ()) -> tuple[
                   list[LineValuation], list[str]]:
    """Value every line, and return what could not be valued cleanly.

    The second element is a list of problems written for the person who has
    to fix them. They are never fatal: a certificate with a problem on it is
    still worth issuing, as long as the problem is printed on its face.
    """
    problems: list[str] = []
    varied: dict[str, dict] = {}
    for variation in variations:
        entry = varied.setdefault(variation.code, {
            "delta": 0.0, "rate": None, "refs": [], "unsigned_refs": [],
            "item": "", "unit": ""})
        entry["item"] = entry["item"] or variation.item
        entry["unit"] = entry["unit"] or variation.unit
        # An unsigned variation is not valued at all. Counting its quantity
        # and then printing a warning beside the total pays for work nobody
        # instructed: the warning is read once, the certificate is banked.
        if not variation.authorised_by:
            entry["unsigned_refs"].append(variation.ref)
            problems.append(
                f"Variation {variation.ref} on {variation.code} names nobody "
                "who authorised it. An unsigned variation is a request, not "
                "an instruction, so its quantity is left out of this "
                "valuation until somebody signs it.")
            continue
        entry["delta"] += float(variation.quantity_delta)
        entry["refs"].append(variation.ref)
        if variation.rate_usd is not None:
            entry["rate"] = float(variation.rate_usd)

    measured: dict[str, float] = {}
    for record in measurements:
        if float(record.quantity) < 0:
            problems.append(
                f"{record.code} is measured as a negative quantity "
                f"({record.quantity:g}); it is treated as nothing measured.")
            continue
        # cumulative-to-date, so the latest figure for a code wins rather
        # than accumulating a running total twice
        measured[record.code] = float(record.quantity)

    valuations: list[LineValuation] = []
    seen: set[str] = set()
    for line in contract.lines:
        change = varied.get(line.code, {})
        seen.add(line.code)
        valuations.append(LineValuation(
            code=line.code, item=line.item, unit=line.unit,
            rate_usd=change.get("rate") if change.get("rate") is not None
            else line.rate_usd,
            contract_quantity=line.quantity,
            variation_quantity=change.get("delta", 0.0),
            measured_quantity=measured.get(line.code, 0.0),
            in_contract=True,
            variation_refs=tuple(change.get("refs", ())),
        ))

    # work added entirely by variation, and work measured against nothing
    for code in list(varied) + [c for c in measured if c not in varied]:
        if code in seen:
            continue
        seen.add(code)
        change = varied.get(code)
        if change is None:
            problems.append(
                f"{code} has been measured but is neither in the contract nor "
                "in any variation, so there is no rate to pay it at and "
                "nothing authorising it. It is valued at zero.")
            valuations.append(LineValuation(
                code=code, item="(not in the contract)", unit="", rate_usd=0.0,
                contract_quantity=0.0, variation_quantity=0.0,
                measured_quantity=measured.get(code, 0.0), in_contract=False))
            continue
        if not change["refs"]:
            problems.append(
                f"Variation {', '.join(change['unsigned_refs'])} adds {code}, "
                "which the contract does not carry, and nobody has signed it. "
                "Nothing is authorised against this line, so nothing on it is "
                "payable.")
        elif change.get("rate") is None:
            problems.append(
                f"Variation {', '.join(change['refs'])} adds {code}, which the "
                "contract does not price, without giving a rate. It is valued "
                "at zero until one is agreed.")
        valuations.append(LineValuation(
            code=code, item=change.get("item") or "(added by variation)",
            unit=change.get("unit", ""), rate_usd=change.get("rate") or 0.0,
            contract_quantity=0.0, variation_quantity=change.get("delta", 0.0),
            measured_quantity=measured.get(code, 0.0), in_contract=False,
            variation_refs=tuple(change.get("refs", ()))))

    for valuation in valuations:
        if valuation.overmeasure_quantity > 0:
            problems.append(
                f"{valuation.code} is measured at "
                f"{valuation.measured_quantity:g} {valuation.unit} against "
                f"{valuation.authorised_quantity:g} authorised. The extra "
                f"{valuation.overmeasure_quantity:g} is not payable until a "
                "variation authorises it - the work may well be justified, "
                "but that is a decision somebody signs, not a measurement.")
    return valuations, problems


# ---------------------------------------------------------------------------
# The certificate
# ---------------------------------------------------------------------------

@dataclass
class Certificate:
    """An interim payment certificate: what is due now, and how it got there."""

    number: int
    date: str
    contract: Contract
    lines: list[LineValuation]
    previously_certified_usd: float
    problems: list[str] = field(default_factory=list)
    prepared_by: str = ""

    @property
    def gross_usd(self) -> float:
        """Value of authorised work done to date, before anything is taken off."""
        return sum(line.payable_amount_usd for line in self.lines)

    @property
    def contract_sum_usd(self) -> float:
        return self.contract.sum_usd

    @property
    def variation_usd(self) -> float:
        return sum(line.authorised_amount_usd - line.contract_amount_usd
                   for line in self.lines)

    @property
    def revised_sum_usd(self) -> float:
        """The contract sum as varied - what the job is now expected to cost."""
        return self.contract_sum_usd + self.variation_usd

    @property
    def percent_complete(self) -> Optional[float]:
        return (self.gross_usd / self.revised_sum_usd * 100.0
                if self.revised_sum_usd else None)

    @property
    def retention_usd(self) -> float:
        """Held to date, capped at the agreed share of the contract sum."""
        held = self.gross_usd * self.contract.retention_percent / 100.0
        cap = self.revised_sum_usd * self.contract.retention_cap_percent / 100.0
        return min(held, cap)

    @property
    def advance_recovered_usd(self) -> float:
        """Recovered in proportion to the work done, never beyond what was paid."""
        advance = self.contract.advance_usd
        if not advance or not self.revised_sum_usd:
            return 0.0
        return min(advance * self.gross_usd / self.revised_sum_usd, advance)

    @property
    def net_certified_usd(self) -> float:
        """Everything due across the whole job so far, after deductions."""
        return self.gross_usd - self.retention_usd - self.advance_recovered_usd

    @property
    def due_now_usd(self) -> float:
        """This certificate only. Never negative: see :attr:`overpaid_usd`."""
        return max(self.net_certified_usd - self.previously_certified_usd, 0.0)

    @property
    def overpaid_usd(self) -> float:
        """How far past the value of the work previous certificates already went.

        Reported rather than netted off, because a negative payment is not a
        payment - it is a credit note somebody has to raise and agree, and
        burying it inside a certificate hides that it happened.
        """
        return max(self.previously_certified_usd - self.net_certified_usd, 0.0)

    @property
    def overmeasure_usd(self) -> float:
        return sum(line.overmeasure_amount_usd for line in self.lines)

    @property
    def summary(self) -> str:
        text = (f"Certificate {self.number}: "
                f"${self.due_now_usd:,.0f} due on work valued at "
                f"${self.gross_usd:,.0f}")
        if self.percent_complete is not None:
            text += f" ({self.percent_complete:.0f}% of the revised sum)"
        if self.overpaid_usd:
            text += (f". Previous certificates exceed the value of the work by "
                     f"${self.overpaid_usd:,.0f}, so nothing is due")
        return text + "."

    def as_dict(self) -> dict:
        return {
            "number": self.number, "date": self.date,
            "contract_ref": self.contract.ref,
            "contract_sum_usd": self.contract_sum_usd,
            "variation_usd": self.variation_usd,
            "revised_sum_usd": self.revised_sum_usd,
            "gross_usd": self.gross_usd,
            "percent_complete": self.percent_complete,
            "retention_usd": self.retention_usd,
            "advance_recovered_usd": self.advance_recovered_usd,
            "net_certified_usd": self.net_certified_usd,
            "previously_certified_usd": self.previously_certified_usd,
            "due_now_usd": self.due_now_usd,
            "overpaid_usd": self.overpaid_usd,
            "overmeasure_usd": self.overmeasure_usd,
            "summary": self.summary,
            "problems": list(self.problems),
            "lines": [line.as_dict() for line in self.lines],
        }


def certify(contract: Contract, measurements: Iterable[Measurement], *,
            number: int, date: str,
            variations: Iterable[Variation] = (),
            previously_certified_usd: float = 0.0,
            prepared_by: str = "") -> Certificate:
    """Value the work and produce the interim payment certificate."""
    lines, problems = value_work(contract, measurements, variations)
    if previously_certified_usd < 0:
        problems.append(
            "Previously certified is negative, which cannot be right; it is "
            "treated as nothing certified so far.")
        previously_certified_usd = 0.0
    if number > 1 and previously_certified_usd == 0:
        problems.append(
            f"This is certificate {number} but nothing is recorded as "
            "previously certified. If earlier certificates were paid, the "
            "contractor will be paid for that work twice.")
    return Certificate(
        number=number, date=date, contract=contract, lines=lines,
        previously_certified_usd=float(previously_certified_usd),
        problems=problems, prepared_by=prepared_by,
    )


def contract_summary(contract: Contract, certificate: Certificate) -> list[
        tuple[str, str]]:
    """Field-value rows for the head of a certificate."""
    rows = [("Contract", contract.ref)]
    if contract.contractor:
        rows.append(("Contractor", contract.contractor))
    if contract.client:
        rows.append(("Client", contract.client))
    rows += [
        ("Contract sum", f"${certificate.contract_sum_usd:,.0f}"),
        # sign outside the currency: "$+1,360" reads as a typo
        ("Variations", ("+" if certificate.variation_usd >= 0 else "-")
         + f"${abs(certificate.variation_usd):,.0f}"),
        ("Revised sum", f"${certificate.revised_sum_usd:,.0f}"),
        ("Work valued to date", f"${certificate.gross_usd:,.0f}"),
    ]
    if certificate.percent_complete is not None:
        rows.append(("Progress", f"{certificate.percent_complete:.0f}%"))
    rows += [
        (f"Less retention ({contract.retention_percent:g}%)",
         f"-${certificate.retention_usd:,.0f}"),
    ]
    if contract.advance_percent:
        rows.append((f"Less advance recovery ({contract.advance_percent:g}% "
                     "advance)", f"-${certificate.advance_recovered_usd:,.0f}"))
    rows += [
        ("Net certified to date", f"${certificate.net_certified_usd:,.0f}"),
        ("Less previously certified",
         f"-${certificate.previously_certified_usd:,.0f}"),
        ("Due on this certificate", f"${certificate.due_now_usd:,.0f}"),
    ]
    return rows
