"""Transaction models shared by extraction, classification, and CSV output."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TransactionType = Literal["INCOME", "EXPENSE"]
ReviewStatus = Literal["ok", "needs_review"]


class Transaction(BaseModel):
    """A transaction with unknown values represented explicitly as ``None``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    transaction_id: str = Field(min_length=1)
    transaction_date: date | None = None
    transaction_type: TransactionType | None = None
    counterparty: str | None = None
    bin_iin: str | None = None
    description: str | None = None
    amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    currency: str | None = None
    vat_amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    payment_method: str | None = None
    business_purpose: str | None = None
    source_document: str = Field(min_length=1)
    category: str | None = None
    classification_confidence: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    classification_reasoning: str | None = None
    tax_deductible: bool | None = None
    tax_category: str | None = None
    legal_reference: str | None = None
    review_status: ReviewStatus = "needs_review"
    duplicate_of: str | None = None
