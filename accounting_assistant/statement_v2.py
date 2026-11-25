"""Deterministic statement parsing, classification and bounded assessment."""
import json
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

CONFIG = Path(__file__).resolve().parent / 'statement_rules.json'


def parse(content: str):
    rows = []
    for line_number, text in enumerate(content.splitlines(), 1):
        if not text.strip():
            continue
        if '|' not in text and re.fullmatch(
            r'(?:ТЕСТОВАЯ ВЫПИСКА(?:\s*\(.*\))?|'
            r'(?:Владелец сч[её]та|ИИН|Сч[её]т|Период|Валюта сч[её]та):.*|'
            r'Итого строк:\s*\d+|Конец выписки)', text.strip(), re.I,
        ):
            continue
        text = re.sub(r'\bKZ[A-Z0-9]{18}\b|\b\d{12}\b', '[скрыто]', text, flags=re.I)
        cells = [cell.strip() for cell in text.split('|')]
        if cells[0] == '№':
            continue
        row = dict(line=line_number, source=text, number=cells[0], date=None, amount=None, currency='', counterparty='', purpose='', type='', decision='disputed', reason='Нераспознанная строка')
        if len(cells) == 7:
            _, raw_date, row['type'], row['counterparty'], row['purpose'], raw_amount, row['currency'] = cells
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_date):
                    raise ValueError('Invalid date')
                row['date'] = date.fromisoformat(raw_date).isoformat()
            except ValueError:
                pass
            if re.fullmatch(r'\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?', raw_amount):
                row['amount'] = str(Decimal(raw_amount.replace(' ', '').replace('\u00a0', '').replace(',', '.')))
        rows.append(row)
    return rows


def classify(rows):
    config = json.loads(CONFIG.read_text())
    seen = {}
    result = []
    for original in rows:
        row = original.copy()
        fingerprint = tuple(row[key] for key in ('date', 'counterparty', 'purpose', 'amount', 'currency'))
        text = (row['type'] + ' ' + row['purpose']).casefold()
        if row['currency'] and row['currency'] != 'KZT':
            row.update(decision='foreign', reason='Валюта без подтверждённого курса')
        elif row['date'] is None or row['amount'] is None or not row['currency']:
            row.update(decision='disputed', reason='Не распознана дата, сумма или валюта')
        elif fingerprint in seen:
            row.update(decision='duplicate', reason=f"Дубль строки {seen[fingerprint]}")
        else:
            row.update(decision='disputed', reason='Назначение требует уточнения')
            for rule in config:
                if any(re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', text) for word in rule['words']) and (not rule.get('types') or row['type'].casefold() in rule['types']):
                    row.update(decision=rule['decision'], reason=rule['reason'])
                    break
        seen.setdefault(fingerprint, row['line'])
        result.append(row)
    return result


def calculate(rows, rule, region, half, paid=None):
    lower = Decimal('0')
    uncertain = Decimal('0')
    unbounded = False
    foreign_rows = []
    details = []
    for original in rows:
        row = original.copy()
        if row['date'] and (not row['date'].startswith('2026-') or (int(row['date'][5:7]) <= 6) != (half == 1)):
            row.update(decision='excluded', reason='Вне выбранного полугодия')
        amount = Decimal(row['amount']) if row['amount'] is not None else None
        if row['decision'] not in {'excluded', 'duplicate'} and row['currency'] and row['currency'] != 'KZT':
            row.update(decision='foreign', reason='Валюта без курса; исключена из диапазона KZT')
            foreign_rows.append(row.copy())
        elif row['decision'] == 'foreign' or (row['decision'] in {'income', 'disputed'} and row['currency'] != 'KZT'):
            unbounded = True
        elif row['decision'] in {'income', 'disputed'}:
            if amount is None:
                unbounded = True
            elif row['decision'] == 'income' and row['date']:
                lower += amount
            else:
                uncertain += amount
        details.append(row)
    applicable = rule and rule.region == region and rule.effective_from <= date(2026, 1 if half == 1 else 7, 1) and rule.effective_to >= date(2026, 6 if half == 1 else 12, 30 if half == 1 else 31)
    verified = applicable and rule.status == 'verified'
    rate = rule.rate if applicable else None
    def tax(base):
        if base is None or rate is None:
            return None
        value = base * rate
        return str(value.quantize(Decimal(1).scaleb(-rule.rounding_places), rounding=ROUND_HALF_UP) if rule.rounding_places is not None else value)
    high = None if unbounded else lower + uncertain
    low_tax, high_tax = tax(lower), tax(high)
    balance = None
    if paid is not None:
        paid = Decimal(paid)
        if not paid.is_finite() or paid < 0:
            raise ValueError('Уплаченный налог должен быть неотрицательной суммой')
        if verified and high == lower and not foreign_rows:
            balance = str(max(Decimal(low_tax) - paid, Decimal('0')))
    warning = 'Диапазон рассчитан только по KZT-операциям загруженной выписки.'
    if unbounded:
        warning += ' Верхняя граница KZT не определена: есть неизвестная сумма или валюта.'
    if foreign_rows:
        warning += ' Иностранная валюта показана отдельно и не входит в диапазон; общий налог по всей выписке не определён.'
    return dict(status='Расчёт по выписке' if verified else 'Предварительная оценка', base=str(lower), upper_base=str(high) if high is not None else None, tax=low_tax, upper_tax=high_tax, balance_payable=balance, formula=f'{lower} × {rate}' if rate is not None else 'Нет правила для региона и периода', period=f'2026, полугодие {half}', rule_id=rule.rule_id if rule else None, rule_version=rule.version if rule else None, source_url=rule.adilet_url if rule else None, rows=details, foreign_rows=foreign_rows, range_currency='KZT', warning=warning)


def main():
    import argparse
    from accounting_assistant.frontend.period_app import load_rule
    parser = argparse.ArgumentParser(description='Расчёт ИП по TXT-выписке')
    parser.add_argument('file', type=Path)
    parser.add_argument('--region', default='Астана')
    parser.add_argument('--half', type=int, choices=[1, 2], required=True)
    parser.add_argument('--paid')
    args = parser.parse_args()
    print(json.dumps(calculate(classify(parse(args.file.read_text(encoding='utf-8-sig'))), load_rule(), args.region, args.half, args.paid), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
