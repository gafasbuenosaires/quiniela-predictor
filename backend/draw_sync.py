"""Sync automatico ~5 min despues de cada sorteo."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.config import (
    DEFAULT_PROVINCE,
    DRAW_TIMES,
    HISTORY_DAYS,
    POST_DRAW_SYNC_MINUTES,
)
from backend.database import get_draws, resolve_predictions
from backend.scraper import sync_all_provinces
from backend.timeutil import draw_datetime_local, now_local, today_local

# Sorteos ya resueltos hoy (reinicia al reiniciar server)
_done_keys: set[str] = set()
# Ultimo intento de sync por sorteo/dia (reintenta cada POST_DRAW_SYNC_MINUTES)
_last_sync_attempt: dict[str, datetime] = {}


def _draw_datetime(slot: dict, day: datetime) -> datetime:
    return draw_datetime_local(slot, day.date())


def _has_draw_result(draw_type: str, draw_date: str, province: str = DEFAULT_PROVINCE) -> bool:
    rows = get_draws(province=province, from_date=draw_date, draw_type=draw_type)
    return any(r["draw_date"] == draw_date and r["position"] == 1 for r in rows)


def get_draw_sync_status() -> list[dict[str, Any]]:
    """Estado de cada sorteo del dia para la UI."""
    now = now_local()
    today = today_local()
    items: list[dict[str, Any]] = []

    for slot in DRAW_TIMES:
        draw_dt = _draw_datetime(slot, now)
        sync_from = draw_dt + timedelta(minutes=POST_DRAW_SYNC_MINUTES)
        key = f"{today}|{slot['id']}"
        has_result = _has_draw_result(slot["id"], today)

        if has_result:
            phase = "done"
        elif now < draw_dt:
            phase = "pending"
        elif now < sync_from:
            phase = "waiting_sync"
        else:
            phase = "awaiting_result"

        result_digit = None
        result_number = None
        if has_result:
            row = next(
                (
                    r
                    for r in get_draws(province=DEFAULT_PROVINCE, from_date=today, draw_type=slot["id"])
                    if r["position"] == 1
                ),
                None,
            )
            if row:
                result_digit = row["last_digit"]
                result_number = row["number"]

        items.append(
            {
                "draw_type": slot["id"],
                "draw_name": slot["name"],
                "time": f"{slot['hour']:02d}:{slot.get('minute', 0):02d} hs",
                "sync_at": sync_from.strftime("%H:%M"),
                "phase": phase,
                "has_result": has_result,
                "result_digit": result_digit,
                "result_number": result_number,
                "date": today,
            }
        )
    return items


def maybe_sync_after_draw(force: bool = False) -> dict[str, Any]:
    """
    Si pasaron 5+ min del sorteo, sincroniza hasta obtener el numero.
    Reintenta cada minuto hasta POST_DRAW_SYNC_RETRY_MINUTES.
    """
    from backend.betting import process_new_results

    now = now_local()
    today = today_local()
    synced_draws: list[str] = []

    for slot in DRAW_TIMES:
        key = f"{today}|{slot['id']}"
        if key in _done_keys and not force:
            continue

        draw_dt = _draw_datetime(slot, now)
        sync_from = draw_dt + timedelta(minutes=POST_DRAW_SYNC_MINUTES)

        if now < sync_from and not force:
            continue

        if _has_draw_result(slot["id"], today):
            _done_keys.add(key)
            continue

        last = _last_sync_attempt.get(key)
        if not force and last and (now - last).total_seconds() < POST_DRAW_SYNC_MINUTES * 60:
            continue
        _last_sync_attempt[key] = now

        try:
            sync_all_provinces(HISTORY_DAYS)
            resolve_predictions()
            process_new_results()
        except Exception as exc:
            return {"synced": synced_draws, "error": str(exc), "status": get_draw_sync_status()}

        if _has_draw_result(slot["id"], today):
            _done_keys.add(key)
            synced_draws.append(slot["id"])

    try:
        process_new_results()
    except Exception:
        pass

    return {
        "synced": synced_draws,
        "status": get_draw_sync_status(),
    }
