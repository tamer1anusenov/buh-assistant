from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from accounting_assistant.statement_v2 import parse, classify, calculate


def rule(status='verified'):
    return SimpleNamespace(region='test', effective_from=date(2026,1,1), effective_to=date(2026,12,31), status=status, rate=Decimal('.04'), rounding_places=2, rule_id='synthetic-only-test', version=1, adilet_url='https://adilet.zan.kz')


@pytest.mark.parametrize('kind,purpose,decision', [('Поступление','Услуги','income'),('Списание','Услуги','excluded'),('Поступление','Возврат','excluded'),('Поступление','Займ','excluded'),('Поступление','между своими счетами','excluded'),('Поступление','Перевод','disputed'),('Поступление','контакт','disputed')])
def test_configuration(kind,purpose,decision):
    assert classify(parse(f'1 | 2026-01-01 | {kind} | Клиент | {purpose} | 100 | KZT'))[0]['decision'] == decision


def test_arithmetic_draft_paid_and_duplicate():
    rows=classify(parse('1 | 2026-01-01 | Поступление | A | Услуги | 1120000 | KZT\n2 | 2026-02-01 | Поступление | B | Перевод | 80000 | KZT\n3 | 2026-01-01 | Поступление | A | Услуги | 1120000 | KZT'))
    result=calculate(rows,rule(),'test',1)
    assert (result['tax'],result['upper_tax']) == ('44800.00','48000.00')
    assert rows[2]['decision']=='duplicate'
    assert result['balance_payable'] is None
    assert calculate(rows[:1],rule(),'test',1,'0')['balance_payable']=='44800.00'
    assert calculate(rows[:1],rule('draft'),'test',1,'0')['balance_payable'] is None


def test_unknown_and_foreign_do_not_create_false_upper_bound():
    rows=classify(parse('broken\n2 | 2026-02-01 | Поступление | B | Услуги | 100 | USD'))
    assert len(rows)==2
    assert calculate(rows,rule(),'test',1)['upper_tax'] is None


def test_redaction():
    assert '123456789012' not in str(parse('1 | 2026-01-01 | Поступление | 123456789012 | Услуги | 100 | KZT'))


def test_v2_screen_profile_and_upload(tmp_path,monkeypatch):
    import streamlit as st
    from io import BytesIO
    from streamlit.testing.v1 import AppTest
    from lexaudit.config.settings import get_settings
    content=BytesIO(b'1 | 2026-01-01 | Unknown | A | B | 100 | KZT')
    content.name='sample.txt';content.size=len(content.getvalue())
    monkeypatch.setenv('ACCOUNTING_DATABASE_PATH',str(tmp_path/'test.db'))
    monkeypatch.setattr(st,'file_uploader',lambda *a,**k:content)
    get_settings.cache_clear()
    try:
        app=AppTest.from_string('from accounting_assistant.frontend.v2_app import main\nmain()').run()
        assert not app.exception
        app.button[0].click().run()
        assert not app.exception
        assert any(item.value=='Предварительная оценка' for item in app.subheader)
    finally:
        get_settings.cache_clear()


def test_supplied_astana_statement():
    from pathlib import Path
    from accounting_assistant.frontend.period_app import load_rule
    statement = Path(__file__).resolve().parents[2] / 'tests/fixtures/statements/test_statement_ip_h1_2026.txt'
    rows = classify(parse(statement.read_text(encoding='utf-8-sig')))
    assert len(rows) == 12
    assert [row['number'] for row in rows] == [str(number) for number in range(1, 13)]
    assert [row['decision'] for row in rows] == ['income', 'excluded', 'income', 'duplicate', 'excluded', 'excluded', 'excluded', 'excluded', 'income', 'foreign', 'disputed', 'income']
    assert [row['line'] for row in rows] == list(range(9, 21))
    assert rows[8]['purpose'] == 'Оплата услуг по акту №3'
    result = calculate(rows, load_rule(), 'Астана', 1, '0')
    assert Decimal(result['base']) == Decimal('1120000')
    assert Decimal(result['upper_base']) == Decimal('1200000')
    assert Decimal(result['tax']) == Decimal('33600')
    assert Decimal(result['upper_tax']) == Decimal('36000')
    assert result['status'] == 'Предварительная оценка'
    assert result['balance_payable'] is None
    assert len(result['foreign_rows']) == 1
    assert result['foreign_rows'][0]['number'] == '10'
    assert result['foreign_rows'][0]['currency'] == 'USD'
    assert result['range_currency'] == 'KZT'


def test_foreign_currency_separate_even_when_rule_verified():
    rows = classify(parse('1 | 2026-01-01 | Поступление | A | Услуги | 100 | KZT\n2 | 2026-02-01 | Поступление | B | Services | 100 | USD'))
    result = calculate(rows, rule(), 'test', 1, '0')
    assert result['tax'] == result['upper_tax'] == '4.00'
    assert result['balance_payable'] is None
    assert len(result['foreign_rows']) == 1
    assert calculate(rows, rule(), 'test', 2)['foreign_rows'] == []


def test_metadata_filter_preserves_broken_transactions():
    content = 'Владелец счета: ИП Тест\nПериод: 01.01.2026 - 30.06.2026\n1 | broken\nНеизвестная строка\nИтого строк: 1\nКонец выписки'
    rows = classify(parse(content))
    assert [row['line'] for row in rows] == [3, 4]
    assert all(row['decision'] == 'disputed' for row in rows)
    assert calculate(rows, rule(), 'test', 1)['upper_tax'] is None


@pytest.mark.parametrize('purpose', ['Оплата услуг по акту №3', 'Оплата по акту №5', 'Оплата по договору', 'Оплата по счёту'])
def test_explicit_inflected_income_words(purpose):
    assert classify(parse(f'1 | 2026-01-01 | Поступление | Клиент | {purpose} | 100 | KZT'))[0]['decision'] == 'income'


def test_supplied_statement_in_screen(tmp_path, monkeypatch):
    import json
    import sqlite3
    from io import BytesIO
    from pathlib import Path
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from lexaudit.config.settings import get_settings

    path = Path(__file__).resolve().parents[2] / 'tests/fixtures/statements/test_statement_ip_h1_2026.txt'
    content = BytesIO(path.read_bytes())
    content.name = path.name
    content.size = len(content.getvalue())
    database = tmp_path / 'screen.db'
    monkeypatch.setenv('ACCOUNTING_DATABASE_PATH', str(database))
    monkeypatch.setattr(st, 'file_uploader', lambda *args, **kwargs: content)
    get_settings.cache_clear()
    try:
        app = AppTest.from_string('from accounting_assistant.frontend.v2_app import main\nmain()').run()
        app.button[0].click().run()
        assert not app.exception
        assert [Decimal(item.value) for item in app.metric] == [Decimal('33600'), Decimal('36000')]
        with sqlite3.connect(database) as db:
            result = json.loads(db.execute("SELECT payload FROM v2_events WHERE kind='calculation' ORDER BY id DESC LIMIT 1").fetchone()[0])['result']
        assert len(result['rows']) == 12
        assert result['foreign_rows'][0]['number'] == '10'
        assert result['balance_payable'] is None
    finally:
        get_settings.cache_clear()
