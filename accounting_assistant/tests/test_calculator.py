from datetime import date
from decimal import Decimal

from accounting_assistant.models.tax_analysis import TaxAnalysis
from accounting_assistant.models.taxpayer import TaxpayerProfile
from accounting_assistant.models.transaction import Transaction
from accounting_assistant.tax_engine.calculator import TaxCalculator, VerifiedTaxCalculationRule, VerifiedVatRule
from accounting_assistant.tax_engine.deduction_rules import LegalReference, VerifiedDeductionRule
from accounting_assistant.tax_engine.eligibility import TaxEligibility


def _reference():
    return LegalReference(act_id="ACT1", act_title="Verified act", article_number="1", legal_url="https://adilet.zan.kz/rus/docs/ACT1")


def _profile(vat=False, regime="VERIFIED_REGIME"):
    return TaxpayerProfile(taxpayer_id="tp1", taxpayer_type="IE", tax_regime=regime, oked="62010", vat_registered=vat, reporting_period="2026-11")


def _rule(vat_rule=None):
    return VerifiedTaxCalculationRule(regime="VERIFIED_REGIME", taxpayer_types=["IE"], legal_analysis_status="VERSION_VERIFIED", legal_reference=_reference(), deductions_allowed=True, tax_base_formula="income_minus_deductions", tax_rate=Decimal("0.10"), vat_rule=vat_rule, explanation="Verified calculation formula.")


def _tx(txid, kind, amount, category=None, vat=None):
    return Transaction(transaction_id=txid, transaction_date=date(2026, 11, 10), transaction_type=kind, description=category or kind, amount=Decimal(amount), currency="KZT", vat_amount=Decimal(vat) if vat else None, business_purpose="Business activity" if kind == "EXPENSE" else None, category=category, source_document="receipt.txt", review_status="ok")


def _eligibility(txid, amount, eligible, rejected):
    return TaxEligibility(transaction_id=txid, tax_status="ELIGIBLE", original_amount=Decimal(amount), eligible_amount=Decimal(eligible), rejected_amount=Decimal(rejected), explanation="Verified deduction.", legal_reference=_reference(), needs_review=False)


def test_calculator_uses_verified_rule_and_decimal_breakdown():
    transactions = [_tx("income", "INCOME", "1000"), _tx("expense", "EXPENSE", "200", "Office expenses")]
    result = TaxCalculator().calculate(transactions, _profile(), "2026-11", rule=_rule(), eligibility_results=[_eligibility("expense", "200", "200", "0")])
    assert result.status == "CALCULATED"
    assert result.total_income == Decimal("1000")
    assert result.taxable_base == Decimal("800")
    assert result.calculated_tax_amount == Decimal("80.00")


def test_unsupported_regime_does_not_estimate():
    result = TaxCalculator().calculate([], _profile(regime="UNKNOWN"), "2026-11", rule=_rule())
    assert result.status == "UNSUPPORTED_REGIME"
    assert result.calculated_tax_amount is None


def test_missing_eligibility_produces_review_warning():
    class MissingEvidence:
        def evaluate(self, transaction, taxpayer, **kwargs):
            return TaxEligibility(transaction_id=transaction.transaction_id, tax_status="NEEDS_REVIEW", original_amount=transaction.amount, explanation="No evidence available", needs_review=True)
    result = TaxCalculator(eligibility_engine=MissingEvidence()).calculate([_tx("income", "INCOME", "1000"), _tx("expense", "EXPENSE", "200", "Office expenses")], _profile(), "2026-11", rule=_rule())
    assert result.status == "NEEDS_REVIEW"
    assert result.calculated_tax_amount is None
    assert result.taxable_base is None
    assert "expense" in result.review_warnings


def test_vat_requires_verified_vat_rule_and_uses_recorded_vat():
    transactions = [_tx("income", "INCOME", "1000", vat="120"), _tx("expense", "EXPENSE", "200", "Office expenses", vat="24")]
    vat_rule = VerifiedVatRule(legal_analysis_status="VERSION_VERIFIED", input_vat_credit_allowed=True, input_vat_credit_fraction=Decimal("1"), legal_reference=_reference())
    result = TaxCalculator().calculate(transactions, _profile(vat=True), "2026-11", rule=_rule(vat_rule), eligibility_results=[_eligibility("expense", "200", "200", "0")])
    assert result.vat_payable == Decimal("96")


def test_registered_vat_without_rule_requires_review():
    result = TaxCalculator().calculate([_tx("income", "INCOME", "1000")], _profile(vat=True), "2026-11", rule=_rule())
    assert result.status == "NEEDS_REVIEW"
    assert result.vat_payable is None


def test_empty_period_is_explicit():
    result = TaxCalculator().calculate([], _profile(), "2026-11", rule=_rule())
    assert result.status == "EMPTY_PERIOD"
    assert result.calculated_tax_amount == Decimal("0")
