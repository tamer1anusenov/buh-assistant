"""Conservative half-year income-tax assessment from reviewed evidence."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Rule(Record):
    rule_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    regime: Literal["simplified_declaration"] = "simplified_declaration"
    tax: Literal["individual_income_tax"] = "individual_income_tax"
    region: str = Field(min_length=1)
    rate: Decimal = Field(ge=0, le=1)
    effective_from: date
    effective_to: date
    adilet_url: str
    article: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    checked_on: date | None = None
    reviewed_by: str | None = None
    status: Literal["draft", "verified", "stale"] = "draft"
    rounding_places: int | None = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def check_source(self) -> Rule:
        url = urlparse(self.adilet_url)
        if url.scheme != "https" or url.hostname not in {"adilet.zan.kz", "old.adilet.zan.kz"}:
            raise ValueError("Rule source must be an HTTPS Adilet URL")
        if self.effective_to < self.effective_from:
            raise ValueError("Rule effective dates are reversed")
        if self.status == "verified" and (not self.checked_on or not self.reviewed_by or not self.reviewed_by.strip()):
            raise ValueError("Verified rules require a human reviewer and review date")
        if self.status == "verified" and self.rounding_places is None:
            raise ValueError("Verified rules require a reviewed rounding policy")
        return self


class EvidenceRow(Record):
    transaction_id: str = Field(min_length=1)
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page: int = Field(ge=1)
    passage: str = Field(min_length=1)
    transaction_date: date | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str = ""
    counterparty: str = ""
    purpose: str = ""
    operation: Literal["BUSINESS_INCOME", "REFUND", "OWN_TRANSFER", "LOAN", "EXPENSE", "UNKNOWN", "NON_INCOME"]
    reviewed: bool = False
    duplicate_of: str | None = None


class PeriodProfile(Record):
    taxpayer_type: Literal["IE"] = "IE"
    regime: Literal["simplified_declaration"] = "simplified_declaration"
    region: str = Field(min_length=1)
    year: Literal[2026] = 2026
    half: Literal[1, 2]
    eligibility_confirmed: bool = False
    eligibility_evidence: str | None = None
    has_employees: bool | None = None
    income_recognition_confirmed: bool = False
    complete_income_confirmed: bool = False
    payments_made: Decimal | None = Field(default=None, ge=0)

    @property
    def dates(self) -> tuple[date, date]:
        return (date(self.year, 1, 1), date(self.year, 6, 30)) if self.half == 1 else (date(self.year, 7, 1), date(self.year, 12, 31))


class PeriodResult(Record):
    status: Literal["NEEDS_MORE_DATA", "CALCULATED"]
    missing_information: list[str] = Field(default_factory=list)
    rule_id: str | None = None
    rule_version: int | None = None
    taxable_income: Decimal | None = None
    assessed_tax: Decimal | None = None
    balance_payable: Decimal | None = None
    overpayment: Decimal | None = None
    formula: str | None = None
    period: str | None = None
    legal_url: str | None = None
    included_transaction_ids: list[str] = Field(default_factory=list)


def calculate_period(rows: list[EvidenceRow], profile: PeriodProfile, rule: Rule | None) -> PeriodResult:
    """Apply a reviewed income-only rule; refunds and payroll need further rules."""
    missing: list[str] = []
    start, end = profile.dates
    if rule is None or rule.status != "verified":
        missing.append("reviewed_rule")
    elif rule.regime != profile.regime or rule.region != profile.region or not (rule.effective_from <= start <= end <= rule.effective_to):
        missing.append("applicable_rule")
    if not profile.eligibility_confirmed or not profile.eligibility_evidence:
        missing.append("eligibility_evidence")
    if profile.has_employees is not False:
        missing.append("employee_obligations_review")
    if not rows:
        missing.append("no_transactions")
    for row in rows:
        if row.transaction_date is None:
            missing.append(f"date:{row.transaction_id}")
    active = [row for row in rows if row.transaction_date is None or start <= row.transaction_date <= end]
    fingerprints: set[tuple] = set()
    seen: set[str] = set()
    for row in active:
        if row.transaction_id in seen or row.duplicate_of:
            missing.append(f"duplicate:{row.transaction_id}")
        fingerprint = (row.transaction_date, row.amount, row.currency, row.counterparty, row.purpose, row.passage)
        if fingerprint in fingerprints:
            missing.append(f"duplicate:{row.transaction_id}")
        fingerprints.add(fingerprint)
        seen.add(row.transaction_id)
        if row.amount is None:
            missing.append(f"amount:{row.transaction_id}")
        if not row.reviewed or row.operation in {"UNKNOWN", "REFUND"}:
            missing.append(f"review:{row.transaction_id}")
        if row.currency != "KZT":
            missing.append(f"currency:{row.transaction_id}")
    if not profile.income_recognition_confirmed:
        missing.append("income_recognition")
    if not profile.complete_income_confirmed:
        missing.append("complete_period_income")
    if profile.payments_made is None:
        missing.append("payments_made")
    if missing:
        return PeriodResult(status="NEEDS_MORE_DATA", missing_information=list(dict.fromkeys(missing)))
    assert rule is not None and rule.rounding_places is not None
    included = [row for row in active if row.operation == "BUSINESS_INCOME"]
    income = sum((row.amount for row in included), Decimal("0"))
    tax = (income * rule.rate).quantize(Decimal(1).scaleb(-rule.rounding_places), rounding=ROUND_HALF_UP)
    balance = tax - profile.payments_made if not missing else None
    return PeriodResult(
        status="NEEDS_MORE_DATA" if missing else "CALCULATED",
        missing_information=missing, rule_id=rule.rule_id, rule_version=rule.version,
        taxable_income=income, assessed_tax=tax if profile.complete_income_confirmed else None,
        balance_payable=max(balance, Decimal("0")) if balance is not None else None,
        overpayment=max(-balance, Decimal("0")) if balance is not None else None,
        formula=f"{income} × {rule.rate} = {tax}", period=f"{start.isoformat()} — {end.isoformat()}", legal_url=rule.adilet_url,
        included_transaction_ids=[row.transaction_id for row in included],
    )


def main() -> None:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Calculate a reviewed half-year income tax case")
    parser.add_argument("input", type=Path, help="JSON object with rows, profile, and optional rule")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rows = [EvidenceRow.model_validate_json(json.dumps(row)) for row in payload["rows"]]
    profile = PeriodProfile.model_validate_json(json.dumps(payload["profile"]))
    rule = Rule.model_validate_json(json.dumps(payload["rule"])) if payload.get("rule") else None
    print(calculate_period(rows, profile, rule).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
