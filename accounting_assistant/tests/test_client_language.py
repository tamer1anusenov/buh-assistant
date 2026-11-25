from decimal import Decimal

from accounting_assistant.report_generator.client_language import category_label, explain_review, tax_amount_label


def test_unknown_tax_is_distinct_from_confirmed_zero():
    assert tax_amount_label(None, "UNSUPPORTED_REGIME") == "Пока не рассчитан"
    assert tax_amount_label(Decimal("0"), "NEEDS_REVIEW") == "Пока не рассчитан"
    assert tax_amount_label(Decimal("0"), "CALCULATED") == "0.00 KZT"


def test_purchase_category_and_missing_rule_are_explained():
    assert category_label("Equipment") == "Оборудование"
    text = explain_review("Нет проверенного расчётного правила для режима.")
    assert "Сумма налога пока неизвестна" in text
