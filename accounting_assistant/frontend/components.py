"""Reusable rendering helpers for the Streamlit page."""
from __future__ import annotations

import io
import json
from typing import Any

import pandas as pd
import streamlit as st
from accounting_assistant.report_generator.client_language import STATUSES


def render_metric_row(summary: dict[str, Any], calculation: dict[str, Any], accounting: pd.DataFrame) -> None:
    income = accounting.loc[accounting["transaction_type"] == "INCOME", "amount"].sum() if not accounting.empty else 0
    expenses = accounting.loc[accounting["transaction_type"] == "EXPENSE", "amount"].sum() if not accounting.empty else 0
    cols = st.columns(7)
    values = [summary.get("transactions_extracted", 0), income, expenses, calculation.get("total_eligible_deductions", "—"), calculation.get("total_non_deductible_expenses", "—"), summary.get("review_transactions", 0), calculation.get("status", "—")]
    values[-1] = STATUSES.get(calculation.get("status"), "Нужно уточнение")
    if calculation.get("status") not in {"CALCULATED", "EMPTY_PERIOD"}:
        values[3:5] = ["На проверке", "На проверке"]
    labels = ["Транзакции", "Доход", "Расходы", "Допустимые вычеты", "Недопустимые расходы", "На проверке", "Статус расчёта"]
    for column, label, value in zip(cols, labels, values):
        column.metric(label, value)


def dataframe_from_artifacts(artifacts: dict[str, bytes], name: str) -> pd.DataFrame:
    payload = artifacts.get(name, b"")
    return pd.read_csv(io.BytesIO(payload)) if payload else pd.DataFrame()


def json_from_artifacts(artifacts: dict[str, bytes], name: str) -> dict[str, Any]:
    payload = artifacts.get(name, b"{}")
    return json.loads(payload.decode("utf-8")) if payload else {}


def download_button(label: str, artifacts: dict[str, bytes], key: str, filename: str, mime: str) -> None:
    if key in artifacts:
        st.download_button(label, data=artifacts[key], file_name=filename, mime=mime, key=f"download_{key}")
