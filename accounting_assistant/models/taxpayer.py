"""Taxpayer profile used to scope tax-law retrieval."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaxpayerType = Literal["INDIVIDUAL", "IE", "LLP"]


class TaxpayerProfile(BaseModel):
    """Required profile facts; no tax regime or VAT status is inferred."""

    model_config = ConfigDict(extra="forbid", strict=True)

    taxpayer_id: str = Field(min_length=1)
    taxpayer_type: TaxpayerType
    tax_regime: str = Field(min_length=1)
    oked: str = Field(min_length=1)
    vat_registered: bool
    reporting_period: str = Field(min_length=1)
    country: Literal["KZ"] = "KZ"
