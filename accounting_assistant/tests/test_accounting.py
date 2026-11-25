import csv
from decimal import Decimal

from accounting_assistant.accounting_engine.classification import classify_transaction
from accounting_assistant.accounting_engine.csv_generator import CSV_COLUMNS, write_csv
from accounting_assistant.document_processor.extraction import extract_transactions


def test_extract_classify_and_export(tmp_path):
    source = tmp_path / "receipts.txt"
    source.write_text("Date: 10.11.2026\nStore: Technodom\nType: Expense\nDescription: Laptop purchase\nAmount: 450000 KZT\nPayment: Kaspi\n", encoding="utf-8")
    transaction = classify_transaction(extract_transactions(source)[0])
    assert transaction.amount == Decimal("450000")
    assert transaction.category == "Equipment"
    output = write_csv([transaction], tmp_path / "accounting.csv")
    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert list(rows[0]) == CSV_COLUMNS
    assert rows[0]["date"] == "2026-11-10"
    assert rows[0]["amount"] == "450000"


def test_missing_values_require_review(tmp_path):
    source = tmp_path / "missing.txt"
    source.write_text("Description: unclear purchase\n", encoding="utf-8")
    transaction = extract_transactions(source)[0]
    assert transaction.amount is None
    assert transaction.transaction_date is None
    assert transaction.review_status == "needs_review"


def test_duplicate_transactions_are_marked(tmp_path):
    source = tmp_path / "duplicates.txt"
    source.write_text("Date: 10.11.2026\nType: Expense\nDescription: Office paper\nAmount: 100 KZT\n\nDate: 10.11.2026\nType: Expense\nDescription: Office paper\nAmount: 100 KZT\n", encoding="utf-8")
    transactions = extract_transactions(source)
    assert transactions[1].duplicate_of == transactions[0].transaction_id
    assert transactions[1].review_status == "needs_review"


def test_zero_receipt_is_preserved_and_does_not_abort_other_receipts(tmp_path):
    from accounting_assistant.review.items import collect_review_items

    source = tmp_path / "zero.txt"
    source.write_text(
        "02.11.2026\nОписание: Продажа\nСумма: 100 KZT\nТип операции: INCOME\n"
        "Способ оплаты: Kaspi QR\n\n"
        "========================\nРАСХОДЫ / ПОКУПКИ И ЗАТРАТЫ\n========================\n\n"
        "05.12.2026\nОписание: Закупка\nСумма: 0 KZT\nТип операции: EXPENSE\n\n"
        "ПРИМЕЧАНИЕ ДЛЯ ТЕСТИРОВАНИЯ:\nЭто проверка нулевой суммы.\n",
        encoding="utf-8",
    )
    transactions = extract_transactions(source)
    assert len(transactions) == 2
    assert transactions[0].transaction_type == "INCOME"
    assert transactions[0].payment_method == "Kaspi QR"
    assert transactions[1].transaction_type == "EXPENSE"
    assert transactions[1].amount == Decimal("0")
    assert transactions[1].review_status == "needs_review"
    assert any(item.problem == "zero_amount" for item in collect_review_items(transactions=transactions))
    output = write_csv(transactions, tmp_path / "zero.csv")
    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[1]["amount"] == "0"


def test_explicit_income_direction_overrides_buyer_word(tmp_path):
    source = tmp_path / "income.txt"
    source.write_text("01.07.2026\nЧек покупателя\nСумма: 350000 KZT\nТип операции: INCOME\n", encoding="utf-8")
    assert extract_transactions(source)[0].transaction_type == "INCOME"
