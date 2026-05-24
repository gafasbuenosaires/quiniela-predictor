"""Dias sin apostar: sabado, domingo y feriados por fecha."""
from __future__ import annotations

from datetime import datetime

from backend.config import CAJA_HOLIDAYS, CAJA_REST_WEEKDAYS
from backend.timeutil import today_local

REST_KIND_SATURDAY = "saturday"
REST_KIND_SUNDAY = "sunday"
REST_KIND_HOLIDAY = "holiday"


def rest_day_kind(draw_date: str) -> str | None:
    if draw_date in CAJA_HOLIDAYS:
        return REST_KIND_HOLIDAY
    weekday = datetime.fromisoformat(draw_date).weekday()
    if weekday in CAJA_REST_WEEKDAYS:
        if weekday == 5:
            return REST_KIND_SATURDAY
        if weekday == 6:
            return REST_KIND_SUNDAY
    return None


def is_rest_day(draw_date: str) -> bool:
    return rest_day_kind(draw_date) is not None


def is_today_rest_day() -> bool:
    return is_rest_day(today_local())


def today_rest_kind() -> str | None:
    return rest_day_kind(today_local())


def rest_day_note(draw_date: str) -> str:
    kind = rest_day_kind(draw_date)
    if kind == REST_KIND_SATURDAY:
        return "No aposto — dia sabado"
    if kind == REST_KIND_SUNDAY:
        return "No aposto — dia domingo"
    if kind == REST_KIND_HOLIDAY:
        name = CAJA_HOLIDAYS.get(draw_date, "feriado")
        return f"No aposto — dia feriado ({name})"
    return ""


def rest_day_label(draw_date: str) -> str:
    kind = rest_day_kind(draw_date)
    if kind == REST_KIND_SATURDAY:
        return "Dia sabado — sin jugar"
    if kind == REST_KIND_SUNDAY:
        return "Dia domingo — sin jugar"
    if kind == REST_KIND_HOLIDAY:
        name = CAJA_HOLIDAYS.get(draw_date, "feriado")
        return f"Dia feriado — {name}"
    return ""


def session_headline(draw_date: str | None = None) -> str:
    ds = draw_date or today_local()
    kind = rest_day_kind(ds)
    if kind == REST_KIND_SATURDAY:
        return "Sabado — dia de descanso (solo monitoreo, sin jugar)"
    if kind == REST_KIND_SUNDAY:
        return "Domingo — dia de descanso (solo monitoreo, sin jugar)"
    if kind == REST_KIND_HOLIDAY:
        name = CAJA_HOLIDAYS.get(ds, "feriado")
        return f"Feriado — {name} (solo monitoreo, sin jugar)"
    return ""
