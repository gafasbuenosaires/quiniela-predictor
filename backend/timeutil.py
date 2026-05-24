"""Hora Argentina para sorteos y dia de descanso (Render usa UTC)."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def now_local() -> datetime:
    return datetime.now(APP_TZ)


def today_local() -> str:
    return now_local().date().isoformat()


def draw_datetime_local(slot: dict, day: date | None = None) -> datetime:
    base = day or now_local().date()
    return datetime(
        base.year,
        base.month,
        base.day,
        slot["hour"],
        slot.get("minute", 0),
        tzinfo=APP_TZ,
    )
