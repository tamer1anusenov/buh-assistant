"""Conservative deterministic transaction classification."""
from __future__ import annotations

from decimal import Decimal

from ..models.transaction import Transaction

_RULES = (
    ("Service revenue", ("разработ", "консалт", "website development")),
    ("Software and IT", ("software", "лиценз", "хостинг", "сайт", "it")),
    ("Equipment", ("laptop", "ноутбук", "оборуд", "компьютер", "техника")),
    ("Rent", ("аренд", "rent", "офис")),
    ("Transportation", ("такси", "бензин", "транспорт", "достав")),
    ("Marketing", ("реклам", "marketing", "продвиж")),
    ("Contractor services", ("подряд", "фриланс", "услуг", "contractor")),
    ("Sales revenue", ("продаж", "sales", "выруч")),
)


def classify_transaction(transaction: Transaction) -> Transaction:
    text = " ".join(filter(None, [transaction.description, transaction.business_purpose])).casefold()
    for category, terms in _RULES:
        if any(term in text for term in terms):
            return transaction.model_copy(update={"category": category, "classification_confidence": Decimal("0.85"), "classification_reasoning": f"Найдено ключевое слово категории: {category}."})
    category = "Other income" if transaction.transaction_type == "INCOME" else "Other expenses"
    return transaction.model_copy(update={"category": category, "classification_confidence": Decimal("0.40"), "classification_reasoning": "Недостаточно признаков для уверенной классификации.", "review_status": "needs_review"})
