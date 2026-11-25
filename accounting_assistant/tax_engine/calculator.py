"""Deterministic calculations driven exclusively by verified runtime rules."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..models.tax_analysis import TaxAnalysis
from ..models.tax_calculation import CalculationBreakdown, TaxCalculationResult
from ..models.taxpayer import TaxpayerProfile
from ..models.transaction import Transaction
from .deduction_rules import LegalReference, VerifiedDeductionRule
from .eligibility import TaxEligibility, TaxEligibilityEngine


class VerifiedVatRule(BaseModel):
    """VAT facts explicitly verified for the selected period and taxpayer."""

    model_config = ConfigDict(extra="forbid", strict=True)

    legal_analysis_status: Literal["VERSION_VERIFIED"]
    output_vat_required: bool = True
    input_vat_credit_allowed: bool = False
    input_vat_credit_fraction: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("1"))
    legal_reference: LegalReference


class VerifiedTaxCalculationRule(BaseModel):
    """A complete regime rule supplied from verified legal evidence."""

    model_config = ConfigDict(extra="forbid", strict=True)

    regime: str = Field(min_length=1)
    taxpayer_types: list[str] = Field(min_length=1)
    legal_analysis_status: Literal["VERSION_VERIFIED"]
    legal_reference: LegalReference
    deductions_allowed: bool
    tax_base_formula: Literal["income_minus_deductions", "income"]
    tax_rate: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    vat_rule: VerifiedVatRule | None = None
    rounding_places: int = Field(default=2, ge=0, le=8)
    explanation: str = Field(min_length=1)


class TaxCalculator:
    """Calculate one reporting period only when a verified regime rule exists."""

    def __init__(self, *, eligibility_engine: TaxEligibilityEngine | None = None) -> None:
        self._eligibility_engine = eligibility_engine or TaxEligibilityEngine()

    def calculate(self, transactions: list[Transaction], taxpayer: TaxpayerProfile, reporting_period: str,
                  *, rule: VerifiedTaxCalculationRule | None = None,
                  eligibility_results: list[TaxEligibility] | None = None,
                  legal_analyses: dict[str, TaxAnalysis] | None = None,
                  deduction_rule: VerifiedDeductionRule | None = None,
                  supporting_documents: dict[str, set[str]] | None = None) -> TaxCalculationResult:
        period_transactions = [t for t in transactions if self._in_period(t.transaction_date, reporting_period)]
        if taxpayer.reporting_period != reporting_period:
            return self._review(taxpayer, reporting_period, "Период профиля налогоплательщика не совпадает с выбранным периодом.", ["reporting_period"])
        if rule is None or rule.legal_analysis_status != "VERSION_VERIFIED":
            return self._unsupported(taxpayer, reporting_period, period_transactions, "Нет проверенного расчётного правила для режима.")
        if rule.regime != taxpayer.tax_regime or taxpayer.taxpayer_type not in rule.taxpayer_types:
            return self._unsupported(taxpayer, reporting_period, period_transactions, "Расчётное правило не поддерживает данный режим или тип налогоплательщика.")
        if not period_transactions:
            return self._zero(taxpayer, reporting_period, rule, "В выбранном периоде нет транзакций.")

        results = {item.transaction_id: item for item in (eligibility_results or [])}
        analyses = legal_analyses or {}
        docs = supporting_documents or {}
        income = sum((t.amount for t in period_transactions if t.transaction_type == "INCOME" and t.amount is not None), Decimal("0"))
        expenses = sum((t.amount for t in period_transactions if t.transaction_type == "EXPENSE" and t.amount is not None), Decimal("0"))
        eligible = Decimal("0")
        rejected = Decimal("0")
        breakdown: list[CalculationBreakdown] = []
        references: list[LegalReference] = [rule.legal_reference]
        warnings: list[str] = []
        for transaction in period_transactions:
            if transaction.transaction_type != "EXPENSE":
                breakdown.append(CalculationBreakdown(transaction_id=transaction.transaction_id, transaction_type=transaction.transaction_type, original_amount=transaction.amount, eligible_deduction=Decimal("0"), rejected_deduction=Decimal("0"), tax_status="NOT_APPLICABLE", explanation="Доход не является расходом для вычета."))
                continue
            result = results.get(transaction.transaction_id)
            if result is None:
                result = self._eligibility_engine.evaluate(transaction, taxpayer, rule=deduction_rule, legal_analysis=analyses.get(transaction.transaction_id), supporting_documents=docs.get(transaction.transaction_id, set()))
            if result.legal_reference and result.legal_reference not in references:
                references.append(result.legal_reference)
            if result.tax_status in {"ELIGIBLE", "PARTIALLY_ELIGIBLE"} and rule.deductions_allowed and result.eligible_amount is not None:
                eligible += result.eligible_amount
                rejected += result.rejected_amount or Decimal("0")
            elif result.original_amount is not None:
                rejected += result.original_amount if result.tax_status == "NOT_ELIGIBLE" else Decimal("0")
            if result.needs_review:
                warnings.append(transaction.transaction_id)
            breakdown.append(CalculationBreakdown(transaction_id=transaction.transaction_id, transaction_type=transaction.transaction_type, original_amount=result.original_amount, eligible_deduction=result.eligible_amount, rejected_deduction=result.rejected_amount, tax_status=result.tax_status, explanation=result.explanation, legal_reference=result.legal_reference))
        base = income - eligible if rule.tax_base_formula == "income_minus_deductions" else income
        if base < 0:
            base = Decimal("0")
        tax = self._round(base * rule.tax_rate, rule.rounding_places)
        vat, vat_warning = self._calculate_vat(period_transactions, taxpayer, rule)
        if vat_warning:
            warnings.append(vat_warning)
        status = "NEEDS_REVIEW" if warnings else "CALCULATED"
        return TaxCalculationResult(taxpayer_id=taxpayer.taxpayer_id, reporting_period=reporting_period, tax_regime=taxpayer.tax_regime, total_income=income, total_accounting_expenses=expenses, total_eligible_deductions=eligible, total_non_deductible_expenses=rejected, taxable_base=base if not warnings else None, applicable_tax_rate=rule.tax_rate, calculated_tax_amount=tax if not warnings else None, vat_payable=vat if not vat_warning else None, status=status, legal_references=references, breakdown=breakdown, explanation=rule.explanation, review_warnings=warnings)

    @staticmethod
    def _in_period(value: date | None, period: str) -> bool:
        return value is not None and len(period) == 7 and period[4] == "-" and f"{value.year:04d}-{value.month:02d}" == period

    @staticmethod
    def _round(value: Decimal, places: int) -> Decimal:
        return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)

    def _calculate_vat(self, transactions: list[Transaction], taxpayer: TaxpayerProfile, rule: VerifiedTaxCalculationRule) -> tuple[Decimal | None, str | None]:
        if not taxpayer.vat_registered:
            return None, None
        vat_rule = rule.vat_rule
        if vat_rule is None or vat_rule.legal_analysis_status != "VERSION_VERIFIED":
            return None, "VAT зарегистрирован, но проверенное VAT-правило отсутствует."
        output = sum((t.vat_amount or Decimal("0") for t in transactions if t.transaction_type == "INCOME"), Decimal("0"))
        input_vat = Decimal("0")
        if vat_rule.input_vat_credit_allowed:
            input_vat = sum((t.vat_amount or Decimal("0") for t in transactions if t.transaction_type == "EXPENSE"), Decimal("0")) * vat_rule.input_vat_credit_fraction
        return output - input_vat, None

    @staticmethod
    def _unsupported(taxpayer: TaxpayerProfile, period: str, transactions: list[Transaction], explanation: str) -> TaxCalculationResult:
        return TaxCalculationResult(taxpayer_id=taxpayer.taxpayer_id, reporting_period=period, tax_regime=taxpayer.tax_regime, total_income=sum((t.amount for t in transactions if t.transaction_type == "INCOME" and t.amount is not None), Decimal("0")), total_accounting_expenses=sum((t.amount for t in transactions if t.transaction_type == "EXPENSE" and t.amount is not None), Decimal("0")), total_eligible_deductions=Decimal("0"), total_non_deductible_expenses=Decimal("0"), taxable_base=None, applicable_tax_rate=None, calculated_tax_amount=None, vat_payable=None, status="UNSUPPORTED_REGIME", explanation=explanation, missing_information=["verified_calculation_rule"])

    @staticmethod
    def _review(taxpayer: TaxpayerProfile, period: str, explanation: str, missing: list[str]) -> TaxCalculationResult:
        return TaxCalculationResult(taxpayer_id=taxpayer.taxpayer_id, reporting_period=period, tax_regime=taxpayer.tax_regime, total_income=Decimal("0"), total_accounting_expenses=Decimal("0"), total_eligible_deductions=Decimal("0"), total_non_deductible_expenses=Decimal("0"), taxable_base=None, applicable_tax_rate=None, calculated_tax_amount=None, vat_payable=None, status="NEEDS_REVIEW", explanation=explanation, missing_information=missing)

    @staticmethod
    def _zero(taxpayer: TaxpayerProfile, period: str, rule: VerifiedTaxCalculationRule, explanation: str) -> TaxCalculationResult:
        return TaxCalculationResult(taxpayer_id=taxpayer.taxpayer_id, reporting_period=period, tax_regime=taxpayer.tax_regime, total_income=Decimal("0"), total_accounting_expenses=Decimal("0"), total_eligible_deductions=Decimal("0"), total_non_deductible_expenses=Decimal("0"), taxable_base=Decimal("0"), applicable_tax_rate=rule.tax_rate, calculated_tax_amount=Decimal("0"), vat_payable=Decimal("0") if rule.vat_rule else None, status="EMPTY_PERIOD", explanation=explanation)
