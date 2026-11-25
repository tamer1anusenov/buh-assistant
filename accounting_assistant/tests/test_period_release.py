"""Release checks for draft rules, evidence and durable review history."""
from decimal import Decimal
import json
import sqlite3
from hashlib import sha256
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from accounting_assistant.frontend.period_app import load_rule, read_text_rows
from accounting_assistant.tax_engine.period_balance import PeriodProfile, calculate_period
from accounting_assistant.review.storage import initialize, import_document, latest_rows, save_calculation

ROOT = Path(__file__).resolve().parents[2]
CONTENT = b'Date: 11.11.2026\nAmount: 250000 KZT\nDescription: service\n'


def test_normal_rule_is_draft_and_cannot_produce_payable():
    rule = load_rule()
    assert rule.status == 'draft'
    assert rule.reviewed_by is None
    profile = PeriodProfile(region='Астана', half=2)
    result = calculate_period(read_text_rows(CONTENT, 'sample.txt'), profile, rule)
    assert result.balance_payable is None
    assert result.assessed_tax is None
    assert 'reviewed_rule' in result.missing_information
    assert 'complete_period_income' in result.missing_information
    assert 'payments_made' in result.missing_information


def test_sources_match_saved_hashes():
    folder = ROOT / 'rules' / 'sources'
    for entry in json.loads((folder / 'manifest.json').read_text()):
        assert sha256((folder / entry['snapshot']).read_bytes()).hexdigest() == entry['sha256']
        assert entry['status'] == 'draft'
        assert entry['reviewed_by'] is None


def test_history_is_append_only_and_detects_concurrent_review(tmp_path):
    db = tmp_path / 'history.db'
    initialize(db)
    original = read_text_rows(CONTENT, 'sample.txt')
    import_document(db, 'sample.txt', CONTENT, original)
    reviewed = [original[0].model_copy(update={'operation': 'BUSINESS_INCOME', 'reviewed': True})]
    profile = PeriodProfile(region='Астана', half=2)
    rule = load_rule()
    result = calculate_period(reviewed, profile, rule)
    save_calculation(db, 'reviewer', original, reviewed, profile, rule, result)
    assert latest_rows(db, original) == reviewed
    with pytest.raises(ValueError, match='уже изменена'):
        save_calculation(db, 'second', original, original, profile, rule, result)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM calculations').fetchone()[0] == 1
        for table in ['documents', 'transactions', 'review_decisions', 'calculations']:
            with pytest.raises(sqlite3.IntegrityError, match='append-only'):
                conn.execute(f'DELETE FROM {table}')


def test_unknown_text_is_preserved():
    rows = read_text_rows(b'Unrecognized bank material', 'unknown.txt')
    assert rows[0].amount is None
    assert rows[0].transaction_date is None
    assert rows[0].operation == 'UNKNOWN'
    assert rows[0].passage == 'Unrecognized bank material'


def test_streamlit_entrypoint(tmp_path, monkeypatch):
    from lexaudit.config.settings import get_settings
    monkeypatch.setenv('ACCOUNTING_DATABASE_PATH', str(tmp_path / 'ui.db'))
    get_settings.cache_clear()
    try:
        app = AppTest.from_string('from accounting_assistant.frontend.period_app import main\nmain()').run()
        assert not app.exception
        app.text_input[1].set_value('Reviewer')
        app.button[0].click().run()
        assert not app.exception
        assert any('Нужно больше данных' in item.value for item in app.warning)
    finally:
        get_settings.cache_clear()


def test_upload_review_persists_a_calculation(tmp_path, monkeypatch):
    from io import BytesIO
    import streamlit as st
    from lexaudit.config.settings import get_settings

    content = BytesIO(CONTENT)
    content.name = 'sample.txt'
    content.size = len(CONTENT)
    monkeypatch.setattr(st, 'file_uploader', lambda *args, **kwargs: content)
    def reviewed_table(entries, **kwargs):
        for row in entries:
            row['Решение'] = 'Доход'
        return entries
    monkeypatch.setattr(st, 'data_editor', reviewed_table)
    database = tmp_path / 'upload.db'
    monkeypatch.setenv('ACCOUNTING_DATABASE_PATH', str(database))
    get_settings.cache_clear()
    try:
        app = AppTest.from_string('from accounting_assistant.frontend.period_app import main\nmain()').run()
        assert not app.exception
        app.text_input[1].set_value('Accountant')
        app.selectbox[0].select(2)
        app.button[0].click().run()
        assert not app.exception
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 1
            assert db.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0] == 1
            result = json.loads(db.execute('SELECT result_json FROM calculations').fetchone()[0])
            assert result['balance_payable'] is None
            assert 'reviewed_rule' in result['missing_information']
    finally:
        get_settings.cache_clear()


def test_pipe_statement_layout_parses_fields_and_preserves_unknown():
    from accounting_assistant.frontend.period_app import read_text_rows
    content = ('№ | Дата | Тип | Контрагент | Назначение | Сумма | Валюта\n'
               '1 | 15.04.2026 | Поступление | Клиент А | Оплата счёта | 125 000,50 | KZT\n'
               '2 | неизвестно | ??? | Банк | текст | не указано | ???\n').encode()
    rows = read_text_rows(content, 'statement.txt')
    assert len(rows) == 2
    assert (rows[0].transaction_date.isoformat(), rows[0].amount, rows[0].currency) == ('2026-04-15', Decimal('125000.50'), 'KZT')
    assert rows[0].counterparty == 'Клиент А' and rows[0].operation == 'UNKNOWN'
    assert rows[1].transaction_date is None and rows[1].amount is None and rows[1].operation == 'UNKNOWN'
