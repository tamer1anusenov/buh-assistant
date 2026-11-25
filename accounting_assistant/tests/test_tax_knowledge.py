from datetime import date

import pytest

from lexaudit.adilet import Article, FullAct, SearchHit
from lexaudit.adilet.client import AdiletUnavailable

from accounting_assistant.models.taxpayer import TaxpayerProfile
from accounting_assistant.models.transaction import Transaction
from accounting_assistant.tax_knowledge_engine.adilet_search import search_tax_laws
from accounting_assistant.tax_knowledge_engine.evidence_validation import validate_evidence
from accounting_assistant.tax_knowledge_engine.law_retrieval import TaxLawService
from accounting_assistant.tax_knowledge_engine.law_versioning import LawVersion, version_for_date


def _hit() -> SearchHit:
    return SearchHit(act_id="K2026000001", title="Налоговый кодекс Республики Казахстан", snippet="налог", url="https://adilet.zan.kz/rus/docs/K2026000001", in_force=True)


def _act() -> FullAct:
    return FullAct(act_id="K2026000001", title="Налоговый кодекс Республики Казахстан", url="https://adilet.zan.kz/rus/docs/K2026000001", in_force=True, fetched_at="2026-01-01T00:00:00+00:00", articles=[Article(number="100", heading="Статья 100", paragraphs=["Расходы учитываются при наличии подтверждающих документов."], anchor="z100")])


def test_search_adapter_scopes_query_and_preserves_hit():
    calls = []
    hits = [_hit()]
    result = search_tax_laws("расходы", search_fn=lambda query, **kwargs: calls.append((query, kwargs)) or hits)
    assert result == hits
    assert "Налоговый кодекс Республики Казахстан" in calls[0][0]
    assert calls[0][1]["language"] == "rus"


def test_evidence_requires_exact_article_quote_and_version():
    result = validate_evidence(search_hits=[_hit()], act=_act(), article_number="100", evidence_quote="Расходы учитываются", transaction_text=None, transaction_date=date(2026, 2, 1), effective_date=date(2026, 1, 1))
    assert result["status"] == "VERSION_VERIFIED"
    invalid = validate_evidence(search_hits=[_hit()], act=_act(), article_number="999", evidence_quote="Расходы", transaction_text=None, transaction_date=date(2026, 2, 1), effective_date=date(2026, 1, 1))
    assert invalid["status"] == "INVALID"


def test_historical_version_without_effective_date_requires_review():
    result = version_for_date(LawVersion(in_force=True), date(2025, 1, 1))
    assert result.status == "NEEDS_REVIEW"
    assert result.applicable is False


def test_service_returns_candidate_evidence_without_tax_decision():
    transaction = Transaction(transaction_id="tx1", transaction_date=date(2026, 2, 1), transaction_type="EXPENSE", description="Office expenses", amount=__import__("decimal").Decimal("100"), currency="KZT", source_document="receipt.txt", category="Office expenses", review_status="ok")
    taxpayer = TaxpayerProfile(taxpayer_id="t1", taxpayer_type="IE", tax_regime="SIMPLIFIED", oked="62010", vat_registered=False, reporting_period="2026-Q1")
    service = TaxLawService(search_fn=lambda *args, **kwargs: [_hit()], full_text_fn=lambda *args, **kwargs: _act())
    result = service.analyze_transaction(transaction, taxpayer)
    assert result.candidate_legal_provisions
    assert result.needs_review is True
    assert result.source_verification_status == "NEEDS_REVIEW"


def test_service_converts_adilet_failure_to_review():
    transaction = Transaction(transaction_id="tx1", transaction_date=date(2026, 2, 1), transaction_type="EXPENSE", description="Office expenses", amount=__import__("decimal").Decimal("100"), currency="KZT", source_document="receipt.txt", category="Office expenses", review_status="ok")
    taxpayer = TaxpayerProfile(taxpayer_id="t1", taxpayer_type="IE", tax_regime="SIMPLIFIED", oked="62010", vat_registered=False, reporting_period="2026-Q1")
    def failing(*args, **kwargs):
        raise AdiletUnavailable("offline")
    result = TaxLawService(search_fn=failing).analyze_transaction(transaction, taxpayer)
    assert result.needs_review is True
    assert "Adilet" in result.analysis_explanation


def test_outage_is_not_retried_for_every_receipt_and_next_run_can_retry():
    from decimal import Decimal

    calls = []
    def unavailable(*args, **kwargs):
        calls.append(1)
        raise AdiletUnavailable("timeout")
    service = TaxLawService(search_fn=unavailable)
    transaction = Transaction(transaction_id="tx-outage", transaction_date=date(2026, 11, 1), transaction_type="EXPENSE", amount=Decimal("100"), category="Rent", source_document="receipt.txt", review_status="ok")
    taxpayer = TaxpayerProfile(taxpayer_id="tp", taxpayer_type="IE", tax_regime="GENERAL", oked="62010", vat_registered=False, reporting_period="2026-11")
    first = service.analyze_transaction(transaction, taxpayer)
    second = service.analyze_transaction(transaction, taxpayer)
    assert first.needs_review and second.needs_review
    assert len(calls) == 1
    assert "Adilet не отвечает" in second.analysis_explanation
    service.reset_availability()
    service.analyze_transaction(transaction, taxpayer)
    assert len(calls) == 2
