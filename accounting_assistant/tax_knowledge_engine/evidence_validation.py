"""Validation of source identity, article text, quotes, and historical dates."""
from __future__ import annotations

from datetime import date
from typing import Any

from lexaudit.adilet import FullAct, SearchHit

from .law_versioning import LawVersion, version_for_date


def validate_evidence(*, search_hits: list[SearchHit], act: FullAct, article_number: str,
                      evidence_quote: str, transaction_text: str | None,
                      transaction_quote: str | None = None,
                      transaction_date: date, effective_date: date | None = None,
                      publication_date: date | None = None,
                      expiration_date: date | None = None) -> dict[str, Any]:
    """Return a stateful validation result; never infer substantive applicability."""
    hit = next((item for item in search_hits if item.act_id == act.act_id), None)
    if hit is None or hit.title != act.title or hit.url.split("#", 1)[0] != act.url.split("#", 1)[0] or not hit.in_force or not act.in_force:
        return {"status": "INVALID", "reason": "Источник не совпадает с результатом поиска или не действует."}
    article = next((item for item in act.articles if item.number.rstrip(".") == article_number.strip().rstrip(".")), None)
    if article is None:
        return {"status": "INVALID", "reason": "Статья отсутствует в полученном тексте акта."}
    article_text = "\n\n".join(filter(None, [article.heading, *article.paragraphs]))
    if not evidence_quote or evidence_quote not in article_text:
        return {"status": "INVALID", "reason": "Цитата не является точной подстрокой текста статьи."}
    if transaction_text is not None and transaction_quote is not None and transaction_quote not in transaction_text:
        return {"status": "INVALID", "reason": "Цитата финансового документа отсутствует в исходном тексте."}
    version = version_for_date(LawVersion(publication_date=publication_date, effective_date=effective_date, expiration_date=expiration_date, in_force=act.in_force), transaction_date)
    if version.status != "VERSION_VERIFIED":
        return {"status": "NEEDS_REVIEW", "reason": version.explanation, "article_text": article_text}
    return {"status": "VERSION_VERIFIED", "reason": "Источник, статья, цитата и период проверены.", "article_text": article_text, "article_number": article.number}
