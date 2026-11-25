"""Structured deterministic tax eligibility decisions."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..models.tax_analysis import TaxAnalysis
from ..models.taxpayer import TaxpayerProfile
from ..models.transaction import Transaction
from ..tax_knowledge_engine.law_retrieval import TaxLawService
from .deduction_rules import LegalReference, VerifiedDeductionRule, evaluate_deduction_rule

TaxStatus = Literal["ELIGIBLE", "NOT_ELIGIBLE", "PARTIALLY_ELIGIBLE", "NEEDS_REVIEW", "NOT_APPLICABLE"]


class TaxEligibility(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    transaction_id: str = Field(min_length=1)
    tax_status: TaxStatus
    original_amount: Decimal | None = None
    eligible_amount: Decimal | None = None
    rejected_amount: Decimal | None = None
    explanation: str = Field(min_length=1)
    legal_reference: LegalReference | None = None
    missing_documents: list[str] = Field(default_factory=list)
    needs_review: bool


class TaxEligibilityEngine:
    """Retrieve candidate law when needed, then apply an explicit verified rule."""

    def __init__(self, *, law_service: TaxLawService | None = None) -> None:
        self._law_service = law_service or TaxLawService()

    def start_run(self) -> None:
        self._law_service.reset_availability()

    def evaluate(self, transaction: Transaction, taxpayer: TaxpayerProfile, *,
                 rule: VerifiedDeductionRule | None = None,
                 legal_analysis: TaxAnalysis | None = None,
                 supporting_documents: set[str] | None = None,
                 transaction_date: date | None = None) -> TaxEligibility:
        documents = supporting_documents or set()
        analysis = legal_analysis
        if analysis is None:
            analysis = self._law_service.analyze_transaction(transaction, taxpayer, transaction_date)
        decision = evaluate_deduction_rule(transaction=transaction, taxpayer=taxpayer, legal_analysis=analysis, rule=rule, supporting_documents=documents)
        if decision["status"] == "NEEDS_REVIEW" and analysis.source_verification_status == "NEEDS_REVIEW":
            decision["explanation"] = analysis.analysis_explanation
        reference = rule.legal_reference if rule is not None else None
        if reference is None and analysis is not None and all((analysis.legal_act_id, analysis.legal_act_title, analysis.article_number, analysis.legal_url)):
            reference = LegalReference(act_id=analysis.legal_act_id, act_title=analysis.legal_act_title, article_number=analysis.article_number, legal_url=analysis.legal_url)
        status = decision["status"]
        eligible = decision.get("eligible_amount")
        rejected = decision.get("rejected_amount")
        return TaxEligibility(transaction_id=transaction.transaction_id, tax_status=status, original_amount=transaction.amount, eligible_amount=eligible if isinstance(eligible, Decimal) else None, rejected_amount=rejected if isinstance(rejected, Decimal) else None, explanation=str(decision["explanation"]), legal_reference=reference, missing_documents=list(decision.get("missing_documents", [])), needs_review=status == "NEEDS_REVIEW")
