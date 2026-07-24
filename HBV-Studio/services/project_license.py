# -*- coding: utf-8 -*-
"""项目交付授权：固定到期日（含当日）。

本包面向甲方项目建模交付。授权使用至 LICENSE_EXPIRES_ON（含）。
到期后禁止启动新的数据准备、率定、模拟等写入/计算任务；
仍允许查看已有结果、导出与退出。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable


# 项目授权截止日（含当日 23:59:59 本地日历日）
LICENSE_EXPIRES_ON = date(2027, 12, 31)
LICENSE_WARNING_DAYS = 30
LICENSE_PRODUCT_LABEL = "HBV-Studio 项目授权版"
LICENSE_CONTACT_HINT = "如需延期或续用，请联系软件提供方书面续约。"

# 到期后仍允许的 POST（查看/收尾类）
POST_ALLOWED_WHEN_EXPIRED: frozenset[str] = frozenset(
    {
        "/api/app/window-unload",
        "/api/app/quit",
        "/api/run/export-excel",
        "/api/fs/open-path",
    }
)


@dataclass(frozen=True)
class LicenseStatus:
    expires_on: str
    today: str
    days_remaining: int
    expired: bool
    warning: bool
    ok: bool
    product: str
    message: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "expires_on": self.expires_on,
            "today": self.today,
            "days_remaining": self.days_remaining,
            "expired": self.expired,
            "warning": self.warning,
            "ok": self.ok,
            "product": self.product,
            "message": self.message,
            "detail": self.detail,
        }


def _as_date(value: date | datetime | None = None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    return value


def evaluate_license(*, today: date | datetime | None = None) -> LicenseStatus:
    current = _as_date(today)
    days_remaining = (LICENSE_EXPIRES_ON - current).days
    expired = days_remaining < 0
    warning = (not expired) and days_remaining <= LICENSE_WARNING_DAYS
    expires_text = LICENSE_EXPIRES_ON.isoformat()
    today_text = current.isoformat()

    if expired:
        message = f"项目授权已于 {expires_text} 到期，无法启动新的建模与计算任务。"
        detail = (
            f"当前日期 {today_text}。仍可查看已有结果并导出。"
            f"{LICENSE_CONTACT_HINT}"
        )
    elif warning:
        message = f"项目授权将于 {expires_text} 到期（剩余 {days_remaining} 天）。"
        detail = f"到期后将无法启动新的数据准备、率定与模拟任务。{LICENSE_CONTACT_HINT}"
    else:
        message = f"项目授权有效，截止日期 {expires_text}（剩余 {days_remaining} 天）。"
        detail = "本安装包为项目交付授权，仅限约定项目期内使用。"

    return LicenseStatus(
        expires_on=expires_text,
        today=today_text,
        days_remaining=days_remaining,
        expired=expired,
        warning=warning,
        ok=not expired,
        product=LICENSE_PRODUCT_LABEL,
        message=message,
        detail=detail,
    )


def license_blocks_post(path: str, *, today: date | datetime | None = None) -> tuple[bool, str]:
    """若应拦截该 POST，返回 (True, 错误信息)。"""
    status = evaluate_license(today=today)
    if not status.expired:
        return False, ""
    normalized = str(path or "").split("?", 1)[0]
    if normalized in POST_ALLOWED_WHEN_EXPIRED:
        return False, ""
    return True, f"{status.message} {status.detail}".strip()


def license_payload(*, today: date | datetime | None = None) -> dict[str, Any]:
    return evaluate_license(today=today).as_dict()
