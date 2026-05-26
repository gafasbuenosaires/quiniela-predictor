"""Dias sin apostar: sabado (opcional), domingo y feriados por fecha."""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.config import CAJA_HOLIDAYS, CAJA_REST_WEEKDAYS, SATURDAY_WEEKDAY
from backend.timeutil import today_local

REST_KIND_SATURDAY = "saturday"
REST_KIND_SUNDAY = "sunday"
REST_KIND_HOLIDAY = "holiday"


def _holiday_dates() -> set[str]:
    """Feriados + trasladados (domingo->lunes, sabado->lunes)."""
    dates = set(CAJA_HOLIDAYS.keys())
    for ds in CAJA_HOLIDAYS:
        d = datetime.fromisoformat(ds).date()
        wd = d.weekday()
        if wd == 6:
            dates.add((d + timedelta(days=1)).isoformat())
        elif wd == 5:
            dates.add((d + timedelta(days=2)).isoformat())
    return dates


def _holiday_name(draw_date: str) -> str:
    if draw_date in CAJA_HOLIDAYS:
        return CAJA_HOLIDAYS[draw_date]
    d = datetime.fromisoformat(draw_date).date()
    for orig, name in CAJA_HOLIDAYS.items():
        od = datetime.fromisoformat(orig).date()
        if od.weekday() == 6 and d == od + timedelta(days=1):
            return f"{name} (trasladado)"
        if od.weekday() == 5 and d == od + timedelta(days=2):
            return f"{name} (trasladado)"
    return "feriado"


def effective_holiday_dates() -> list[str]:
    return sorted(_holiday_dates())


def saturday_rest_enabled() -> bool:
    from backend.database import get_betting_settings

    row = get_betting_settings()
    if not row:
        return True
    return bool(row.get("saturday_rest_day", 1))


def rest_day_kind(draw_date: str) -> str | None:
    if draw_date in _holiday_dates():
        return REST_KIND_HOLIDAY
    weekday = datetime.fromisoformat(draw_date).weekday()
    if weekday == SATURDAY_WEEKDAY and saturday_rest_enabled():
        return REST_KIND_SATURDAY
    if weekday in CAJA_REST_WEEKDAYS:
        return REST_KIND_SUNDAY
    return None


def is_rest_day(draw_date: str) -> bool:
    return rest_day_kind(draw_date) is not None


def is_today_rest_day() -> bool:
    return is_rest_day(today_local())


def today_rest_kind() -> str | None:
    return rest_day_kind(today_local())


def rest_weekdays_to_purge() -> list[int]:
    """Weekdays cuyas apuestas hay que borrar de la DB (descanso activo)."""
    days = list(CAJA_REST_WEEKDAYS)
    if saturday_rest_enabled():
        days.append(SATURDAY_WEEKDAY)
    return days


def rest_day_note(draw_date: str) -> str:
    kind = rest_day_kind(draw_date)
    if kind == REST_KIND_SATURDAY:
        return "No aposto — dia sabado"
    if kind == REST_KIND_SUNDAY:
        return "No aposto — dia domingo"
    if kind == REST_KIND_HOLIDAY:
        return f"No aposto — dia feriado ({_holiday_name(draw_date)})"
    return ""


def rest_day_label(draw_date: str) -> str:
    kind = rest_day_kind(draw_date)
    if kind == REST_KIND_SATURDAY:
        return "Dia sabado — sin jugar"
    if kind == REST_KIND_SUNDAY:
        return "Dia domingo — sin jugar"
    if kind == REST_KIND_HOLIDAY:
        return f"Dia feriado — {_holiday_name(draw_date)}"
    return ""


def session_headline(draw_date: str | None = None) -> str:
    ds = draw_date or today_local()
    kind = rest_day_kind(ds)
    if kind == REST_KIND_SATURDAY:
        return "Sabado — dia de descanso (solo monitoreo, sin jugar)"
    if kind == REST_KIND_SUNDAY:
        return "Domingo — dia de descanso (solo monitoreo, sin jugar)"
    if kind == REST_KIND_HOLIDAY:
        return f"Feriado — {_holiday_name(ds)} (solo monitoreo, sin jugar)"
    return ""
