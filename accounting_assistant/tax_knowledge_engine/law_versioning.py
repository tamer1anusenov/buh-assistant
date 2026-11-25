"""Conservative historical applicability checks for retrieved legal acts."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

VersionStatus = Literal["VERSION_VERIFIED", "NEEDS_REVIEW", "NOT_APPLICABLE"]


class LawVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    publication_date: date | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    in_force: bool


class VersionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: VersionStatus
    applicable: bool
    explanation: str


def version_for_date(version: LawVersion, transaction_date: date) -> VersionCheck:
    """Return review when effective/expiry dates cannot establish history."""
    if not version.in_force and version.expiration_date is None:
        return VersionCheck(status="NEEDS_REVIEW", applicable=False, explanation="Статус акта не подтверждает применение к указанной исторической дате.")
    if version.effective_date is None:
        return VersionCheck(status="NEEDS_REVIEW", applicable=False, explanation="Дата вступления в силу не получена из источника.")
    if transaction_date < version.effective_date:
        return VersionCheck(status="NOT_APPLICABLE", applicable=False, explanation="Транзакция датирована раньше вступления нормы в силу.")
    if version.expiration_date is not None and transaction_date > version.expiration_date:
        return VersionCheck(status="NOT_APPLICABLE", applicable=False, explanation="Транзакция датирована после окончания действия версии нормы.")
    if not version.in_force:
        return VersionCheck(status="NOT_APPLICABLE", applicable=False, explanation="Версия акта отмечена как утратившая силу для указанного периода.")
    return VersionCheck(status="VERSION_VERIFIED", applicable=True, explanation="Период действия нормы подтверждён переданными датами.")
