"""Rule inputs and deterministic deduction evaluation.

This module intentionally contains no Kazakhstan article numbers or invented
legal conclusions. A ``VerifiedDeductionRule`` is supplied only after a legal
provision has been reviewed for the taxpayer, regime, and reporting period.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..models.tax_analysis import TaxAnalysis
from ..models.taxpayer import TaxpayerProfile
from ..models.transaction import Transaction

FixedAssetTreatment = Literal["ordinary", "capitalized", "depreciation", "unknown"]


class LegalReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    act_id: str = Field(min_length=1)
    act_title: str = Field(min_length=1)
    article_number: str = Field(min_length=1)
    legal_url: str = Field(min_length=1)


class VerifiedDeductionRule(BaseModel):
    """A deterministic interpretation of a verified, period-applicable provision."""

    model_config = ConfigDict(extra="forbid", strict=True)

    legal_reference: LegalReference
    legal_analysis_status: Literal["VERSION_VERIFIED"]
    allowed_taxpayer_types: list[str] = Field(default_factory=list)
    allowed_regimes: list[str] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    deduction_fraction: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    prohibited: bool = False
    business_purpose_required: bool = True
    fixed_asset_treatment: FixedAssetTreatment = "unknown"
    explanation: str = Field(min_length=1)


def evaluate_deduction_rule(*, transaction: Transaction, taxpayer: TaxpayerProfile,
                            legal_analysis: TaxAnalysis | None,
                            rule: VerifiedDeductionRule | None,
                            supporting_documents: set[str]) -> dict[str, object]:
    """Evaluate only explicit rule facts; no category is approved implicitly."""
    if transaction.transaction_type != "EXPENSE":
        return {"status": "NOT_APPLICABLE", "explanation": "Налоговые вычеты проверяются только для расходов."}
    if transaction.amount is None or transaction.amount <= 0:
        return {"status": "NEEDS_REVIEW", "explanation": "Сумма расхода отсутствует или некорректна."}
    if legal_analysis is None or legal_analysis.source_verification_status != "VERSION_VERIFIED" or rule is None:
        return {"status": "NEEDS_REVIEW", "explanation": "Нет подтверждённой нормы, применимой к периоду операции."}
    if legal_analysis.needs_review or rule.legal_analysis_status != "VERSION_VERIFIED":
        return {"status": "NEEDS_REVIEW", "explanation": "Правовая применимость требует ручной проверки."}
    if rule.allowed_taxpayer_types and taxpayer.taxpayer_type not in rule.allowed_taxpayer_types:
        return {"status": "NOT_APPLICABLE", "explanation": "Правило не распространяется на данный тип налогоплательщика."}
    if rule.allowed_regimes and taxpayer.tax_regime not in rule.allowed_regimes:
        return {"status": "NOT_APPLICABLE", "explanation": "Правило не распространяется на данный налоговый режим."}
    if rule.allowed_categories and (transaction.category or "") not in rule.allowed_categories:
        return {"status": "NOT_APPLICABLE", "explanation": "Правило не распространяется на категорию операции."}
    if rule.prohibited:
        return {"status": "NOT_ELIGIBLE", "eligible_amount": Decimal("0"), "rejected_amount": transaction.amount, "explanation": rule.explanation}
    if rule.business_purpose_required and not transaction.business_purpose:
        return {"status": "NEEDS_REVIEW", "explanation": "Не указано деловое назначение расхода."}
    missing = sorted(set(rule.required_documents) - supporting_documents)
    if missing:
        return {"status": "NEEDS_REVIEW", "missing_documents": missing, "explanation": "Недостающие подтверждающие документы не позволяют подтвердить вычет."}
    if transaction.category == "Equipment" and rule.fixed_asset_treatment in {"capitalized", "depreciation", "unknown"}:
        return {"status": "NEEDS_REVIEW", "explanation": "Оборудование требует отдельной проверки режима основных средств; оно не признаётся обычным расходом автоматически."}
    eligible = transaction.amount * rule.deduction_fraction
    rejected = transaction.amount - eligible
    if rule.deduction_fraction == 0:
        status = "NOT_ELIGIBLE"
    elif rule.deduction_fraction == 1:
        status = "ELIGIBLE"
    else:
        status = "PARTIALLY_ELIGIBLE"
    return {"status": status, "eligible_amount": eligible, "rejected_amount": rejected, "explanation": rule.explanation}
