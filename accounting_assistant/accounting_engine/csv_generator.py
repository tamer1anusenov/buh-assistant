"""Accounting CSV export with stable columns and Decimal-safe formatting."""
from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from ..models.transaction import Transaction
from .classification import classify_transaction

CSV_COLUMNS = ["transaction_id", "date", "transaction_type", "counterparty", "bin_iin", "description", "category", "amount", "currency", "vat_amount", "payment_method", "business_purpose", "tax_deductible", "tax_category", "legal_reference", "confidence", "review_status", "source_document"]


def _decimal(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def write_csv(transactions: list[Transaction], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for original in transactions:
            transaction = classify_transaction(original) if original.category is None else original
            writer.writerow({"transaction_id": transaction.transaction_id, "date": transaction.transaction_date.isoformat() if transaction.transaction_date else "", "transaction_type": transaction.transaction_type or "", "counterparty": transaction.counterparty or "", "bin_iin": transaction.bin_iin or "", "description": transaction.description or "", "category": transaction.category or "", "amount": _decimal(transaction.amount), "currency": transaction.currency or "", "vat_amount": _decimal(transaction.vat_amount), "payment_method": transaction.payment_method or "", "business_purpose": transaction.business_purpose or "", "tax_deductible": "" if transaction.tax_deductible is None else str(transaction.tax_deductible).lower(), "tax_category": transaction.tax_category or "", "legal_reference": transaction.legal_reference or "", "confidence": _decimal(transaction.classification_confidence), "review_status": transaction.review_status, "source_document": transaction.source_document})
    return destination
