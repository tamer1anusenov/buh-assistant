"""Transparent outputs from verified tax calculation rules."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..tax_engine.deduction_rules import LegalReference

CalculationStatus = Literal["CALCULATED", "NEEDS_REVIEW", "UNSUPPORTED_REGIME", "EMPTY_PERIOD"]


class CalculationBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    transaction_id: str
    transaction_type: str | None
    original_amount: Decimal | None
    eligible_deduction: Decimal | None
    rejected_deduction: Decimal | None
    tax_status: str
    explanation: str
    legal_reference: LegalReference | None = None


class TaxCalculationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    taxpayer_id: str
    reporting_period: str
    tax_regime: str
    total_income: Decimal
    total_accounting_expenses: Decimal
    total_eligible_deductions: Decimal
    total_non_deductible_expenses: Decimal
    taxable_base: Decimal | None
    applicable_tax_rate: Decimal | None
    calculated_tax_amount: Decimal | None
    vat_payable: Decimal | None
    status: CalculationStatus
    legal_references: list[LegalReference] = Field(default_factory=list)
    breakdown: list[CalculationBreakdown] = Field(default_factory=list)
    explanation: str
    missing_information: list[str] = Field(default_factory=list)
    review_warnings: list[str] = Field(default_factory=list)
