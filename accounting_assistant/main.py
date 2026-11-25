"""Small CLI for the first accounting vertical slice."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models.taxpayer import TaxpayerProfile
from .workflow import run_workflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract TXT transactions and write accounting CSV")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("accounting.csv"))
    parser.add_argument("--profile", type=Path, help="taxpayer profile JSON; enables tax reporting")
    parser.add_argument("--period", help="reporting period in YYYY-MM format")
    parser.add_argument("--out-dir", type=Path, help="directory for tax reports")
    parser.add_argument("--llm", action="store_true", help="use configured LLM for incomplete transaction extraction")
    args = parser.parse_args()
    if not args.profile:
        result = run_workflow(args.inputs, out_dir=args.out.parent)
        source = Path(result.generated_files["accounting"])
        if source != args.out:
            args.out.write_bytes(source.read_bytes())
        print(f"Extracted {result.transactions_extracted} transaction(s) to {args.out}")
        return
    profile = TaxpayerProfile.model_validate(json.loads(args.profile.read_text(encoding="utf-8")))
    result = run_workflow(args.inputs, profile=profile, reporting_period=args.period, out_dir=args.out_dir or args.out.parent, use_llm=args.llm, llm_client=None)
    print(f"Extracted: {result.transactions_extracted}")
    print(f"Classified: {result.transactions_classified}")
    print(f"Duplicates: {result.duplicates_detected}")
    print(f"Tax eligible: {result.tax_eligible_transactions}")
    print(f"Review required: {result.review_transactions}")
    print(f"Tax calculation: {result.tax_calculation_status}")
    for path in result.generated_files.values():
        print(path)


if __name__ == "__main__":
    main()
