"""Convert TXT records into validated Transaction models."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from .txt_parser import parse_record, split_records
from ..accounting_engine.validation import mark_duplicates, validate_transaction
from ..models.transaction import Transaction


def extract_transactions(path: str | Path) -> list[Transaction]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    transactions: list[Transaction] = []
    for index, record in enumerate(split_records(text), 1):
        payload = parse_record(record, source.name, index)
        payload["transaction_id"] = "tx_" + sha256(f"{source.name}\0{index}\0{record}".encode()).hexdigest()[:12]
        transactions.append(validate_transaction(Transaction.model_validate(payload)))
    return mark_duplicates(transactions)
