"""Fail release until a human rule and independent control case are present."""
import json
from pathlib import Path
from accounting_assistant.frontend.period_app import load_rule
from accounting_assistant.statement_v2 import parse, classify, calculate


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Проверка допуска к релизу')
    parser.add_argument('statement', type=Path)
    parser.add_argument('approval', type=Path)
    args = parser.parse_args()
    rule = load_rule()
    if not rule or rule.status != 'verified':
        parser.exit(1, 'Релиз запрещён: правило не подтверждено человеком.\n')
    approval = json.loads(args.approval.read_text())
    required = ['reviewed_by','reviewed_on','expected_tax','expected_upper_tax','rule_id','rule_version','half','region']
    if any(approval.get(key) is None or approval.get(key) == '' for key in required):
        parser.exit(1, 'Релиз запрещён: независимая сверка не заполнена.\n')
    result = calculate(classify(parse(args.statement.read_text(encoding='utf-8-sig'))), rule, approval['region'], approval['half'])
    if any(result[key] != approval[expected] for key, expected in [('tax','expected_tax'),('upper_tax','expected_upper_tax'),('rule_id','rule_id'),('rule_version','rule_version')]):
        parser.exit(1, 'Релиз запрещён: контрольный результат расходится.\n')
    print('Правило и контрольный расчёт подтверждены. Перед релизом выполните полный набор тестов.')


if __name__ == '__main__':
    main()
