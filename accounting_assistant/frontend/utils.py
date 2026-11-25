"""Streamlit-independent frontend helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def validate_uploads(files: Iterable[tuple[str, int]]) -> list[str]:
    errors: list[str] = []
    for name, size in files:
        if Path(name).suffix.casefold() != ".txt":
            errors.append(f"{name}: поддерживаются только TXT-файлы.")
        if size > MAX_UPLOAD_BYTES:
            errors.append(f"{name}: размер превышает 10 MB.")
        if size == 0:
            errors.append(f"{name}: файл пуст.")
    return errors


def safe_filename(name: str) -> str:
    """Keep only a basename and use a stable fallback for unsafe names."""
    candidate = Path(name).name
    return candidate if candidate and candidate not in {".", ".."} else "receipt.txt"
