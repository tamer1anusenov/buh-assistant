"""Generate accounting and transaction-level tax reports."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from ..models.tax_calculation import TaxCalculationResult
from ..models.transaction import Transaction
from ..tax_engine.eligibility import TaxEligibility
from .client_language import category_label, explain_review, STATUSES


def _money(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def _summary(transactions: list[Transaction], period: str) -> list[dict[str, str]]:
    income = sum((t.amount for t in transactions if t.transaction_type == "INCOME" and t.amount is not None), Decimal("0"))
    expenses = sum((t.amount for t in transactions if t.transaction_type == "EXPENSE" and t.amount is not None), Decimal("0"))
    by_category: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for transaction in transactions:
        if transaction.amount is not None:
            by_category[f"{transaction.transaction_type or 'UNKNOWN'}:{transaction.category or 'UNKNOWN'}"] += transaction.amount
    rows = [{"period": period, "metric": "total_income", "category": "", "amount": _money(income), "count": str(sum(t.transaction_type == "INCOME" for t in transactions)), "review_count": ""}, {"period": period, "metric": "total_expenses", "category": "", "amount": _money(expenses), "count": str(sum(t.transaction_type == "EXPENSE" for t in transactions)), "review_count": ""}]
    rows.extend({"period": period, "metric": "by_category", "category": key, "amount": _money(amount), "count": "", "review_count": ""} for key, amount in sorted(by_category.items()))
    rows.append({"period": period, "metric": "review_transactions", "category": "", "amount": "", "count": str(sum(t.review_status == "needs_review" or t.duplicate_of is not None for t in transactions)), "review_count": ""})
    return rows


def write_tax_reports(*, transactions: list[Transaction], eligibilities: list[TaxEligibility], calculation: TaxCalculationResult, out_dir: str | Path) -> dict[str, Path]:
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    accounting_path = destination / "accounting_summary.csv"
    with accounting_path.open("w", encoding="utf-8", newline="") as stream:
        fields = ["period", "metric", "category", "amount", "count", "review_count"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(_summary(transactions, calculation.reporting_period))

    eligibility_by_id = {item.transaction_id: item for item in eligibilities}
    tax_summary_path = destination / "tax_summary.csv"
    with tax_summary_path.open("w", encoding="utf-8", newline="") as stream:
        fields = ["period", "metric", "amount", "status", "explanation"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        rows = [("total_eligible_deductions", calculation.total_eligible_deductions, calculation.status, calculation.explanation), ("total_non_deductible_expenses", calculation.total_non_deductible_expenses, calculation.status, calculation.explanation), ("taxable_base", calculation.taxable_base, calculation.status, calculation.explanation), ("calculated_tax_amount", calculation.calculated_tax_amount, calculation.status, calculation.explanation), ("vat_payable", calculation.vat_payable, calculation.status, calculation.explanation)]
        for metric, amount, status, explanation in rows:
            writer.writerow({"period": calculation.reporting_period, "metric": metric, "amount": _money(amount), "status": status, "explanation": explain_review(explanation)})

    transaction_path = destination / "tax_transactions.csv"
    with transaction_path.open("w", encoding="utf-8", newline="") as stream:
        fields = ["transaction_id", "description", "category", "currency", "original_amount", "eligible_amount", "rejected_amount", "tax_status", "client_status", "explanation", "legal_reference", "missing_documents", "needs_review"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for transaction in transactions:
            if transaction.transaction_type != "EXPENSE":
                continue
            item = eligibility_by_id.get(transaction.transaction_id)
            writer.writerow({"transaction_id": transaction.transaction_id, "description": transaction.description, "category": category_label(transaction.category), "currency": transaction.currency, "original_amount": _money(item.original_amount if item else transaction.amount), "eligible_amount": _money(item.eligible_amount if item else None), "rejected_amount": _money(item.rejected_amount if item else None), "tax_status": item.tax_status if item else "NEEDS_REVIEW", "client_status": STATUSES.get(item.tax_status if item else "NEEDS_REVIEW"), "explanation": explain_review(item.explanation) if item else "Покупка записана. Возможность уменьшить налог нужно уточнить.", "legal_reference": item.legal_reference.model_dump_json() if item and item.legal_reference else "", "missing_documents": ";".join(item.missing_documents) if item else "", "needs_review": str(item.needs_review if item else True).lower()})

    calculation_path = destination / "tax_calculation.json"
    calculation_path.write_text(json.dumps(calculation.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return {"accounting_summary": accounting_path, "tax_summary": tax_summary_path, "tax_transactions": transaction_path, "tax_calculation": calculation_path}
