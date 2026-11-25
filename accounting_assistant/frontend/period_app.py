"""Half-year review screen; all tax arithmetic belongs to the calculator."""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path

import streamlit as st
from pydantic import ValidationError
from lexaudit.config.settings import get_settings
from accounting_assistant.review.storage import initialize, import_document, latest_rows, save_calculation

from accounting_assistant.document_processor.txt_parser import parse_record, split_records, parse_date, parse_amount
from accounting_assistant.tax_engine.period_balance import EvidenceRow, PeriodProfile, calculate_period


REASONS = {
    "income_recognition": "Подтвердите суммы и даты признания доходов по первичным документам, включая ещё не оплаченные доходы.",
    "reviewed_rule": "Правило не подтверждено человеком. Итоговая сумма к уплате недоступна.",
    "applicable_rule": "Нет правила для выбранного региона и полугодия.",
    "eligibility_evidence": "Подтвердите право на режим и укажите основание.",
    "employee_obligations_review": "Нужно уточнить обязательства по работникам.",
    "no_transactions": "Не загружены операции.",
    "complete_period_income": "Не подтверждена полнота доходов за полугодие.",
    "payments_made": "Укажите уплаченный налог за этот период, включая ноль.",
    "duplicate": "Возможный дубль операции",
    "review": "Не определено решение по операции",
    "currency": "Валюта операции отличается от KZT или отсутствует",
    "date": "Не распознана дата операции",
    "amount": "Не распознана сумма операции",
}
DECISIONS = {"Неопределённо": "UNKNOWN", "Доход": "BUSINESS_INCOME", "Не доход": "NON_INCOME"}


