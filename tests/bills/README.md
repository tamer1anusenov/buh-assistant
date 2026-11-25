# Bill test corpus

These TXT fixtures are for local pipeline and edge-case testing. They contain
synthetic data and must not be treated as accounting records.

| File | Scenario |
|---|---|
| `01_structured_receipt.txt` | Complete structured expense with VAT |
| `02_unstructured_income.txt` | Natural-language income |
| `03_missing_date.txt` | Missing date |
| `04_missing_amount.txt` | Missing amount |
| `05_duplicate_receipts.txt` | Duplicate transactions |
| `06_multiple_currencies.txt` | USD and KZT transactions |
| `07_personal_expense.txt` | Personal expense and missing business purpose |
| `08_equipment_purchase.txt` | Equipment/fixed-asset review case |
| `09_mixed_transactions.txt` | Income, software expense, and incomplete-purpose expense |
| `10_russian_receipt.txt` | Russian field names and тенге |
| `11_ambiguous_text.txt` | Ambiguous amount and business purpose |
| `12_invalid_values.txt` | Invalid date and unavailable amount |
