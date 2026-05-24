"""Caja de apuestas: Matutina Nacional + Provincia, martingala cada 6 fallos."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.config import (
    CAJA_ACTIVE_BETS,
    CAJA_DEFAULT_STAKE,
    CAJA_DOUBLE_AFTER_LOSSES,
    CAJA_DRAW,
    CAJA_PROVINCES,
    CAJA_HOLIDAYS,
    CAJA_SESSION_NACIONAL_PREV_DIGIT,
    CAJA_SESSION_NACIONAL_START,
    CAJA_SESSION_PROVINCIA_DIGIT,
    CAJA_SESSION_PROVINCIA_START,
    CAJA_SESSION_START,
    DEFAULT_PROVINCE,
    DRAW_TIMES,
    PAYOUT_MULTIPLIER,
    PROVINCES,
)
from backend.database import (
    clear_betting_entries,
    disable_betting_slots_except,
    get_betting_entries_filtered,
    get_betting_settings,
    get_betting_slots,
    get_draws,
    get_last_betting_entry_date,
    get_processed_draw_keys,
    insert_betting_entry,
    purge_betting_entries_before_session,
    purge_betting_entries_excluded_draws,
    purge_betting_entries_on_dates,
    purge_betting_entries_on_weekdays,
    upsert_betting_settings,
    upsert_betting_slot,
)
from backend.rest_days import (
    is_rest_day,
    is_today_rest_day,
    rest_day_kind,
    rest_day_label,
    rest_day_note,
    session_headline,
    today_rest_kind,
)
from backend.timeutil import draw_datetime_local, now_local, today_local

DRAW_INFO = {d["id"]: d for d in DRAW_TIMES}
DRAW_ORDER = {d["id"]: i for i, d in enumerate(DRAW_TIMES)}
CAJA_DRAW_ORDER = DRAW_ORDER.get(CAJA_DRAW, 1)


def _should_process_draw(draw_date: str, draw_type: str) -> bool:
    if is_rest_day(draw_date):
        return False
    if draw_date < CAJA_SESSION_START:
        return False
    if draw_date == CAJA_SESSION_START:
        return DRAW_ORDER.get(draw_type, 0) >= CAJA_DRAW_ORDER
    return True


def _default_settings() -> dict[str, Any]:
    return {
        "initial_balance": 0.0,
        "default_stake": CAJA_DEFAULT_STAKE,
        "payout_multiplier": float(PAYOUT_MULTIPLIER),
        "auto_advance": False,
        "double_after_losses": CAJA_DOUBLE_AFTER_LOSSES,
    }


def get_settings() -> dict[str, Any]:
    row = get_betting_settings()
    if not row:
        defaults = _default_settings()
        upsert_betting_settings(defaults)
        return defaults
    if "double_after_losses" not in row:
        row["double_after_losses"] = CAJA_DOUBLE_AFTER_LOSSES
    return row


def _slot_map() -> dict[str, dict[str, Any]]:
    return {f"{s['province']}|{s['draw_type']}": s for s in get_betting_slots()}


def _province_label(pid: str) -> str:
    if pid == "nacional":
        return "Nacional"
    if pid == "buenos_aires":
        return "Provincia"
    return PROVINCES.get(pid, {}).get("name", pid)


def _ensure_today_draws() -> None:
    """Fusiona seed si faltan sorteos de hoy (Render pierde DB al redeploy)."""
    today = today_local()
    now = now_local()
    past_slots = [slot for slot in DRAW_TIMES if now >= draw_datetime_local(slot)]
    if not past_slots:
        return
    missing = False
    for slot in past_slots:
        for pid in CAJA_PROVINCES:
            row = next(
                (
                    d
                    for d in get_draws(province=pid, from_date=today)
                    if d["draw_date"] == today
                    and d["draw_type"] == slot["id"]
                    and d["position"] == 1
                ),
                None,
            )
            if not row:
                missing = True
                break
        if missing:
            break
    if missing:
        from backend.seed.loader import merge_seed_draws

        merge_seed_draws()


def _rest_day_movements(draw_date: str, entries: list[dict]) -> list[dict[str, Any]]:
    """Movimientos de dia de descanso en el ledger — sin apostar ni sumar."""
    kind = rest_day_kind(draw_date)
    note = rest_day_note(draw_date)
    items: list[dict[str, Any]] = []
    for slot in DRAW_TIMES:
        for pid in CAJA_PROVINCES:
            row = next(
                (
                    d
                    for d in get_draws(province=pid, from_date=draw_date)
                    if d["draw_date"] == draw_date
                    and d["draw_type"] == slot["id"]
                    and d["position"] == 1
                ),
                None,
            )
            digit = _province_active_digit(pid)
            state = _replay_province_state(pid, entries)
            result_digit = int(row["last_digit"]) if row else None
            items.append(
                {
                    "province": pid,
                    "draw_type": slot["id"],
                    "draw_date": draw_date,
                    "digit_played": digit,
                    "stake": 0.0,
                    "reference_stake": float(state["stake"]),
                    "result_digit": result_digit,
                    "hit": 0,
                    "payout": 0.0,
                    "new_digit": None,
                    "note": note,
                    "rest_day": True,
                    "rest_kind": kind,
                    "rest_label": rest_day_label(draw_date),
                    "has_result": row is not None,
                    "processed_at": now_local().isoformat(timespec="seconds"),
                }
            )
    items.sort(key=lambda e: (DRAW_ORDER.get(e["draw_type"], 0), e["province"]))
    return items


def _all_rest_day_movements(today: str, entries: list[dict]) -> list[dict[str, Any]]:
    """Todos los dias de descanso de la sesion en el ledger."""
    items: list[dict[str, Any]] = []
    start = datetime.fromisoformat(CAJA_SESSION_START).date()
    end = datetime.fromisoformat(today).date()
    day = start
    while day <= end:
        ds = day.isoformat()
        if is_rest_day(ds):
            items.extend(_rest_day_movements(ds, entries))
        day += timedelta(days=1)
    return items


def _merge_display_entries(real: list[dict], rest: list[dict]) -> list[dict]:
    merged = real + rest
    merged.sort(
        key=lambda e: (e["draw_date"], DRAW_ORDER.get(e["draw_type"], 0), e["province"]),
        reverse=True,
    )
    return merged


def _replay_province_state(pid: str, entries: list[dict] | None = None) -> dict[str, float | int]:
    """Recalcula racha y apuesta actual de una provincia segun el historial cronologico."""
    if entries is None:
        entries = get_betting_entries_filtered(provinces=[pid], limit=500)
    settings = get_settings()
    threshold = int(settings.get("double_after_losses", CAJA_DOUBLE_AFTER_LOSSES))
    ordered = sorted(
        [e for e in entries if e["province"] == pid],
        key=lambda e: (e["draw_date"], DRAW_ORDER.get(e["draw_type"], 0)),
    )
    streak = 0
    base = CAJA_DEFAULT_STAKE
    stake = CAJA_DEFAULT_STAKE
    for e in ordered:
        if e["hit"]:
            streak = 0
            stake = base
        else:
            streak += 1
            if streak >= threshold:
                stake *= 2
                streak = 0
    return {"loss_streak": streak, "stake": stake, "base_stake": base}


def _province_active_digit(pid: str) -> int:
    for bet in CAJA_ACTIVE_BETS:
        if bet["province"] == pid:
            return int(bet["digit"])
    return 0


def _sync_province_slots(pid: str, state: dict[str, float | int]) -> None:
    digit = _province_active_digit(pid)
    for bet in CAJA_ACTIVE_BETS:
        if bet["province"] != pid:
            continue
        upsert_betting_slot(
            pid,
            bet["draw_type"],
            digit,
            float(state["stake"]),
            True,
            base_stake=float(state["base_stake"]),
            loss_streak=int(state["loss_streak"]),
        )


def _sync_all_province_slots(entries: list[dict]) -> None:
    for pid in CAJA_PROVINCES:
        _sync_province_slots(pid, _replay_province_state(pid, entries))


def apply_session_bets(reset_streak: bool = False) -> None:
    """Activa los 4 sorteos por provincia. La racha se calcula global por provincia."""
    active_keys: set[str] = set()
    entries = get_betting_entries_filtered(provinces=CAJA_PROVINCES, limit=500)
    for bet in CAJA_ACTIVE_BETS:
        active_keys.add(f"{bet['province']}|{bet['draw_type']}")

    if reset_streak or not entries:
        for bet in CAJA_ACTIVE_BETS:
            upsert_betting_slot(
                bet["province"],
                bet["draw_type"],
                int(bet["digit"]),
                float(bet["stake"]),
                True,
                base_stake=CAJA_DEFAULT_STAKE,
                loss_streak=0,
                reset_streak=True,
            )
    else:
        _sync_all_province_slots(entries)

    disable_betting_slots_except(active_keys)
    settings = get_settings()
    upsert_betting_settings({**settings, "auto_advance": False, "default_stake": CAJA_DEFAULT_STAKE})


def _needs_session_rebuild(entries: list[dict]) -> bool:
    """Matutina 22/05: Nacional jugo el 2 y gano; si el ledger dice otra cosa, reconstruir."""
    mat_nac = next(
        (
            e
            for e in entries
            if e["province"] == "nacional"
            and e["draw_type"] == CAJA_DRAW
            and e["draw_date"] == CAJA_SESSION_START
        ),
        None,
    )
    if not mat_nac:
        return bool(entries)
    return (
        int(mat_nac["digit_played"]) != CAJA_SESSION_NACIONAL_PREV_DIGIT
        or not mat_nac["hit"]
    )


def rebuild_session_ledger() -> dict[str, Any]:
    """Reconstruye movimientos desde inicio sesion Matutina (Nacional 2→3, Provincia 5)."""
    settings = get_settings()
    threshold = int(settings.get("double_after_losses", CAJA_DOUBLE_AFTER_LOSSES))
    clear_betting_entries(provinces=CAJA_PROVINCES, from_date=CAJA_SESSION_START)
    now = datetime.now().isoformat(timespec="seconds")

    prov_streak = 0
    prov_stake = CAJA_DEFAULT_STAKE
    nac_streak = 0
    nac_stake = CAJA_DEFAULT_STAKE
    entries_added = 0

    date_prov: list[tuple[str, str]] = []
    for draw_date in sorted(
        {
            d["draw_date"]
            for d in get_draws(province="nacional", days=30)
            if d["position"] == 1 and d["draw_type"] == CAJA_DRAW and d["draw_date"] >= CAJA_SESSION_NACIONAL_START
        }
    ):
        date_prov.append((draw_date, "nacional"))
    for draw_date in sorted(
        {
            d["draw_date"]
            for d in get_draws(province="buenos_aires", days=30)
            if d["position"] == 1 and d["draw_type"] == CAJA_DRAW and d["draw_date"] >= CAJA_SESSION_PROVINCIA_START
        }
    ):
        date_prov.append((draw_date, "buenos_aires"))

    for draw_date, pid in date_prov:
        row = next(
            (
                d
                for d in get_draws(province=pid, from_date=draw_date)
                if d["draw_date"] == draw_date
                and d["draw_type"] == CAJA_DRAW
                and d["position"] == 1
            ),
            None,
        )
        if not row:
            continue

        if pid == "nacional":
            digit = CAJA_SESSION_NACIONAL_PREV_DIGIT
            stake = nac_stake
        else:
            digit = CAJA_SESSION_PROVINCIA_DIGIT
            stake = prov_stake

        result = int(row["last_digit"])
        hit = result == digit
        payout = round(stake * settings["payout_multiplier"], 2) if hit else 0.0
        note = ""

        if pid == "nacional":
            if hit:
                note = f"GANO con el {digit} · cobro {payout:,.0f} · proximo: 3"
                nac_streak = 0
                nac_stake = CAJA_DEFAULT_STAKE
            else:
                nac_streak += 1
                note = f"Salio {result} · jugaba {digit} · fallo {nac_streak}/{threshold}"
                if nac_streak >= threshold:
                    nac_stake *= 2
                    nac_streak = 0
                    note += f" · doble → {nac_stake:,.0f}"
        else:
            if hit:
                note = f"GANO con el {digit} · cobro {payout:,.0f}"
                prov_streak = 0
                prov_stake = CAJA_DEFAULT_STAKE
            else:
                prov_streak += 1
                note = f"Salio {result} · jugaba {digit} · 1ra jugada Matutina · fallo {prov_streak}/{threshold}"
                if prov_streak >= threshold:
                    prov_stake *= 2
                    prov_streak = 0
                    note += f" · doble → {prov_stake:,.0f}"

        insert_betting_entry(
            {
                "province": pid,
                "draw_type": CAJA_DRAW,
                "draw_date": draw_date,
                "digit_played": digit,
                "stake": stake,
                "result_digit": result,
                "hit": int(hit),
                "payout": payout,
                "new_digit": 3 if pid == "nacional" and hit else None,
                "note": note,
                "processed_at": now,
            }
        )
        entries_added += 1

    upsert_betting_slot("nacional", CAJA_DRAW, 3, nac_stake, True, base_stake=CAJA_DEFAULT_STAKE, loss_streak=nac_streak)
    upsert_betting_slot(
        "buenos_aires",
        CAJA_DRAW,
        CAJA_SESSION_PROVINCIA_DIGIT,
        prov_stake,
        True,
        base_stake=CAJA_DEFAULT_STAKE,
        loss_streak=prov_streak,
    )
    disable_betting_slots_except({f"{b['province']}|{b['draw_type']}" for b in CAJA_ACTIVE_BETS})
    entries = get_betting_entries_filtered(provinces=CAJA_PROVINCES, limit=500)
    _sync_all_province_slots(entries)

    return {"entries_added": entries_added, "nacional_streak": nac_streak, "provincia_streak": prov_streak}


def _session_status() -> dict[str, str]:
    if is_today_rest_day():
        today = today_local()
        headline = session_headline(today)
        return {
            "headline": headline,
            "nacional": "Nacional: sin apostar hoy · racha congelada",
            "provincia": "Provincia: sin apostar hoy · racha congelada",
        }
    return {
        "headline": "Jugando el 3 (Nacional) y el 5 (Provincia) en los 4 sorteos del dia",
        "nacional": "Nacional: 3 en cada sorteo · ganamos con el 2 en Matutina el 22/05",
        "provincia": "Provincia: 5 en cada sorteo · se actualiza solo al salir cada quiniela",
    }


def _active_bets() -> list[dict[str, Any]]:
    from backend.analyzer import get_next_draw

    settings = get_settings()
    entries = get_betting_entries_filtered(provinces=CAJA_PROVINCES, limit=500)
    bets: list[dict[str, Any]] = []
    rest_today = is_today_rest_day()
    rest_msg = rest_day_note(today_local()) if rest_today else ""

    for pid in CAJA_PROVINCES:
        next_sid = get_next_draw(province=pid)["next_draw"]
        draw = DRAW_INFO.get(next_sid, DRAW_TIMES[0])
        state = _replay_province_state(pid, entries)
        threshold = int(settings.get("double_after_losses", CAJA_DOUBLE_AFTER_LOSSES))
        streak = int(state["loss_streak"])
        stake = float(state["stake"])
        bets.append(
            {
                "province": pid,
                "province_label": _province_label(pid),
                "draw_type": next_sid,
                "draw_name": draw["name"],
                "draw_time": f"{draw['hour']:02d}:{draw.get('minute', 0):02d} hs",
                "active_digit": _province_active_digit(pid),
                "stake": stake,
                "base_stake": float(state["base_stake"]),
                "loss_streak": streak,
                "losses_to_double": max(0, threshold - streak),
                "double_threshold": threshold,
                "next_stake_if_double": stake * 2,
                "potential_win": round(stake * settings["payout_multiplier"], 2),
                "enabled": not rest_today,
                "rest_day": rest_today,
                "rest_kind": today_rest_kind() if rest_today else None,
                "rest_message": rest_msg,
            }
        )
    return bets


def _caja_totals(entries: list[dict]) -> dict[str, float]:
    betting = [e for e in entries if not e.get("rest_day")]
    invertido = sum(e["stake"] for e in betting)
    ganado = sum(e["payout"] for e in betting)
    aciertos = sum(1 for e in betting if e["hit"])
    return {
        "invertido": round(invertido, 2),
        "ganado": round(ganado, 2),
        "neto": round(ganado - invertido, 2),
        "aciertos": aciertos,
        "jugadas": len(betting),
    }


def _purge_invalid_caja_entries() -> int:
    """Elimina movimientos anteriores al inicio de sesion o sorteos previos a Matutina ese dia."""
    from backend.config import CAJA_REST_WEEKDAYS

    excluded = [dt for dt, idx in DRAW_ORDER.items() if idx < CAJA_DRAW_ORDER]
    n1 = purge_betting_entries_before_session(CAJA_SESSION_START, CAJA_PROVINCES)
    n2 = purge_betting_entries_excluded_draws(CAJA_SESSION_START, excluded, CAJA_PROVINCES)
    n3 = purge_betting_entries_on_weekdays(CAJA_REST_WEEKDAYS, CAJA_PROVINCES)
    n4 = purge_betting_entries_on_dates(list(CAJA_HOLIDAYS.keys()), CAJA_PROVINCES)
    return n1 + n2 + n3 + n4


def get_caja_state(limit: int = 50) -> dict[str, Any]:
    apply_session_bets()
    _purge_invalid_caja_entries()
    settings = get_settings()
    entries = get_betting_entries_filtered(
        provinces=CAJA_PROVINCES,
        limit=limit,
    )
    if not entries or _needs_session_rebuild(entries):
        rebuild_session_ledger()
    process_new_results()
    today = today_local()
    rest_today = is_today_rest_day()
    _ensure_today_draws()
    real_entries = get_betting_entries_filtered(
        provinces=CAJA_PROVINCES,
        limit=limit,
    )
    rest_entries = _all_rest_day_movements(today, real_entries)
    entries = _merge_display_entries(real_entries, rest_entries)
    totals = _caja_totals(real_entries)
    saldo = round(settings["initial_balance"] + totals["neto"], 2)

    by_province: dict[str, dict[str, float]] = {}
    for e in real_entries:
        p = e["province"]
        if p not in by_province:
            by_province[p] = {"invertido": 0.0, "ganado": 0.0, "neto": 0.0}
        by_province[p]["invertido"] += e["stake"]
        by_province[p]["ganado"] += e["payout"]
    for p in by_province:
        by_province[p]["neto"] = round(by_province[p]["ganado"] - by_province[p]["invertido"], 2)
        for k in by_province[p]:
            by_province[p][k] = round(by_province[p][k], 2)

    draw = DRAW_INFO.get(CAJA_DRAW, DRAW_TIMES[1])
    return {
        "settings": settings,
        "session": {
            "draw": CAJA_DRAW,
            "draw_name": draw["name"],
            "draw_time": f"{draw['hour']:02d}:{draw.get('minute', 0):02d} hs",
            "provinces": [_province_label(p) for p in CAJA_PROVINCES],
            "rule": f"Sesion desde el {CAJA_SESSION_START} · sync auto 5 min despues de cada sorteo",
            "status": _session_status(),
            "rest_day": rest_today,
            "rest_kind": today_rest_kind() if rest_today else None,
            "rest_label": rest_day_label(today) if rest_today else "",
        },
        "caja": {
            **totals,
            "saldo": saldo,
            "initial_balance": settings["initial_balance"],
        },
        "active_bets": _active_bets(),
        "by_province": by_province,
        "entries": entries,
    }


def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = get_settings()
    data = {
        "initial_balance": float(payload.get("initial_balance", current["initial_balance"])),
        "default_stake": float(payload.get("default_stake", current["default_stake"])),
        "payout_multiplier": float(payload.get("payout_multiplier", current["payout_multiplier"])),
        "auto_advance": False,
        "double_after_losses": int(payload.get("double_after_losses", current.get("double_after_losses", 6))),
    }
    upsert_betting_settings(data)
    return data


def save_bet(province: str, draw_type: str, digit: int, stake: float | None = None) -> None:
    settings = get_settings()
    slot_map = _slot_map()
    key = f"{province}|{draw_type}"
    existing = slot_map.get(key)
    base = float(existing["base_stake"]) if existing else CAJA_DEFAULT_STAKE
    current_stake = float(stake if stake is not None else (existing["stake"] if existing else base))
    digit_changed = existing and int(existing["active_digit"]) != digit
    upsert_betting_slot(
        province,
        draw_type,
        digit,
        current_stake,
        True,
        base_stake=base,
        reset_streak=digit_changed,
    )


def process_new_results() -> dict[str, Any]:
    """Sorteos nuevos desde inicio sesion — racha compartida por provincia en los 4 horarios."""
    apply_session_bets()
    _purge_invalid_caja_entries()
    settings = get_settings()
    threshold = int(settings.get("double_after_losses", CAJA_DOUBLE_AFTER_LOSSES))
    processed = get_processed_draw_keys()
    now = datetime.now().isoformat(timespec="seconds")
    new_entries: list[dict[str, Any]] = []

    for pid in CAJA_PROVINCES:
        existing = get_betting_entries_filtered(provinces=[pid], limit=500)
        state = _replay_province_state(pid, existing)
        digit = _province_active_digit(pid)

        pending = [
            d
            for d in get_draws(province=pid, days=30)
            if d["position"] == 1 and _should_process_draw(d["draw_date"], d["draw_type"])
        ]
        pending.sort(key=lambda d: (d["draw_date"], DRAW_ORDER.get(d["draw_type"], 0)))

        for row in pending:
            draw_date = row["draw_date"]
            draw_type = row["draw_type"]
            key = f"{pid}|{draw_type}|{draw_date}"
            if key in processed:
                continue
            # Matutina inicial la arma rebuild_session_ledger (Nacional 2, no 3).
            if draw_date == CAJA_SESSION_START and draw_type == CAJA_DRAW:
                continue

            stake = float(state["stake"])
            streak = int(state["loss_streak"])
            result_digit = int(row["last_digit"])
            hit = result_digit == digit
            payout = round(stake * settings["payout_multiplier"], 2) if hit else 0.0
            draw_label = next((d["name"] for d in DRAW_TIMES if d["id"] == draw_type), draw_type)
            note = ""

            if hit:
                state = {"loss_streak": 0, "stake": float(state["base_stake"]), "base_stake": float(state["base_stake"])}
                note = f"{draw_label}: GANO {digit} · cobro {payout:,.0f}"
            else:
                new_streak = streak + 1
                note = f"{draw_label}: salio {result_digit} · fallo {new_streak}/{threshold}"
                if new_streak >= threshold:
                    state = {
                        "loss_streak": 0,
                        "stake": stake * 2,
                        "base_stake": float(state["base_stake"]),
                    }
                    note += f" · DOBLE → {state['stake']:,.0f}"
                else:
                    state = {"loss_streak": new_streak, "stake": stake, "base_stake": float(state["base_stake"])}

            insert_betting_entry(
                {
                    "province": pid,
                    "draw_type": draw_type,
                    "draw_date": draw_date,
                    "digit_played": digit,
                    "stake": stake,
                    "result_digit": result_digit,
                    "hit": int(hit),
                    "payout": payout,
                    "new_digit": None,
                    "note": note,
                    "processed_at": now,
                }
            )
            processed.add(key)
            new_entries.append(
                {
                    "province": pid,
                    "draw_type": draw_type,
                    "draw_date": draw_date,
                    "hit": hit,
                    "stake": stake,
                    "payout": payout,
                }
            )

        _sync_province_slots(pid, state)

    return {"processed": len(new_entries), "entries": new_entries}
