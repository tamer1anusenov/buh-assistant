"""Deterministic tax eligibility decisions based on verified legal rules."""

from .deduction_rules import VerifiedDeductionRule
from .eligibility import TaxEligibility, TaxEligibilityEngine

__all__ = ["TaxEligibility", "TaxEligibilityEngine", "VerifiedDeductionRule"]