def parse_statement_table(text: str) -> list[dict]:
    """Parse the explicit pipe-separated statement layout without inference."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = []
    for line in lines:
        columns = [part.strip() for part in line.strip().strip("|").split("|")]
        if columns and columns[0].casefold() in {"№", "номер", "no", "id"}:
            continue
        if len(columns) != 7:
            continue
        number, date_text, operation, counterparty, purpose, amount_text, currency = columns
        if not number.isdigit():
            continue
        amount, parsed_currency = parse_amount(f"{amount_text} {currency}")
        date_value = parse_date(date_text)
        operation_lower = operation.casefold()
        rows.append({
            "number": number,
            "transaction_date": date_value,
            "amount": amount,
            "currency": parsed_currency or (currency.upper() if currency else ""),
            "counterparty": counterparty,
            "purpose": purpose,
            "passage": line,
            "operation": "UNKNOWN",
        })
    return rows


def read_text_rows(content: bytes, filename: str) -> list[EvidenceRow]:
    """Read pipe-table statements or explicit-field UTF-8 TXT records."""
    text = content.decode("utf-8-sig")
    digest = sha256(content).hexdigest()
    table = parse_statement_table(text)
    rows = []
    if table:
        for index, item in enumerate(table, 1):
            rows.append(EvidenceRow(
                transaction_id=f"{digest}:1:{index}", document_sha256=digest,
                page=1, passage=item["passage"], transaction_date=item["transaction_date"],
                amount=item["amount"], currency=item["currency"], counterparty=item["counterparty"],
                purpose=item["purpose"], operation="UNKNOWN",
            ))
        return rows
    for page, page_text in enumerate(text.split("\f"), 1):
        for index, passage in enumerate(split_records(page_text), 1):
            parsed = parse_record(passage, filename, index)
            rows.append(EvidenceRow(
                transaction_id=f"{digest}:{page}:{index}", document_sha256=digest,
                page=page, passage=passage, transaction_date=parsed.get("transaction_date"),
                amount=parsed.get("amount"), currency=parsed.get("currency") or "",
                counterparty=parsed.get("counterparty") or "", purpose=parsed.get("description") or "",
                operation="UNKNOWN",
            ))
    return rows


def main() -> None:
    st.set_page_config(page_title="ИП · 910.00", layout="wide")
    st.title("ИП на упрощённой декларации · 910.00 · 2026")
    st.caption("Справочный расчёт. Не является налоговой консультацией.")
    st.info("Банковский PDF-парсер ожидает образец выписки. Для проверки экрана доступен учебный TXT-файл.")
    uploaded = st.file_uploader("Документ TXT", type=["txt"])
    half = st.selectbox("Полугодие 2026", [1, 2])
    region = st.text_input("Регион / маслихат", value="Астана")
    reviewer = st.text_input("Кто проверяет операции")
    paid = st.text_input("Уже уплаченный налог за полугодие, KZT", placeholder="Укажите 0, если налог не уплачен")
    complete = st.checkbox("Загружен весь доход за выбранное полугодие")
    recognition = st.checkbox("Суммы и даты признания доходов сверены с первичными документами, включая неоплаченные доходы")
    eligible = st.checkbox("Подтверждаю право ИП применять упрощённую декларацию")
    basis = st.text_input("Основание подтверждения права на режим")
    employees = st.selectbox("Работники", ["Не указано", "Нет", "Есть"])
    database = get_settings().ACCOUNTING_DATABASE_PATH
    initialize(database)
    rows = []
    if uploaded:
        if uploaded.size > 10 * 1024 * 1024:
            st.error("Размер файла превышает 10 МБ.")
            return
        try:
            rows = read_text_rows(uploaded.getvalue(), uploaded.name)
            import_document(database, uploaded.name, uploaded.getvalue(), rows)
            rows = latest_rows(database, rows)
        except (UnicodeError, ValidationError, ValueError) as exc:
            st.error(f"Не удалось прочитать документ: {exc}")
            return
    entries = [{"ID": row.transaction_id, "Дата": row.transaction_date.isoformat() if row.transaction_date else "", "Сумма": str(row.amount) if row.amount is not None else "", "Валюта": row.currency, "Контрагент": row.counterparty, "Назначение": row.purpose, "Страница": row.page, "Фрагмент": row.passage, "Решение": next((label for label, value in DECISIONS.items() if value == row.operation and row.reviewed), "Неопределённо")} for row in rows]
    edited = st.data_editor(entries, disabled=["ID", "Страница", "Фрагмент"], column_config={"Решение": st.column_config.SelectboxColumn(options=list(DECISIONS), required=True)}, key="rows_" + (sha256(uploaded.getvalue()).hexdigest() if uploaded else "empty")) if entries else []
    if st.button("Проверить и рассчитать", type="primary"):
        if not reviewer.strip():
            st.error("Укажите, кто проверяет операции.")
            return
        try:
            reviewed = []
            for original, item in zip(rows, edited):
                payload = original.model_dump(mode="json")
                payload.update(transaction_date=item["Дата"] or None, amount=item["Сумма"] or None, currency=item["Валюта"], counterparty=item["Контрагент"], purpose=item["Назначение"], operation=DECISIONS[item["Решение"]], reviewed=item["Решение"] != "Неопределённо")
                reviewed.append(EvidenceRow.model_validate_json(json.dumps(payload)))
            profile = PeriodProfile(region=region, half=half, eligibility_confirmed=eligible, eligibility_evidence=basis, has_employees={"Нет": False, "Есть": True, "Не указано": None}[employees], income_recognition_confirmed=recognition, complete_income_confirmed=complete, payments_made=Decimal(paid.replace(",", ".")) if paid.strip() else None)
            rule = load_rule()
            result = calculate_period(reviewed, profile, rule)
            calculation_id = save_calculation(database, reviewer, rows, reviewed, profile, rule, result)
        except (ValidationError, ValueError, InvalidOperation, sqlite3.Error, OSError) as exc:
            st.error(f"Проверьте введённые данные: {exc}")
            return
        st.caption(f"Расчёт сохранён: {calculation_id}")
        if result.status == "CALCULATED":
            st.metric("Остаток к уплате, KZT", str(result.balance_payable))
            st.write(result.period, result.formula)
            st.write(f"Переплата: {result.overpayment} KZT")
            st.link_button("Правовое основание", result.legal_url)
        else:
            st.warning("Нужно больше данных")
            for reason in result.missing_information:
                key, _, identifier = reason.partition(":")
                st.write(REASONS.get(key, key) + (f" · {identifier}" if identifier else ""))
        st.download_button("Скачать результат JSON", result.model_dump_json(indent=2), "period_result.json", "application/json")


def load_rule():
    from accounting_assistant.tax_engine.period_balance import Rule
    path = Path(__file__).resolve().parents[2] / "rules" / "astana_2026.json"
    if not path.exists():
        return None
    rule = Rule.model_validate_json(path.read_text(encoding="utf-8"))
    sources = path.parent / "sources"
    manifest = json.loads((sources / "manifest.json").read_text(encoding="utf-8"))
    source = next((entry for entry in manifest if entry["url"] == rule.adilet_url and entry["sha256"] == rule.source_sha256), None)
    if source is None or sha256((sources / source["snapshot"]).read_bytes()).hexdigest() != rule.source_sha256:
        raise ValueError("Снимок правового источника отсутствует или изменён")
    return rule
