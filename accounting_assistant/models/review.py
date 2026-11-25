"""Manual-review items emitted by the end-to-end workflow."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    transaction_id: str = Field(min_length=1)
    original_description: str | None = None
    problem: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    suggested_next_action: str = Field(min_length=1)
