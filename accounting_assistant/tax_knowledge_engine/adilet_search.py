"""Small adapter around the existing LexAudit Adilet client."""
from __future__ import annotations

from collections.abc import Callable

from lexaudit.adilet import SearchHit, search_laws

SearchFn = Callable[..., list[SearchHit]]


def search_tax_laws(query: str, *, limit: int = 10, search_fn: SearchFn = search_laws) -> list[SearchHit]:
    """Search official Adilet results with a Tax Code-focused query.

    The adapter never creates act IDs or article numbers. Search failures are
    allowed to propagate as the typed Adilet exceptions from the legacy client.
    """
    if not query.strip():
        raise ValueError("tax-law query must not be empty")
    scoped_query = f"Налоговый кодекс Республики Казахстан с 1 января 2026 года {query.strip()}"
    return search_fn(scoped_query, limit=limit, language="rus")
