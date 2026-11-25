"""Deterministic accounting validation and duplicate detection."""
from __future__ import annotations

from ..models.transaction import Transaction


def validate_transaction(transaction: Transaction) -> Transaction:
    """Mark incomplete extraction for review; never fill missing financial data."""
    status = "ok" if all(value is not None for value in (transaction.transaction_date, transaction.transaction_type, transaction.amount)) else "needs_review"
    if transaction.amount == 0:
        status = "needs_review"
    return transaction.model_copy(update={"review_status": status})


def _fingerprint(transaction: Transaction) -> tuple[object, ...]:
    return (transaction.transaction_date, transaction.transaction_type, transaction.counterparty, transaction.amount, transaction.currency, transaction.description)


def mark_duplicates(transactions: list[Transaction]) -> list[Transaction]:
    seen: dict[tuple[object, ...], str] = {}
    result: list[Transaction] = []
    for transaction in transactions:
        fingerprint = _fingerprint(transaction)
        previous = seen.get(fingerprint)
        if previous:
            result.append(transaction.model_copy(update={"duplicate_of": previous, "review_status": "needs_review"}))
        else:
            seen[fingerprint] = transaction.transaction_id
            result.append(transaction)
    return result
