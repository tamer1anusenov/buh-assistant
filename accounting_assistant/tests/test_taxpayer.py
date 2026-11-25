import pytest
from pydantic import ValidationError

from accounting_assistant.models.taxpayer import TaxpayerProfile


def test_taxpayer_profile_requires_explicit_regime_and_vat_status():
    profile = TaxpayerProfile(taxpayer_id="t1", taxpayer_type="IE", tax_regime="SIMPLIFIED", oked="62010", vat_registered=False, reporting_period="2026-Q1")
    assert profile.country == "KZ"
    assert profile.vat_registered is False


def test_taxpayer_profile_rejects_missing_regime():
    with pytest.raises(ValidationError):
        TaxpayerProfile(taxpayer_id="t1", taxpayer_type="IE", oked="62010", vat_registered=False, reporting_period="2026-Q1")
