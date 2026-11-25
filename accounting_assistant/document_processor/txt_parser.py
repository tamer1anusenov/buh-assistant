"""Deterministic TXT transaction parser for structured and natural-language input."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_DATE_RE = re.compile(r"(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{4})")
_WORD_DATE_RE = re.compile(r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-zА-Яа-яёЁ]+)\s+(?P<year>\d{4})", re.I)
_AMOUNT_RE = re.compile(r"(?P<amount>\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?P<currency>KZT|ТГ|₸|тенге|USD|EUR)?", re.I)
_KEY_RE = re.compile(r"^\s*(?P<key>[A-Za-zА-Яа-яЁё_ -]+?)\s*:\s*(?P<value>.*?)\s*$")


def _is_document_note(record: str) -> bool:
    """Exclude explicit standalone headings/notes, retaining uncertain receipts."""
    lines = [line.strip() for line in record.splitlines() if line.strip()]
    content = [line for line in lines if not re.fullmatch(r"[=\-_*]+", line)]
    if not content:
        return True
    if re.match(r"(?i)^примечание(?:\s+для\s+тестирования)?\s*:", content[0]):
        return True
    return len(content) == 1 and content[0].casefold() in {
        "расходы / покупки и затраты", "расходы", "доходы", "покупки и затраты",
    }


def split_records(text: str) -> list[str]:
    """Split a TXT file into records without inventing record boundaries."""
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    records = re.split(r"\n\s*\n+", normalized)
    if len(records) > 1:
        return [record.strip() for record in records if record.strip() and not _is_document_note(record)]
    starts = list(re.finditer(r"(?im)^\s*(?:date|дата)\s*:", normalized))
    if len(starts) > 1:
        return [normalized[m.start():starts[i + 1].start()].strip() for i, m in enumerate(starts[:-1])] + [normalized[starts[-1].start():].strip()]
    return [normalized]


def parse_date(value: str) -> date | None:
    match = _DATE_RE.search(value)
    if match:
        try:
            return date(int(match["year"]), int(match["month"]), int(match["day"]))
        except ValueError:
            return None
    match = _WORD_DATE_RE.search(value)
    if match:
        month = _MONTHS.get(match["month"].casefold())
        if month:
            try:
                return date(int(match["year"]), month, int(match["day"]))
            except ValueError:
                return None
    return None


def parse_amount(value: str) -> tuple[Decimal | None, str | None]:
    matches = list(_AMOUNT_RE.finditer(value))
    if not matches:
        return None, None
    match = next((candidate for candidate in matches if candidate["currency"]), matches[-1])
    raw = re.sub(r"\s+", "", match["amount"]).replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None, None
    currency = match["currency"]
    if currency:
        currency = "KZT" if currency.casefold() in {"тг", "₸", "тенге"} else currency.upper()
    return amount, currency


def parse_record(record: str, source_document: str, index: int) -> dict[str, object]:
    """Extract only explicit fields; unresolved values remain ``None``."""
    fields: dict[str, str] = {}
    free_text: list[str] = []
    for line in record.splitlines():
        match = _KEY_RE.match(line)
        if match:
            key = re.sub(r"\s+", "_", match["key"].strip().casefold())
            fields[key] = match["value"].strip()
        elif line.strip():
            free_text.append(line.strip())
    combined = " ".join(free_text)
    date_value = parse_date(fields.get("date", fields.get("дата", ""))) or parse_date(combined)
    amount, currency = parse_amount(fields.get("amount", fields.get("сумма", "")))
    if amount is None:
        amount, currency = parse_amount(combined)
    type_value = fields.get("type") or fields.get("тип") or fields.get("тип_операции") or ""
    lowered = f"{type_value} {combined}".casefold()
    transaction_type = "INCOME" if re.search(r"income|доход|получил|получено|received|выруч", lowered) else None
    if re.search(r"expense|расход|покуп|оплат|купил|списан", lowered):
        transaction_type = "EXPENSE"
    # An explicit direction takes precedence over words in the receipt body.
    explicit_types = {"income": "INCOME", "доход": "INCOME", "expense": "EXPENSE", "расход": "EXPENSE"}
    transaction_type = explicit_types.get(type_value.casefold(), transaction_type)
    return {
        "transaction_id": f"tx_{index:04d}",
        "transaction_date": date_value,
        "transaction_type": transaction_type,
        "counterparty": fields.get("store") or fields.get("магазин") or fields.get("counterparty") or fields.get("контрагент"),
        "bin_iin": fields.get("bin_iin") or fields.get("бин_иин") or fields.get("bin") or fields.get("iin"),
        "description": fields.get("description") or fields.get("описание") or (combined or None),
        "amount": amount,
        "currency": fields.get("currency") or fields.get("валюта") or currency,
        "vat_amount": parse_amount(fields.get("vat_amount", fields.get("ндс", "")))[0],
        "payment_method": fields.get("payment") or fields.get("оплата") or fields.get("payment_method") or fields.get("способ_оплаты"),
        "business_purpose": fields.get("business_purpose") or fields.get("назначение") or fields.get("цель"),
        "source_document": source_document,
    }
