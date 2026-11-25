"""Plain-language descriptions shared by downloads and the dashboard."""
from decimal import Decimal

CATEGORIES = {
    "Equipment": "Оборудование", "Software and IT": "ПО и IT",
    "Office expenses": "Офисные расходы", "Transportation": "Транспорт",
    "Food and hospitality": "Питание и представительские расходы",
    "Marketing": "Реклама", "Salary": "Зарплата", "Rent": "Аренда",
    "Contractor services": "Услуги подрядчиков", "Utilities": "Коммунальные услуги",
    "Other expenses": "Прочие расходы", "Sales revenue": "Продажи",
    "Service revenue": "Выручка за услуги", "Other income": "Прочие доходы",
}
STATUSES = {
    "ELIGIBLE": "Расход можно учесть при расчёте налога",
    "PARTIALLY_ELIGIBLE": "Расход можно учесть частично",
    "NOT_ELIGIBLE": "Расход нельзя учесть для уменьшения налога",
    "NOT_APPLICABLE": "Вычет по этому правилу не применяется",
    "NEEDS_REVIEW": "Нужно уточнение", "UNSUPPORTED_REGIME": "Расчёт для вашего режима пока недоступен",
    "CALCULATED": "Налог рассчитан", "EMPTY_PERIOD": "Нет операций за период",
}


def category_label(value: str | None) -> str:
    return CATEGORIES.get(value or "", value or "Категория не определена")


def tax_amount_label(value: object, status: str, currency: str = "KZT") -> str:
    if value is None or status not in {"CALCULATED", "EMPTY_PERIOD"}:
        return "Пока не рассчитан"
    return f"{Decimal(str(value)):,.2f} {currency}"


def explain_review(reason: str) -> str:
    replacements = {
        "Нет подтверждённой нормы, применимой к периоду операции.":
            "Пока не удалось определить, уменьшает ли эта покупка ваш налог. Нужно проверить условия вычета для вашего режима и даты покупки.",
        "Нет проверенного расчётного правила для режима.":
            "Для выбранного налогового режима расчёт ещё не настроен. Сумма налога пока неизвестна; бухгалтеру нужно подтвердить ставку и порядок расчёта за этот период.",
    }
    return replacements.get(reason, reason)
