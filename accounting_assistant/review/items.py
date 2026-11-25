"""Build traceable manual-review records from every workflow stage."""
from __future__ import annotations

import csv
from pathlib import Path

from ..models.review import ReviewItem
from ..models.tax_calculation import TaxCalculationResult
from ..models.transaction import Transaction
from ..tax_engine.eligibility import TaxEligibility


def collect_review_items(*, transactions: list[Transaction], eligibilities: list[TaxEligibility] | None = None, calculation: TaxCalculationResult | None = None, profile_missing: bool = False) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    by_id = {item.transaction_id: item for item in (eligibilities or [])}

    def add(transaction: Transaction, problem: str, reason: str, action: str) -> None:
        if not any(item.transaction_id == transaction.transaction_id and item.problem == problem for item in items):
            items.append(ReviewItem(transaction_id=transaction.transaction_id, original_description=transaction.description, problem=problem, reason=reason, suggested_next_action=action))

    for transaction in transactions:
        if transaction.transaction_date is None:
            add(transaction, "missing_date", "Дата операции не извлечена.", "Проверить исходный документ и указать дату.")
        if transaction.amount is None:
            add(transaction, "missing_amount", "Сумма операции не извлечена.", "Проверить чек или банковскую запись.")
        elif transaction.amount == 0:
            add(transaction, "zero_amount", "В документе указана нулевая сумма.", "Подтвердить, что сумма действительно равна нулю, или исправить её по документу.")
        if transaction.transaction_type is None:
            add(transaction, "missing_transaction_type", "Тип дохода или расхода не определён.", "Подтвердить направление операции.")
        if transaction.duplicate_of:
            add(transaction, "duplicate", f"Совпадает с операцией {transaction.duplicate_of}.", "Проверить, не является ли запись повторной.")
        if transaction.review_status == "needs_review":
            add(transaction, "transaction_validation", "Извлечённые поля или классификация требуют проверки.", "Проверить поля операции вручную.")
        if transaction.transaction_type == "EXPENSE" and not transaction.business_purpose:
            add(transaction, "missing_business_purpose", "Не указано деловое назначение расхода.", "Добавить деловое назначение и подтверждающие документы.")
        eligibility = by_id.get(transaction.transaction_id)
        if eligibility and eligibility.needs_review:
            add(transaction, "tax_eligibility", eligibility.explanation, "Проверить правовое основание и документы.")
            for document in eligibility.missing_documents:
                add(transaction, f"missing_document:{document}", f"Не хватает документа: {document}.", "Предоставить документ или подтвердить его отсутствие.")
    if profile_missing:
        for transaction in transactions:
            add(transaction, "missing_taxpayer_profile", "Профиль налогоплательщика не передан.", "Передать профиль для налогового анализа.")
    if calculation and calculation.status in {"NEEDS_REVIEW", "UNSUPPORTED_REGIME"}:
        for transaction in transactions:
            add(transaction, "tax_calculation", calculation.explanation, "Добавить проверенное правило или выбрать поддерживаемый режим.")
    return items


def write_review_csv(items: list[ReviewItem], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        fields = ["transaction_id", "original_description", "problem", "reason", "suggested_next_action"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(item.model_dump() for item in items)
    return destination
