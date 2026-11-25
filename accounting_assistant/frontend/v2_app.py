"""Automatic statement assessment with optional decisions and append-only history."""
import json
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256

import streamlit as st

from accounting_assistant.statement_v2 import parse, classify, calculate
from accounting_assistant.frontend.period_app import load_rule
from lexaudit.config.settings import get_settings

LABELS = {'income':'Доход', 'excluded':'Не доход', 'disputed':'Спорная', 'duplicate':'Дубль', 'foreign':'Валюта без курса'}


def connect():
    path = get_settings().ACCOUNTING_DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS v2_events (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)')
    for action in ('UPDATE', 'DELETE'):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS v2_no_{action} BEFORE {action} ON v2_events BEGIN SELECT RAISE(ABORT, 'append-only'); END")
    return db


def append(db, kind, payload):
    db.execute('INSERT INTO v2_events(kind, created_at, payload) VALUES (?, ?, ?)', (kind, datetime.now(timezone.utc).isoformat(), json.dumps(payload, ensure_ascii=False)))
    db.commit()


def main():
    st.set_page_config(page_title='ИП · 910.00', layout='wide')
    st.title('Налог по упрощённой декларации · 2026')
    st.caption('Справочный расчёт по загруженной выписке. Спорные операции показаны отдельно.')
    db = connect()
    try:
        saved = db.execute("SELECT payload FROM v2_events WHERE kind='profile' ORDER BY id DESC LIMIT 1").fetchone()
        profile = json.loads(saved[0]) if saved else None
        with st.expander('Профиль ИП', expanded=profile is None):
            with st.form('profile'):
                st.write('Режим — упрощённая декларация')
                region = st.text_input('Регион', value=profile['region'] if profile else 'Астана')
                employees = st.radio('Есть работники?', ['Нет', 'Да'], index=1 if profile and profile['employees'] else 0)
                if st.form_submit_button('Сохранить профиль'):
                    profile = dict(region=region, employees=employees == 'Да', regime='simplified_declaration')
                    append(db, 'profile', profile)
        if profile is None:
            st.info('Сохраните профиль один раз перед загрузкой выписки.')
            return
        half = st.selectbox('Полугодие 2026', [1, 2])
        uploaded = st.file_uploader('TXT-выписка', type=['txt'])
        paid = st.text_input('Уже уплачено, KZT — необязательно', placeholder='Пусто, если нужен только налог за период')
        if not uploaded:
            return
        if uploaded.size > 10 * 1024 * 1024:
            st.error('Файл превышает 10 МБ')
            return
        try:
            rows = classify(parse(uploaded.getvalue().decode('utf-8-sig')))
            key = sha256(uploaded.getvalue()).hexdigest()
            previous = db.execute("SELECT payload FROM v2_events WHERE kind='calculation' ORDER BY id DESC").fetchall()
            stored = next((json.loads(item[0]) for item in previous if json.loads(item[0]).get('document') == key and json.loads(item[0]).get('half') == half), None)
            corrections = stored.get('corrections', {}) if stored else {}
            with st.expander('Операции и добровольные исправления'):
                table = [dict(Строка=row['line'], Дата=row['date'] or 'Неопределённо', Сумма=row['amount'] or 'Неопределённо', Валюта=row['currency'], Контрагент=row['counterparty'], Назначение=row['purpose'], Фрагмент=row['source'], Причина=row['reason'], Решение=corrections.get(str(row['line']), LABELS[row['decision']])) for row in rows]
                edited = st.data_editor(table, disabled=['Строка','Дата','Сумма','Валюта','Контрагент','Назначение','Фрагмент','Причина'], column_config={'Решение':st.column_config.SelectboxColumn(options=list(LABELS.values()), required=True)}, key=f'{key}_{half}_range_fix')
            reverse = {label: value for value, label in LABELS.items()}
            corrections = {}
            for row, item in zip(rows, edited):
                decision = reverse[item['Решение']]
                if decision != row['decision']:
                    corrections[str(row['line'])] = item['Решение']
                    row.update(decision=decision, reason='Исправлено пользователем')
            rule = load_rule()
            result = calculate(rows, rule, profile['region'], half, paid.replace(',', '.') if paid.strip() else None)
            payload = dict(document=key, half=half, profile=profile, corrections=corrections, rule=rule.model_dump(mode='json') if rule else None, result=result)
            latest = db.execute("SELECT payload FROM v2_events WHERE kind='calculation' ORDER BY id DESC LIMIT 1").fetchone()
            if not latest or json.loads(latest[0]) != payload:
                append(db, 'calculation', payload)
            st.subheader(result['status'])
            columns = st.columns(2)
            columns[0].metric('Налог по подтверждённой базе, KZT', result['tax'] or 'Нет применимого правила')
            columns[1].metric('Верхняя граница по KZT-операциям', result['upper_tax'] or 'Не определена')
            st.write(result['formula'], result['period'])
            st.info(result['warning'])
            if result['foreign_rows']:
                st.write('Иностранная валюта вне диапазона KZT')
                st.dataframe([{'№ операции': row['number'], 'Строка файла': row['line'], 'Сумма': row['amount'], 'Валюта': row['currency'], 'Причина': row['reason']} for row in result['foreign_rows']], hide_index=True)
            if result['balance_payable'] is not None:
                st.metric('Остаток к уплате, KZT', result['balance_payable'])
            if result['source_url']:
                st.link_button('Правовое основание', result['source_url'])
            st.dataframe([{'Строка':r['line'], 'Решение':LABELS.get(r['decision'],r['decision']), 'Причина':r['reason']} for r in result['rows'] if r['decision'] != 'income'], hide_index=True)
            st.download_button('Результат JSON', json.dumps(result, ensure_ascii=False, indent=2), 'result.json')
        except (ValueError, UnicodeError, OSError) as exc:
            st.error(f'Не удалось обработать выписку: {exc}')
        with st.expander('История расчётов'):
            for identifier, timestamp, payload in db.execute("SELECT id, created_at, payload FROM v2_events WHERE kind='calculation' ORDER BY id DESC LIMIT 20"):
                with st.expander(f'Расчёт {identifier} · {timestamp}'):
                    st.json(json.loads(payload)['result'])
    finally:
        db.close()
