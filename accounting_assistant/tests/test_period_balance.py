"""Synthetic rules test arithmetic only, without asserting Kazakhstan law."""
from datetime import date
from decimal import Decimal

from accounting_assistant.tax_engine.period_balance import EvidenceRow, PeriodProfile, Rule, calculate_period


def test_balance_requires_complete_income_and_known_payments():
    rule = Rule(rule_id="synthetic", version=1, regime="simplified_declaration", tax="individual_income_tax", region="test", rate=Decimal("0.03"), effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31), adilet_url="https://adilet.zan.kz/rus/docs/synthetic", article="synthetic", source_sha256="a" * 64, checked_on=date(2026, 11, 24), reviewed_by="test", status="verified", rounding_places=2)
    row = EvidenceRow(transaction_id="one", document_sha256="b" * 64, page=1, passage="synthetic payment", transaction_date=date(2026, 11, 1), amount=Decimal("250000"), currency="KZT", operation="BUSINESS_INCOME", reviewed=True)
    profile = PeriodProfile(regime="simplified_declaration", region="test", year=2026, half=2, eligibility_confirmed=True, eligibility_evidence="synthetic eligibility", has_employees=False, income_recognition_confirmed=True)
    result = calculate_period([row], profile, rule)
    assert result.balance_payable is None
    assert result.assessed_tax is None
    profile = profile.model_copy(update={"complete_income_confirmed": True, "payments_made": Decimal("1000")})
    assert calculate_period([row], profile, rule).balance_payable == Decimal("6500")
    assert calculate_period([row, row], profile, rule).balance_payable is None
    assert calculate_period([row.model_copy(update={"currency": "USD"})], profile, rule).balance_payable is None
    assert calculate_period([row], profile, rule.model_copy(update={"status": "stale"})).balance_payable is None
