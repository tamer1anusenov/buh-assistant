"""End-to-end accounting and tax workflow."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from lexaudit.llm import LLMClient

from .accounting_engine.classification import classify_transaction
from .accounting_engine.csv_generator import write_csv
from .accounting_engine.validation import mark_duplicates
from .document_processor import extract_transactions
from .document_processor.llm_extraction import enrich_transaction
from .models.taxpayer import TaxpayerProfile
from .models.transaction import Transaction
from .report_generator.tax_report import write_tax_reports
from .review.items import collect_review_items, write_review_csv
from .tax_engine.calculator import TaxCalculator, VerifiedTaxCalculationRule
from .tax_engine.deduction_rules import VerifiedDeductionRule
from .tax_engine.eligibility import TaxEligibility, TaxEligibilityEngine

logger = logging.getLogger("accounting_assistant.workflow")


class WorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: str
    transactions_extracted: int
    transactions_classified: int
    duplicates_detected: int
    tax_eligible_transactions: int
    review_transactions: int
    tax_calculation_status: str
    generated_files: dict[str, str]
    warnings: list[str]


def run_workflow(input_paths: list[str | Path], *, profile: TaxpayerProfile | None = None,
                 reporting_period: str | None = None, out_dir: str | Path = "reports",
                 llm_client: LLMClient | None = None, use_llm: bool = False,
                 eligibility_engine: TaxEligibilityEngine | None = None,
                 calculator: TaxCalculator | None = None,
                 deduction_rule: VerifiedDeductionRule | None = None,
                 calculation_rule: VerifiedTaxCalculationRule | None = None) -> WorkflowResult:
    """Run all stages while preserving transactions when later stages fail."""
    paths = [Path(path) for path in input_paths]
    source_text = "\n\n".join(path.read_text(encoding="utf-8") for path in paths)
    transactions = [transaction for path in paths for transaction in extract_transactions(path)]
    active_llm = llm_client
    owns_llm = False
    llm_warnings: list[str] = []
    if use_llm and active_llm is None:
        try:
            active_llm = LLMClient()
            owns_llm = True
        except Exception as exc:
            llm_warnings.append(f"llm:{type(exc).__name__}")
    if use_llm and active_llm is not None:
        transactions = [enrich_transaction(transaction, source_text, active_llm) if transaction.review_status == "needs_review" else transaction for transaction in transactions]
    if owns_llm and active_llm is not None:
        active_llm.close()
    transactions = mark_duplicates([classify_transaction(transaction) for transaction in transactions])
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    generated: dict[str, str] = {}
    accounting_path = write_csv(transactions, destination / "accounting.csv")
    generated["accounting"] = str(accounting_path)
    if profile is None:
        review_items = collect_review_items(transactions=transactions, profile_missing=True)
        review_path = write_review_csv(review_items, destination / "review_required.csv")
        generated["review_required"] = str(review_path)
        generated["execution_summary"] = str(destination / "execution_summary.json")
        summary = WorkflowResult(status="ACCOUNTING_ONLY", transactions_extracted=len(transactions), transactions_classified=sum(t.category is not None for t in transactions), duplicates_detected=sum(t.duplicate_of is not None for t in transactions), tax_eligible_transactions=0, review_transactions=len(review_items), tax_calculation_status="NOT_RUN", generated_files=generated, warnings=["Taxpayer profile was not provided; tax analysis was not run.", *llm_warnings])
        _write_execution_summary(destination, summary)
        return summary

    period = reporting_period or profile.reporting_period
    engine = eligibility_engine or TaxEligibilityEngine()
    if isinstance(engine, TaxEligibilityEngine):
        engine.start_run()
    eligibilities: list[TaxEligibility] = []
    warnings: list[str] = [*llm_warnings]
    for transaction in transactions:
        if transaction.transaction_type != "EXPENSE":
            continue
        try:
            eligibilities.append(engine.evaluate(transaction, profile, rule=deduction_rule))
        except Exception as exc:
            logger.exception("eligibility_stage_failed", extra={"transaction_id": transaction.transaction_id})
            eligibilities.append(TaxEligibility(transaction_id=transaction.transaction_id, tax_status="NEEDS_REVIEW", original_amount=transaction.amount, explanation=f"Tax eligibility service failed: {type(exc).__name__}.", needs_review=True))
            warnings.append(f"eligibility:{transaction.transaction_id}")
    calc = calculator or TaxCalculator(eligibility_engine=engine)
    try:
        calculation = calc.calculate(transactions, profile, period, rule=calculation_rule, eligibility_results=eligibilities, deduction_rule=deduction_rule)
    except Exception as exc:
        logger.exception("calculation_stage_failed")
        calculation = TaxCalculator().calculate([], profile, period)
        warnings.append(f"calculation:{type(exc).__name__}")
    generated.update({key: str(value) for key, value in write_tax_reports(transactions=transactions, eligibilities=eligibilities, calculation=calculation, out_dir=destination).items()})
    review_items = collect_review_items(transactions=transactions, eligibilities=eligibilities, calculation=calculation)
    generated["review_required"] = str(write_review_csv(review_items, destination / "review_required.csv"))
    summary = WorkflowResult(status="COMPLETED_WITH_REVIEW" if review_items or calculation.status != "CALCULATED" else "COMPLETED", transactions_extracted=len(transactions), transactions_classified=sum(t.category is not None for t in transactions), duplicates_detected=sum(t.duplicate_of is not None for t in transactions), tax_eligible_transactions=sum(item.tax_status in {"ELIGIBLE", "PARTIALLY_ELIGIBLE"} for item in eligibilities), review_transactions=len(review_items), tax_calculation_status=calculation.status, generated_files=generated, warnings=warnings)
    generated["execution_summary"] = str(destination / "execution_summary.json")
    summary = summary.model_copy(update={"generated_files": generated})
    _write_execution_summary(destination, summary)
    return summary


def _write_execution_summary(destination: Path, summary: WorkflowResult) -> None:
    payload = {"created_at": datetime.now(timezone.utc).isoformat(), **summary.model_dump()}
    (destination / "execution_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
