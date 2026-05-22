"""Análisis estadístico de la última cifra (terminación 0-9)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from backend.config import (
    AI_ANALYSIS_DAYS,
    DEFAULT_PROVINCE,
    DRAW_TIMES,
    HISTORY_DAYS,
    PAYOUT_MULTIPLIER,
    PROVINCES,
)
from backend.database import get_draws


def _digits_from_draws(
    draws: list[dict],
    *,
    position: int | None = None,
    all_numbers: bool = False,
) -> list[int]:
    digits: list[int] = []
    for d in draws:
        if position is not None and d["position"] != position:
            continue
        if not all_numbers and position is None:
            # Por defecto: premio 1
            if d["position"] != 1:
                continue
        digits.append(d["last_digit"])
    return digits


def _frequency(digits: list[int]) -> dict[int, float]:
    if not digits:
        return {i: 1 / 10 for i in range(10)}
    c = Counter(digits)
    total = len(digits)
    return {i: c.get(i, 0) / total for i in range(10)}


def _gap_scores(draws: list[dict], draw_type: str | None = None) -> dict[int, float]:
    """Mayor score = más 'atrasado' el dígito en premio 1."""
    filtered = [d for d in draws if d["position"] == 1]
    if draw_type:
        filtered = [d for d in filtered if d["draw_type"] == draw_type]
    filtered.sort(key=lambda x: (x["draw_date"], x["draw_type"]))

    last_seen: dict[int, int] = {}
    gaps: dict[int, list[int]] = defaultdict(list)
    for idx, row in enumerate(filtered):
        d = row["last_digit"]
        if d in last_seen:
            gaps[d].append(idx - last_seen[d])
        last_seen[d] = idx

    scores: dict[int, float] = {}
    n = max(len(filtered), 1)
    for digit in range(10):
        if digit not in last_seen:
            scores[digit] = 1.0
        else:
            gap = (n - 1) - last_seen[digit]
            avg = sum(gaps[digit]) / len(gaps[digit]) if gaps[digit] else n
            scores[digit] = min(1.0, gap / max(avg, 1))
    return scores


def _markov_scores(draws: list[dict], draw_type: str | None = None) -> dict[int, float]:
    filtered = [d for d in draws if d["position"] == 1]
    if draw_type:
        filtered = [d for d in filtered if d["draw_type"] == draw_type]
    filtered.sort(key=lambda x: (x["draw_date"], x["draw_type"]))
    if len(filtered) < 2:
        return {i: 0.1 for i in range(10)}

    transitions: dict[int, Counter[int]] = defaultdict(Counter)
    for i in range(1, len(filtered)):
        prev_d = filtered[i - 1]["last_digit"]
        cur_d = filtered[i]["last_digit"]
        transitions[prev_d][cur_d] += 1

    last = filtered[-1]["last_digit"]
    trans = transitions[last]
    total = sum(trans.values()) or 1
    return {i: trans.get(i, 0) / total for i in range(10)}


def _weighted_blend(
    freq: dict[int, float],
    gaps: dict[int, float],
    markov: dict[int, float],
    weights: tuple[float, float, float] = (0.5, 0.25, 0.25),
) -> dict[int, float]:
    w_f, w_g, w_m = weights
    blended: dict[int, float] = {}
    for i in range(10):
        blended[i] = w_f * freq[i] + w_g * gaps[i] + w_m * markov[i]
    total = sum(blended.values()) or 1
    return {k: v / total for k, v in blended.items()}


def predict_digit(
    draws: list[dict],
    draw_type: str,
    *,
    days_weight: int = HISTORY_DAYS,
    use_all_numbers: bool = False,
) -> dict[str, Any]:
    dates = sorted({d["draw_date"] for d in draws}, reverse=True)[:days_weight]
    subset = [d for d in draws if d["draw_date"] in dates]

    type_draws = [d for d in subset if d["draw_type"] == draw_type]
    if use_all_numbers:
        digits = _digits_from_draws(type_draws, all_numbers=True)
        # all_numbers flag: include every position
        digits = [d["last_digit"] for d in type_draws]
    else:
        digits = _digits_from_draws(type_draws, position=1)

    freq = _frequency(digits)
    gaps = _gap_scores(subset, draw_type)
    markov = _markov_scores(subset, draw_type)
    probs = _weighted_blend(freq, gaps, markov, (0.45, 0.30, 0.25))

    best = max(probs, key=probs.get)
    ranked = sorted(probs.items(), key=lambda x: -x[1])

    return {
        "digit": best,
        "probability": round(probs[best], 4),
        "probabilities": {str(k): round(v, 4) for k, v in ranked},
        "ranking": [{"digit": d, "prob": round(p, 4)} for d, p in ranked],
        "sample_size": len(digits),
        "frequency": {str(k): round(v, 4) for k, v in sorted(freq.items())},
        "gaps": {str(k): round(v, 4) for k, v in sorted(gaps.items())},
    }


def digit_stats_30d(draws: list[dict], use_all_numbers: bool = True) -> dict[str, Any]:
    dates = sorted({d["draw_date"] for d in draws}, reverse=True)[:HISTORY_DAYS]
    subset = [d for d in draws if d["draw_date"] in dates]

    if use_all_numbers:
        digits = [d["last_digit"] for d in subset]
    else:
        digits = _digits_from_draws(subset, position=1)

    freq = Counter(digits)
    total = len(digits) or 1
    by_draw: dict[str, Counter] = defaultdict(Counter)
    for row in subset:
        if use_all_numbers or row["position"] == 1:
            by_draw[row["draw_type"]].update([row["last_digit"]])

    return {
        "days": len(dates),
        "total_observations": total,
        "global_frequency": [
            {"digit": d, "count": freq.get(d, 0), "pct": round(100 * freq.get(d, 0) / total, 2)}
            for d in range(10)
        ],
        "by_draw_type": {
            dt: [
                {"digit": d, "count": c.get(d, 0)}
                for d, _ in sorted(c.items(), key=lambda x: -x[1])
            ]
            for dt, c in by_draw.items()
        },
        "hottest": freq.most_common(3),
        "coldest": sorted(((d, freq.get(d, 0)) for d in range(10)), key=lambda x: x[1])[:3],
    }


def _format_draw_time(hour: int, minute: int = 0) -> str:
    return f"{hour:02d}:{minute:02d} hs"


def _countdown_label(seconds: int, *, live: bool = False, waiting: bool = False) -> str:
    if live:
        return "Sorteo en curso — ventana activa"
    if waiting:
        return "Horario pasado — esperando resultado"
    if seconds <= 0:
        return "Ahora"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"Faltan {h} h {m} min"
    if m > 0:
        return f"Faltan {m} min"
    return f"Faltan {s} seg"


def get_next_draw(
    now: datetime | None = None,
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    now = now or datetime.now()
    today = now.date().isoformat()
    completed_today: list[str] = []

    draws_today = get_draws(from_date=today, province=province)
    for dt in [d["id"] for d in DRAW_TIMES]:
        if any(r["draw_type"] == dt and r["position"] == 1 for r in draws_today):
            completed_today.append(dt)

    schedule: list[dict[str, Any]] = []
    next_slot: dict | None = None
    next_draw_dt: datetime | None = None

    for slot in DRAW_TIMES:
        minute = slot.get("minute", 0)
        draw_dt = datetime(now.year, now.month, now.day, slot["hour"], minute)
        end_window = draw_dt + timedelta(minutes=30)
        done = slot["id"] in completed_today

        if done:
            status = "done"
        elif now < draw_dt:
            status = "pending"
        elif now < end_window:
            status = "live"
        else:
            status = "waiting"

        schedule.append(
            {
                "id": slot["id"],
                "name": slot["name"],
                "hour": slot["hour"],
                "minute": minute,
                "time": _format_draw_time(slot["hour"], minute),
                "draw_time": draw_dt.isoformat(),
                "status": status,
            }
        )

        if next_slot is None and not done and now < end_window:
            next_slot = slot
            next_draw_dt = draw_dt

    if next_slot and next_draw_dt:
        seconds_until = max(0, int((next_draw_dt - now).total_seconds()))
        live = now >= next_draw_dt
        return {
            "province": province,
            "next_draw": next_slot["id"],
            "next_draw_name": next_slot["name"],
            "next_draw_time": _format_draw_time(next_slot["hour"], next_slot.get("minute", 0)),
            "draw_time": next_draw_dt.isoformat(),
            "target_date": today,
            "completed_today": completed_today,
            "is_today": True,
            "countdown_seconds": seconds_until,
            "countdown_label": _countdown_label(
                seconds_until,
                live=live,
                waiting=False,
            ),
            "schedule": schedule,
        }

    next_day = (now + timedelta(days=1)).date()
    first = DRAW_TIMES[0]
    first_minute = first.get("minute", 0)
    tomorrow_dt = datetime(next_day.year, next_day.month, next_day.day, first["hour"], first_minute)
    seconds_until = max(0, int((tomorrow_dt - now).total_seconds()))
    return {
        "province": province,
        "next_draw": first["id"],
        "next_draw_name": first["name"],
        "next_draw_time": _format_draw_time(first["hour"], first_minute),
        "draw_time": tomorrow_dt.isoformat(),
        "target_date": next_day.isoformat(),
        "completed_today": completed_today,
        "is_today": False,
        "countdown_seconds": seconds_until,
        "countdown_label": f"Manana {_format_draw_time(first['hour'], first_minute)} · {_countdown_label(seconds_until)}",
        "schedule": schedule,
    }


def martingale_plan(
    base_bet: float,
    max_attempts: int = 4,
    payout: float = PAYOUT_MULTIPLIER,
) -> dict[str, Any]:
    """Plan de recuperación: duplicar apuesta tras fallo. Pago x7."""
    steps = []
    total_risk = 0.0
    bet = base_bet
    for attempt in range(1, max_attempts + 1):
        total_risk += bet
        win_profit = bet * payout - total_risk
        steps.append(
            {
                "attempt": attempt,
                "bet": round(bet, 2),
                "cumulative_staked": round(total_risk, 2),
                "profit_if_win_now": round(win_profit, 2),
            }
        )
        bet *= 2

    break_even_prob = total_risk / (base_bet * payout) if payout else 0
    return {
        "base_bet": base_bet,
        "payout_multiplier": payout,
        "max_attempts": max_attempts,
        "steps": steps,
        "max_exposure": round(total_risk, 2),
        "note": (
            f"Si acertás en el intento N, ganás apuesta×{payout} menos lo ya apostado. "
            "La quiniela es aleatoria: esto no garantiza ganancia."
        ),
    }


def full_analysis(
    use_all_numbers: bool = True,
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    draws = get_draws(province=province)
    next_info = get_next_draw(province=province)
    target = next_info["next_draw"]

    math_pred = predict_digit(draws, target, use_all_numbers=use_all_numbers)
    per_draw = {
        d["id"]: predict_digit(draws, d["id"], use_all_numbers=use_all_numbers)
        for d in DRAW_TIMES
    }

    from backend.expert_analysis import analyze_full_day, expert_recommendation

    expert = expert_recommendation(draws, target, province)
    daily_four = analyze_full_day(draws, province)

    return {
        "province": province,
        "province_name": PROVINCES.get(province, {}).get("name", province),
        "next_draw_info": next_info,
        "math_prediction": math_pred,
        "expert": expert,
        "daily_four": daily_four,
        "predictions_by_draw": per_draw,
        "stats_30d": digit_stats_30d(draws, use_all_numbers=use_all_numbers),
        "martingale": martingale_plan(100.0),
    }


def dashboard_summary() -> dict[str, Any]:
    """Resumen de todas las provincias para la vista general."""
    items = []
    for pid, cfg in PROVINCES.items():
        draws = get_draws(province=pid, days=AI_ANALYSIS_DAYS)
        if not draws:
            items.append(
                {
                    "province": pid,
                    "name": cfg["name"],
                    "has_data": False,
                    "math_digit": None,
                    "ai_digit": None,
                }
            )
            continue
        next_info = get_next_draw(province=pid)
        target = next_info["next_draw"]
        math = predict_digit(draws, target)
        from backend.ai_agent import analyze_5_days
        from backend.expert_analysis import expert_recommendation

        ai = analyze_5_days(draws, target, province=pid)
        expert = expert_recommendation(draws, target, pid)
        seq = expert.get("sequences", {})
        items.append(
            {
                "province": pid,
                "name": cfg["name"],
                "has_data": True,
                "next_draw": next_info,
                "math_digit": math["digit"],
                "math_prob": math["probability"],
                "ai_digit": ai["recommended_digit"],
                "ai_prob": ai["confidence"],
                "expert_digit": expert["my_pick"],
                "expert_confidence": expert["confidence"],
                "best_model": expert["precision_comparison"]["winner"]["label"],
                "last_digits": seq.get("last_digits", []),
                "verdict_short": expert.get("agent_says", expert.get("verdict_summary", "")),
                "play_message": expert.get("play_message", "JUGA ESTE"),
                "play_callout": expert.get("play_callout", ""),
                "agent_says": expert.get("agent_says", ""),
            }
        )
    return {"provinces": items, "updated_at": datetime.now().isoformat(timespec="seconds")}
