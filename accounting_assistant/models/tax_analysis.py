"""Models for candidate tax-law evidence, not final tax decisions."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceStatus = Literal[
    "SOURCE_VERIFIED", "ARTICLE_VERIFIED", "QUOTE_VERIFIED", "VERSION_VERIFIED", "NEEDS_REVIEW", "INVALID"
]


class LegalProvisionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    act_id: str = Field(min_length=1)
    act_title: str = Field(min_length=1)
    article_number: str = Field(min_length=1)
    paragraph_number: str | None = None
    legal_url: str = Field(min_length=1)
    article_text: str = Field(min_length=1)
    publication_date: date | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    in_force: bool
    version_status: str


class TaxAnalysis(BaseModel):
    """Candidate provisions associated with one transaction."""

    model_config = ConfigDict(extra="forbid", strict=True)

    transaction_id: str = Field(min_length=1)
    taxpayer_id: str = Field(min_length=1)
    relevant_tax_category: str | None = None
    candidate_legal_provisions: list[LegalProvisionCandidate] = Field(default_factory=list)
    legal_act_id: str | None = None
    legal_act_title: str | None = None
    article_number: str | None = None
    paragraph_number: str | None = None
    legal_url: str | None = None
    effective_date: date | None = None
    evidence_quote: str | None = None
    source_verification_status: EvidenceStatus
    analysis_explanation: str = Field(min_length=1)
    needs_review: bool
