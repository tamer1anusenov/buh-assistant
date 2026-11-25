import json
from datetime import date
from decimal import Decimal

from accounting_assistant.models.taxpayer import TaxpayerProfile
from accounting_assistant.models.transaction import Transaction
from accounting_assistant.report_generator.tax_report import write_tax_reports
from accounting_assistant.tax_engine.calculator import TaxCalculator
from accounting_assistant.tax_engine.deduction_rules import LegalReference, VerifiedDeductionRule
from accounting_assistant.tax_engine.eligibility import TaxEligibility


def test_tax_reports_write_expected_files(tmp_path):
    transaction = Transaction(transaction_id="tx1", transaction_date=date(2026, 11, 10), transaction_type="EXPENSE", description="Office", amount=Decimal("100"), currency="KZT", business_purpose="Business", category="Office expenses", source_document="receipt.txt", review_status="ok")
    profile = TaxpayerProfile(taxpayer_id="tp1", taxpayer_type="IE", tax_regime="R", oked="62010", vat_registered=False, reporting_period="2026-11")
    eligibility = TaxEligibility(transaction_id="tx1", tax_status="NEEDS_REVIEW", original_amount=Decimal("100"), explanation="Review", needs_review=True)
    calculation = TaxCalculator().calculate([transaction], profile, "2026-11")
    paths = write_tax_reports(transactions=[transaction], eligibilities=[eligibility], calculation=calculation, out_dir=tmp_path)
    assert {path.name for path in paths.values()} == {"accounting_summary.csv", "tax_summary.csv", "tax_transactions.csv", "tax_calculation.json"}
    data = json.loads(paths["tax_calculation"].read_text(encoding="utf-8"))
    assert data["status"] == "UNSUPPORTED_REGIME"
