from datetime import date
from decimal import Decimal

from accounting_assistant.models.tax_analysis import TaxAnalysis
from accounting_assistant.models.taxpayer import TaxpayerProfile
from accounting_assistant.models.transaction import Transaction
from accounting_assistant.tax_engine.deduction_rules import LegalReference, VerifiedDeductionRule
from accounting_assistant.tax_engine.eligibility import TaxEligibilityEngine


def _profile(regime="SIMPLIFIED"):
    return TaxpayerProfile(taxpayer_id="tp1", taxpayer_type="IE", tax_regime=regime, oked="62010", vat_registered=False, reporting_period="2026-Q1")


def _transaction(category="Office expenses", purpose="Офисная деятельность"):
    return Transaction(transaction_id="tx1", transaction_date=date(2026, 2, 1), transaction_type="EXPENSE", description=category, amount=Decimal("100.00"), currency="KZT", business_purpose=purpose, category=category, source_document="receipt.txt", review_status="ok")


def _analysis():
    return TaxAnalysis(transaction_id="tx1", taxpayer_id="tp1", relevant_tax_category="Office expenses", legal_act_id="ACT1", legal_act_title="Verified act", article_number="1", legal_url="https://adilet.zan.kz/rus/docs/ACT1", effective_date=date(2026, 1, 1), evidence_quote="Verified provision", source_verification_status="VERSION_VERIFIED", analysis_explanation="Verified provision.", needs_review=False)


def _rule(fraction="1", **kwargs):
    return VerifiedDeductionRule(legal_reference=LegalReference(act_id="ACT1", act_title="Verified act", article_number="1", legal_url="https://adilet.zan.kz/rus/docs/ACT1"), legal_analysis_status="VERSION_VERIFIED", deduction_fraction=Decimal(fraction), explanation="Verified rule.", **kwargs)


def test_fully_eligible_expense_uses_decimal_amount():
    result = TaxEligibilityEngine().evaluate(_transaction(), _profile(), rule=_rule(), legal_analysis=_analysis())
    assert result.tax_status == "ELIGIBLE"
    assert result.eligible_amount == Decimal("100.00")
    assert result.rejected_amount == Decimal("0.00")


def test_partial_rule_returns_partial_amount():
    result = TaxEligibilityEngine().evaluate(_transaction(), _profile(), rule=_rule("0.5"), legal_analysis=_analysis())
    assert result.tax_status == "PARTIALLY_ELIGIBLE"
    assert result.eligible_amount == Decimal("50.000")
    assert result.rejected_amount == Decimal("50.000")


def test_prohibited_rule_is_not_eligible():
    result = TaxEligibilityEngine().evaluate(_transaction(), _profile(), rule=_rule("0", prohibited=True), legal_analysis=_analysis())
    assert result.tax_status == "NOT_ELIGIBLE"
    assert result.eligible_amount == Decimal("0")


def test_missing_documents_require_review():
    result = TaxEligibilityEngine().evaluate(_transaction(), _profile(), rule=_rule(required_documents=["invoice"]), legal_analysis=_analysis())
    assert result.tax_status == "NEEDS_REVIEW"
    assert result.missing_documents == ["invoice"]


def test_equipment_is_not_ordinary_deduction():
    result = TaxEligibilityEngine().evaluate(_transaction("Equipment"), _profile(), rule=_rule(), legal_analysis=_analysis())
    assert result.tax_status == "NEEDS_REVIEW"


def test_personal_or_missing_business_purpose_requires_review_without_verified_prohibition():
    result = TaxEligibilityEngine().evaluate(_transaction(purpose=None), _profile(), rule=_rule(), legal_analysis=_analysis())
    assert result.tax_status == "NEEDS_REVIEW"


def test_missing_legal_evidence_requires_review():
    analysis = _analysis().model_copy(update={"source_verification_status": "NEEDS_REVIEW", "needs_review": True})
    result = TaxEligibilityEngine().evaluate(_transaction(), _profile(), rule=None, legal_analysis=analysis)
    assert result.tax_status == "NEEDS_REVIEW"
    assert result.needs_review is True


def test_regime_restriction_is_not_applicable():
    result = TaxEligibilityEngine().evaluate(_transaction(), _profile("GENERAL"), rule=_rule(allowed_regimes=["SIMPLIFIED"]), legal_analysis=_analysis())
    assert result.tax_status == "NOT_APPLICABLE"
