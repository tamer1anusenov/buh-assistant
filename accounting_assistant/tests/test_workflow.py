import csv
import json
from datetime import date
from decimal import Decimal

from lexaudit.llm import ChatResult, TokenUsage

from accounting_assistant.document_processor.llm_extraction import enrich_transaction
from accounting_assistant.models.tax_analysis import TaxAnalysis
from accounting_assistant.models.taxpayer import TaxpayerProfile
from accounting_assistant.models.transaction import Transaction
from accounting_assistant.tax_engine.eligibility import TaxEligibility
from accounting_assistant.workflow import run_workflow


class FakeLLM:
    def __init__(self, content):
        self.content = content

    def chat(self, *args, **kwargs):
        return ChatResult(content=self.content, tool_calls=[], usage=TokenUsage(), latency_ms=0)


class FakeEligibility:
    def evaluate(self, transaction, taxpayer, **kwargs):
        return TaxEligibility(transaction_id=transaction.transaction_id, tax_status="NEEDS_REVIEW", original_amount=transaction.amount, explanation="Mocked legal review.", needs_review=True)


def test_invalid_llm_output_preserves_transaction_for_review(tmp_path):
    transaction = Transaction(transaction_id="tx1", transaction_date=None, transaction_type=None, description="unknown", amount=None, source_document="r.txt")
    result = enrich_transaction(transaction, "unknown receipt", FakeLLM("not json"))
    assert result.transaction_id == "tx1"
    assert result.amount is None
    assert result.review_status == "needs_review"


def test_workflow_without_profile_generates_accounting_and_review(tmp_path):
    source = tmp_path / "receipts.txt"
    source.write_text("Date: 10.11.2026\nType: Expense\nDescription: Office paper\nAmount: 100 KZT\n", encoding="utf-8")
    result = run_workflow([source], out_dir=tmp_path / "reports")
    assert result.status == "ACCOUNTING_ONLY"
    assert (tmp_path / "reports" / "accounting.csv").exists()
    assert (tmp_path / "reports" / "review_required.csv").exists()
    assert result.tax_calculation_status == "NOT_RUN"


def test_profile_workflow_generates_all_tax_outputs_and_preserves_review(tmp_path):
    source = tmp_path / "receipts.txt"
    source.write_text("Date: 10.11.2026\nType: Expense\nDescription: Office paper\nAmount: 100 KZT\n", encoding="utf-8")
    profile = TaxpayerProfile(taxpayer_id="tp1", taxpayer_type="IE", tax_regime="UNKNOWN", oked="62010", vat_registered=False, reporting_period="2026-11")
    result = run_workflow([source], profile=profile, out_dir=tmp_path / "reports", eligibility_engine=FakeEligibility())
    expected = {"accounting", "accounting_summary", "tax_summary", "tax_transactions", "tax_calculation", "review_required", "execution_summary"}
    assert expected <= set(result.generated_files)
    assert result.tax_calculation_status == "UNSUPPORTED_REGIME"
    payload = json.loads((tmp_path / "reports" / "execution_summary.json").read_text(encoding="utf-8"))
    assert payload["transactions_extracted"] == 1
    with (tmp_path / "reports" / "tax_transactions.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["transaction_id"]
    assert rows[0]["needs_review"] == "true"


def test_workflow_does_not_drop_transactions_when_eligibility_fails(tmp_path):
    source = tmp_path / "receipts.txt"
    source.write_text("Date: 10.11.2026\nType: Expense\nDescription: Office paper\nAmount: 100 KZT\n", encoding="utf-8")

    class FailingEligibility:
        def evaluate(self, *args, **kwargs):
            raise RuntimeError("Adilet unavailable")

    profile = TaxpayerProfile(taxpayer_id="tp1", taxpayer_type="IE", tax_regime="UNKNOWN", oked="62010", vat_registered=False, reporting_period="2026-11")
    result = run_workflow([source], profile=profile, out_dir=tmp_path / "reports", eligibility_engine=FailingEligibility())
    assert result.transactions_extracted == 1
    assert result.review_transactions > 0
    assert (tmp_path / "reports" / "accounting.csv").exists()
