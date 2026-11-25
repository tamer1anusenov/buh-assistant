"""Optional, validated LLM enrichment for incomplete deterministic extraction."""
from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lexaudit.llm import LLMClient, LLMError

from ..models.transaction import Transaction

logger = logging.getLogger("accounting_assistant.llm_extraction")


class TransactionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    transaction_date: date | None = None
    transaction_type: Literal["INCOME", "EXPENSE"] | None = None
    counterparty: str | None = None
    bin_iin: str | None = None
    description: str | None = None
    amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    currency: str | None = None
    vat_amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    payment_method: str | None = None
    business_purpose: str | None = None


def enrich_transaction(transaction: Transaction, source_text: str, client: LLMClient) -> Transaction:
    """Apply only schema-valid, explicitly returned fields; failure preserves input."""
    messages = [
        {"role": "system", "content": "Извлеки поля финансовой операции из исходного текста. Верни только JSON объекта TransactionPatch. Не выдумывай отсутствующие значения: используй null."},
        {"role": "user", "content": json.dumps({"transaction_id": transaction.transaction_id, "existing": transaction.model_dump(mode="json"), "source_text": source_text}, ensure_ascii=False)},
    ]
    try:
        response = client.chat(messages, temperature=0, max_tokens=700)
        if response.tool_calls:
            raise ValueError("LLM tool calls are not allowed for extraction")
        patch = TransactionPatch.model_validate_json(response.content)
        updates = {key: value for key, value in patch.model_dump().items() if value is not None}
        return Transaction.model_validate({**transaction.model_dump(), **updates})
    except (LLMError, ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("llm_extraction_review", extra={"transaction_id": transaction.transaction_id, "error_type": type(exc).__name__})
        return transaction.model_copy(update={"review_status": "needs_review"})
