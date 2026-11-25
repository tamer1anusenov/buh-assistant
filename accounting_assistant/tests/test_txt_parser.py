from decimal import Decimal

from accounting_assistant.document_processor.txt_parser import parse_amount, parse_date, split_records


def test_parse_dates_and_amounts():
    assert str(parse_date("10.11.2026")) == "2026-11-10"
    assert str(parse_date("11 November 2026")) == "2026-11-11"
    assert parse_amount("450 000,50 KZT") == (Decimal("450000.50"), "KZT")


def test_split_structured_records():
    text = "Date: 10.11.2026\nAmount: 100 KZT\n\nDate: 11.11.2026\nAmount: 200 KZT"
    assert len(split_records(text)) == 2
