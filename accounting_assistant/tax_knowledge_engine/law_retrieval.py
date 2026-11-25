"""Connect transactions and taxpayer profiles to candidate Adilet provisions."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from lexaudit.adilet import FullAct, SearchHit, get_full_text
from lexaudit.adilet.client import AdiletError, AdiletUnavailable

from ..models.tax_analysis import LegalProvisionCandidate, TaxAnalysis
from ..models.taxpayer import TaxpayerProfile
from ..models.transaction import Transaction
from .adilet_search import search_tax_laws
from .evidence_validation import validate_evidence


class TaxLawService:
    """Injectable retrieval service; tax eligibility and calculations are out of scope."""

    def __init__(self, *, search_fn: Callable[..., list[SearchHit]] = search_tax_laws,
                 full_text_fn: Callable[..., FullAct] = get_full_text) -> None:
        self._search_fn = search_fn
        self._full_text_fn = full_text_fn
        self._unavailable = False

    def reset_availability(self) -> None:
        """Allow one new connection attempt for each user-initiated execution."""
        self._unavailable = False

    def analyze_transaction(self, transaction: Transaction, taxpayer: TaxpayerProfile,
                            transaction_date: date | None = None, *, original_text: str | None = None,
                            limit: int = 10) -> TaxAnalysis:
        category = transaction.category or "не определена"
        when = transaction_date or transaction.transaction_date
        if when is None:
            return self._review(transaction, taxpayer, category, "Дата транзакции отсутствует; историческую версию нормы проверить нельзя.")
        if transaction.review_status == "needs_review" or taxpayer.tax_regime.strip() == "":
            return self._review(transaction, taxpayer, category, "Профиль или финансовые данные требуют ручной проверки.")
        query = f"{category} налоговый вычет режим {taxpayer.tax_regime} ОКЭД {taxpayer.oked}"
        if self._unavailable:
            return self._review(transaction, taxpayer, category, "Adilet не отвечает. Операция сохранена; проверку закона повторите позже.")
        try:
            hits = self._search_fn(query, limit=limit)
            candidates: list[LegalProvisionCandidate] = []
            acts: dict[str, FullAct] = {}
            for hit in hits:
                if not hit.in_force:
                    continue
                act = self._full_text_fn(hit.act_id, language="rus")
                acts[act.act_id] = act
                for article in act.articles:
                    article_text = "\n\n".join(filter(None, [article.heading, *article.paragraphs]))
                    candidates.append(LegalProvisionCandidate(act_id=act.act_id, act_title=act.title, article_number=article.number, legal_url=act.url + (f"#{article.anchor}" if article.anchor else ""), article_text=article_text, in_force=act.in_force, version_status="NEEDS_REVIEW"))
                    if len(candidates) >= 3:
                        break
                if len(candidates) >= 3:
                    break
            if not candidates:
                return self._review(transaction, taxpayer, category, "Действующие кандидаты в Adilet не найдены.")
            first = candidates[0]
            first_act = acts[first.act_id]
            check = validate_evidence(search_hits=hits, act=first_act, article_number=first.article_number, evidence_quote=first.article_text, transaction_text=original_text, transaction_date=when)
            return TaxAnalysis(transaction_id=transaction.transaction_id, taxpayer_id=taxpayer.taxpayer_id, relevant_tax_category=category, candidate_legal_provisions=candidates, legal_act_id=first.act_id, legal_act_title=first.act_title, article_number=first.article_number, legal_url=first.legal_url, evidence_quote=first.article_text, source_verification_status=check["status"], analysis_explanation="Найдены кандидатные нормы. Их наличие не устанавливает налоговую применимость или сумму вычета.", needs_review=True)
        except AdiletError as exc:
            if isinstance(exc, AdiletUnavailable):
                self._unavailable = True
            return self._review(transaction, taxpayer, category, f"Источник Adilet недоступен: {type(exc).__name__}.")

    @staticmethod
    def _review(transaction: Transaction, taxpayer: TaxpayerProfile, category: str, explanation: str) -> TaxAnalysis:
        return TaxAnalysis(transaction_id=transaction.transaction_id, taxpayer_id=taxpayer.taxpayer_id, relevant_tax_category=category, source_verification_status="NEEDS_REVIEW", analysis_explanation=explanation, needs_review=True)
