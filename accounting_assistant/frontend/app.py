"""Minimal Streamlit frontend for the accounting assistant workflow."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from accounting_assistant.models.taxpayer import TaxpayerProfile
from accounting_assistant.workflow import run_workflow
from accounting_assistant.report_generator.client_language import category_label, explain_review, tax_amount_label, STATUSES
from accounting_assistant.frontend.components import dataframe_from_artifacts, download_button, json_from_artifacts, render_metric_row
from accounting_assistant.frontend.utils import safe_filename, validate_uploads


def _profile_form() -> dict[str, object]:
    with st.sidebar:
        st.header("Профиль налогоплательщика")
        taxpayer_id = st.text_input("Идентификатор налогоплательщика")
        type_label = st.selectbox("Тип налогоплательщика", ["", "Individual / Физлицо", "IE / ИП", "LLP / ТОО"])
        regime = st.text_input("Налоговый режим", help="Режим не назначается автоматически.")
        oked = st.text_input("ОКЭД")
        vat = st.radio("Плательщик НДС", ["Нет", "Да"], horizontal=True) == "Да"
        period = st.text_input("Отчётный период", placeholder="2026-11")
        country = st.text_input("Страна", value="Kazakhstan", disabled=True)
    type_map = {"Individual / Физлицо": "INDIVIDUAL", "IE / ИП": "IE", "LLP / ТОО": "LLP"}
    return {"taxpayer_id": taxpayer_id, "taxpayer_type": type_map.get(type_label, ""), "tax_regime": regime, "oked": oked, "vat_registered": vat, "reporting_period": period, "country": "KZ" if country else ""}


def _validate_profile(payload: dict[str, object]) -> TaxpayerProfile | None:
    try:
        return TaxpayerProfile.model_validate(payload)
    except Exception as exc:
        st.error(f"Профиль заполнен некорректно: {exc}")
        return None


def _run_analysis(uploaded: list[object], profile: TaxpayerProfile, period: str, use_llm: bool) -> None:
    errors = validate_uploads([(getattr(item, "name", "receipt.txt"), len(item.getvalue())) for item in uploaded])
    if errors:
        for error in errors:
            st.error(error)
        return
    with st.status("Обработка чеков и правовой анализ...", expanded=True) as status:
        try:
            with tempfile.TemporaryDirectory(prefix="accounting_assistant_") as temp:
                input_paths: list[Path] = []
                for item in uploaded:
                    path = Path(temp) / safe_filename(getattr(item, "name", "receipt.txt"))
                    path.write_bytes(item.getvalue())
                    input_paths.append(path)
                result = run_workflow(input_paths, profile=profile, reporting_period=period, out_dir=Path(temp) / "reports", use_llm=use_llm)
                artifacts = {key: Path(path).read_bytes() for key, path in result.generated_files.items() if Path(path).exists()}
            st.session_state["workflow_result"] = result.model_dump()
            st.session_state["workflow_artifacts"] = artifacts
            status.update(label=f"Готово: {result.status}", state="complete")
        except Exception:
            status.update(label="Обработка завершилась ошибкой", state="error")
            st.error("Не удалось завершить анализ. Проверьте входные TXT-файлы, профиль и доступность внешних сервисов.")


def _render_results() -> None:
    result = st.session_state.get("workflow_result")
    artifacts = st.session_state.get("workflow_artifacts", {})
    if not result:
        return
    accounting = dataframe_from_artifacts(artifacts, "accounting")
    calculation = json_from_artifacts(artifacts, "tax_calculation")
    render_metric_row(result, calculation, accounting)
    st.caption("Покупки и поступления обработаны. Ниже — их категории и результаты налоговой проверки.")
    if result.get("warnings"):
        st.warning("; ".join(result["warnings"]))
    st.subheader("Транзакции")
    if not accounting.empty:
        columns = [column for column in ["date", "description", "amount", "currency", "transaction_type", "category", "review_status"] if column in accounting.columns]
        query = st.text_input("Поиск по транзакциям", key="transaction_search")
        view = accounting[columns]
        view = view.copy()
        if "category" in view:
            view["category"] = view["category"].fillna("").map(category_label)
        view = view.rename(columns={"date": "Дата", "description": "Покупка / поступление", "amount": "Сумма", "currency": "Валюта", "transaction_type": "Тип", "category": "Категория", "review_status": "Проверка"})
        if query:
            mask = view.astype(str).apply(lambda column: column.str.contains(query, case=False, na=False, regex=False)).any(axis=1)
            view = view[mask]
        st.dataframe(view, use_container_width=True, hide_index=True)
    else:
        st.info("Транзакции не найдены.")
    st.subheader("Ваш налог за отчётный период")
    status = calculation.get("status", "NEEDS_REVIEW")
    st.metric("Налог за период", tax_amount_label(calculation.get("calculated_tax_amount"), status))
    if calculation.get("calculated_tax_amount") is None or status not in {"CALCULATED", "EMPTY_PERIOD"}:
        st.info(explain_review(calculation.get("explanation", "Нужно уточнить налоговый режим и документы по операциям.")))
    else:
        st.write({"Налогооблагаемая база": calculation.get("taxable_base"), "Налог": calculation.get("calculated_tax_amount"), "НДС к уплате": calculation.get("vat_payable")})
    if calculation.get("legal_references"):
        st.json(calculation["legal_references"])
    if calculation.get("review_warnings"):
        st.warning("Требуют проверки: " + ", ".join(calculation["review_warnings"]))
    tax_transactions = dataframe_from_artifacts(artifacts, "tax_transactions")
    if not tax_transactions.empty:
        st.caption("Как ваши покупки учитываются при расчёте налога")
        for _, purchase in tax_transactions.iterrows():
            description = purchase.get("description")
            if pd.isna(description):
                description = purchase["transaction_id"]
            category = purchase.get("category", "Категория не определена")
            currency = purchase.get("currency", "")
            with st.expander(f"{description} · {purchase['original_amount']} {currency}", expanded=True):
                st.write(f"Категория: {category}")
                st.write(STATUSES.get(purchase.get("tax_status"), "Нужно уточнение"))
                st.write(explain_review(str(purchase.get("explanation", ""))))
                deduction = purchase.get("eligible_amount")
                if pd.notna(deduction):
                    st.write(f"Сумма, учитываемая для вычета: {deduction} {currency}")
                st.caption("Налог показывается выше за весь отчётный период. Сумма вычета по покупке — это не сумма налога.")
                reference = purchase.get("legal_reference")
                if pd.notna(reference) and reference:
                    st.text(f"Правовое основание: {reference}")
    st.subheader("Ручная проверка")
    review = dataframe_from_artifacts(artifacts, "review_required")
    if review.empty:
        st.success("Операций для ручной проверки нет.")
    else:
        if "reason" in review:
            review["reason"] = review["reason"].map(explain_review)
        st.dataframe(review, use_container_width=True, hide_index=True)
    st.subheader("Скачать отчёты")
    download_button("Accounting CSV", artifacts, "accounting", "accounting.csv", "text/csv")
    download_button("Tax summary CSV", artifacts, "tax_summary", "tax_summary.csv", "text/csv")
    download_button("Tax transactions CSV", artifacts, "tax_transactions", "tax_transactions.csv", "text/csv")
    download_button("Review required CSV", artifacts, "review_required", "review_required.csv", "text/csv")
    download_button("Tax calculation JSON", artifacts, "tax_calculation", "tax_calculation.json", "application/json")


def main() -> None:
    from accounting_assistant.frontend.v2_app import main as period_main
    period_main()


if __name__ == "__main__":
    main()
