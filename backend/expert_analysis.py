"""Análisis avanzado: secuencias, día vs mes, recomendación experta."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from backend.analyzer import (
    _frequency,
    _gap_scores,
    _markov_scores,
    _weighted_blend,
    predict_digit,
)
from backend.config import AI_ANALYSIS_DAYS, DEFAULT_PROVINCE, DRAW_TIMES, HISTORY_DAYS


def _draw_label(draw_type: str) -> str:
    for d in DRAW_TIMES:
        if d["id"] == draw_type:
            return d["name"]
    return draw_type


def latest_day_snapshot(draws: list[dict]) -> dict[str, Any]:
    """Todos los sorteos del ultimo dia cargado (premio #1)."""
    dates = sorted({d["draw_date"] for d in draws}, reverse=True)
    if not dates:
        return {"date": None, "draws": [], "note": ""}
    latest = dates[0]
    order = {d["id"]: i for i, d in enumerate(DRAW_TIMES)}
    rows = [
        d
        for d in draws
        if d["draw_date"] == latest and d["position"] == 1
    ]
    rows.sort(key=lambda x: order.get(x["draw_type"], 99))
    items = [
        {
            "draw_type": r["draw_type"],
            "draw_name": _draw_label(r["draw_type"]),
            "number": r["number"],
            "last_digit": r["last_digit"],
        }
        for r in rows
    ]
    return {
        "date": latest,
        "draws": items,
        "note": (
            "Fuente: quini-6-resultados (4 sorteos: Primera, Matutina, Vespertina, Nocturna). "
            "La Previa no esta en esta fuente."
        ),
    }


def _prize_series(draws: list[dict], draw_type: str) -> list[dict]:
    """Serie cronológica del premio #1 para un horario."""
    rows = [
        d
        for d in draws
        if d["draw_type"] == draw_type and d["position"] == 1
    ]
    rows.sort(key=lambda x: (x["draw_date"], x["draw_type"]))
    return rows


def _month_key(draw_date: str) -> str:
    return draw_date[:7]


def _predict_from_draws(train: list[dict], draw_type: str) -> int:
    if not train:
        return 0
    digits = [d["last_digit"] for d in train if d["draw_type"] == draw_type]
    if not digits:
        digits = [d["last_digit"] for d in train]
    freq = _frequency(digits)
    gaps = _gap_scores(train, draw_type)
    markov = _markov_scores(train, draw_type)
    probs = _weighted_blend(freq, gaps, markov, (0.4, 0.35, 0.25))
    return max(probs, key=probs.get)


def analyze_sequences(draws: list[dict], draw_type: str, tail: int = 12) -> dict[str, Any]:
    series = _prize_series(draws, draw_type)
    if not series:
        return {"sequence": [], "streaks": {}, "transitions": []}

    recent = series[-tail:]
    seq = [
        {
            "date": r["draw_date"],
            "number": r["number"],
            "digit": r["last_digit"],
            "draw_type": r["draw_type"],
        }
        for r in recent
    ]

    digits = [r["last_digit"] for r in recent]
    streak_digit = digits[-1]
    streak_len = 1
    for d in reversed(digits[:-1]):
        if d == streak_digit:
            streak_len += 1
        else:
            break

    transitions: list[dict] = []
    for i in range(1, len(digits)):
        transitions.append({"from": digits[i - 1], "to": digits[i]})

    trans_counter = Counter((t["from"], t["to"]) for t in transitions)
    top_trans = trans_counter.most_common(3)

    freq = Counter(digits)
    last_digit = digits[-1]
    markov_next = _markov_scores(draws, draw_type)
    likely_after_last = max(markov_next, key=markov_next.get)

    return {
        "sequence": seq,
        "last_digits": digits,
        "sequence_text": " → ".join(str(d) for d in digits),
        "current_streak": {"digit": streak_digit, "length": streak_len},
        "frequency_in_window": dict(freq),
        "top_transitions": [
            {"from": a, "to": b, "count": c} for (a, b), c in top_trans
        ],
        "after_last_digit": {
            "last": last_digit,
            "markov_suggests": likely_after_last,
            "markov_prob": round(markov_next[likely_after_last], 4),
        },
        "hot_in_sequence": freq.most_common(2),
        "cold_in_sequence": sorted(freq.items(), key=lambda x: x[1])[:2],
    }


def _backtest_one(
    series: list[dict],
    all_draws: list[dict],
    draw_type: str,
    mode: str,
    window_days: int = 5,
) -> dict[str, Any]:
    """
    mode: daily_5 | daily_30 | monthly
    Predice sorteo i usando solo datos anteriores a i.
    """
    hits = 0
    tests = 0
    min_train = 8

    for i in range(min_train, len(series)):
        target = series[i]
        actual = target["last_digit"]
        cutoff_date = target["draw_date"]

        if mode == "monthly":
            month = _month_key(cutoff_date)
            train = [
                d
                for d in all_draws
                if d["draw_type"] == draw_type
                and d["position"] == 1
                and _month_key(d["draw_date"]) == month
                and d["draw_date"] < cutoff_date
            ]
        else:
            if mode == "daily_5":
                days = 5
            elif mode == "weekly_7":
                days = 7
            else:
                days = 30
            date_set = _week_dates_before(series[:i], cutoff_date, days)
            train = [
                d
                for d in all_draws
                if d["draw_type"] == draw_type
                and d["position"] == 1
                and d["draw_date"] in date_set
            ]

        if len(train) < 4:
            continue

        pred = _predict_from_draws(train, draw_type)
        if pred == actual:
            hits += 1
        tests += 1

    rate = hits / tests if tests else 0
    baseline = 0.10
    return {
        "mode": mode,
        "label": _mode_label(mode),
        "hits": hits,
        "tests": tests,
        "hit_rate": round(rate, 4),
        "hit_rate_pct": round(100 * rate, 1),
        "vs_random": round(100 * (rate - baseline), 1),
    }


def _mode_label(mode: str) -> str:
    return {
        "daily_5": "Por día (últimos 5 días)",
        "weekly_7": "Por semana (últimos 7 días)",
        "daily_30": "Por día (últimos 30 días)",
        "monthly": "Por mes (mismo mes calendario)",
    }.get(mode, mode)


def _week_dates_before(series: list[dict], cutoff_date: str, days: int = 7) -> set[str]:
    dates_before = sorted(
        {s["draw_date"] for s in series if s["draw_date"] < cutoff_date},
        reverse=True,
    )[:days]
    return set(dates_before)


def compare_daily_vs_monthly(draws: list[dict], draw_type: str) -> dict[str, Any]:
    series = _prize_series(draws, draw_type)
    results = [
        _backtest_one(series, draws, draw_type, "daily_5", 5),
        _backtest_one(series, draws, draw_type, "weekly_7", 7),
        _backtest_one(series, draws, draw_type, "daily_30", 30),
        _backtest_one(series, draws, draw_type, "monthly"),
    ]
    valid = [r for r in results if r["tests"] >= 5]
    if not valid:
        winner = results[0]
        verdict = "Datos insuficientes para comparar; se usa ventana de 5 días por defecto."
    else:
        winner = max(valid, key=lambda x: x["hit_rate"])
        second = sorted(valid, key=lambda x: -x["hit_rate"])[1] if len(valid) > 1 else None
        diff = (
            round(winner["hit_rate_pct"] - second["hit_rate_pct"], 1)
            if second
            else 0
        )
        if winner["mode"] == "weekly_7":
            verdict = (
                f"Históricamente, analizar **por semana** ({winner['hit_rate_pct']}% aciertos) "
                f"superó al resto (+{diff}% vs el segundo)."
            )
        elif winner["mode"].startswith("daily"):
            verdict = (
                f"Históricamente, analizar **por día** ({winner['label']}) acertó más "
                f"({winner['hit_rate_pct']}% vs azar 10%, +{diff}% vs otros períodos)."
            )
        else:
            verdict = (
                f"Históricamente, analizar **por mes** fue lo más preciso "
                f"({winner['hit_rate_pct']}%). El patrón del mes en curso pesa más."
            )

    return {
        "models": results,
        "winner": winner,
        "verdict": verdict,
        "recommendation": (
            "daily" if winner["mode"].startswith("daily") else "monthly"
        ),
    }


def _current_predictions_by_mode(
    draws: list[dict], draw_type: str, best_mode: str
) -> dict[str, Any]:
    dates_all = sorted({d["draw_date"] for d in draws}, reverse=True)
    today_month = _month_key(dates_all[0]) if dates_all else ""

    dates_recent = sorted({d["draw_date"] for d in draws}, reverse=True)
    week_dates = set(dates_recent[:7])
    week_draws = [d for d in draws if d["draw_date"] in week_dates and d["position"] == 1]

    pred_5 = predict_digit(draws, draw_type, days_weight=5)
    pred_30 = predict_digit(draws, draw_type, days_weight=30)
    week_digit = _predict_from_draws(
        [d for d in draws if d["draw_date"] in week_dates], draw_type
    )

    month_draws = [d for d in draws if _month_key(d["draw_date"]) == today_month]
    month_digit = _predict_from_draws(
        [d for d in month_draws if d["position"] == 1], draw_type
    )

    return {
        "daily_5": {"digit": pred_5["digit"], "prob": pred_5["probability"], "label": "por día (5 días)"},
        "weekly_7": {
            "digit": week_digit,
            "label": "por semana (7 días)",
            "samples": len(week_draws),
        },
        "daily_30": {"digit": pred_30["digit"], "prob": pred_30["probability"], "label": "por día (30 días)"},
        "monthly": {
            "digit": month_digit,
            "month": today_month,
            "samples": len([d for d in month_draws if d["position"] == 1]),
            "label": "por mes",
        },
        "best_mode": best_mode,
    }


def expert_recommendation(
    draws: list[dict],
    draw_type: str,
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    """Recomendación final con texto claro más allá del porcentaje."""
    comparison = compare_daily_vs_monthly(draws, draw_type)
    sequences = analyze_sequences(draws, draw_type)
    preds = _current_predictions_by_mode(
        draws, draw_type, comparison["recommendation"]
    )

    winner_mode = comparison["winner"]["mode"]
    votes: Counter[int] = Counter()

    w_map = {"daily_5": 1.0, "weekly_7": 1.1, "daily_30": 1.2, "monthly": 1.0}
    if winner_mode == "daily_5":
        w_map["daily_5"] = 2.0
        w_map["weekly_7"] = 1.4
    elif winner_mode == "weekly_7":
        w_map["weekly_7"] = 2.2
        w_map["daily_5"] = 1.3
    elif winner_mode == "daily_30":
        w_map["daily_30"] = 2.0
        w_map["weekly_7"] = 1.2
    else:
        w_map["monthly"] = 2.2

    for mode, data in [
        ("daily_5", preds["daily_5"]),
        ("weekly_7", preds["weekly_7"]),
        ("daily_30", preds["daily_30"]),
        ("monthly", preds["monthly"]),
    ]:
        d = data["digit"]
        prob = data.get("prob", 0.15)
        votes[d] += w_map[mode] * prob

    seq = sequences
    if seq.get("last_digits"):
        hot = seq["hot_in_sequence"][0][0]
        votes[hot] += 0.35
        markov_d = seq["after_last_digit"]["markov_suggests"]
        votes[markov_d] += 0.5 * seq["after_last_digit"]["markov_prob"]

    final_digit = max(votes, key=votes.get)
    total_vote = sum(votes.values()) or 1
    confidence = round(votes[final_digit] / total_vote, 4)

    alt = sorted(votes.items(), key=lambda x: -x[1])[1:3]

    reasons = _build_verdict_reasons(
        final_digit, comparison, sequences, preds, winner_mode
    )
    agent_says = _build_agent_message(
        final_digit, comparison, sequences, preds, winner_mode, confidence, draw_type
    )
    day_snap = latest_day_snapshot(draws)

    return {
        "province": province,
        "draw_type": draw_type,
        "draw_type_label": _draw_label(draw_type),
        "my_pick": final_digit,
        "confidence": confidence,
        "play_message": "JUGA ESTE",
        "play_callout": f"JUGÁ LA TERMINACIÓN {final_digit} EN {_draw_label(draw_type).upper()}",
        "agent_says": agent_says,
        "verdict_title": f"JUGA ESTE — terminación {final_digit}",
        "verdict_summary": agent_says,
        "reasons": reasons,
        "alternatives": [{"digit": d, "weight": round(w, 3)} for d, w in alt],
        "precision_comparison": comparison,
        "sequences": sequences,
        "model_predictions": preds,
        "analysis_by_period": {
            "day": preds["daily_5"],
            "week": preds["weekly_7"],
            "month": preds["monthly"],
            "day_30": preds["daily_30"],
        },
        "latest_day": day_snap,
        "sequence_scope": (
            f"Ultimas terminaciones del premio #1 en sorteos '{_draw_label(draw_type)}' "
            "(no mezcla Matutina/Vespertina/Nocturna del mismo dia)."
        ),
        "disclaimer": (
            "Análisis histórico; no garantiza el resultado. Juego responsable."
        ),
    }


def _build_agent_message(
    digit: int,
    comparison: dict,
    sequences: dict,
    preds: dict,
    winner_mode: str,
    confidence: float,
    draw_type: str = "primera",
) -> str:
    win = comparison["winner"]
    dlabel = _draw_label(draw_type)
    d5 = preds["daily_5"]["digit"]
    w7 = preds["weekly_7"]["digit"]
    m = preds["monthly"]["digit"]
    d30 = preds["daily_30"]["digit"]

    msg = (
        f"JUGA ESTE: el {digit} en {dlabel}. "
        f"Analicé el historial por DÍA (últimos 5 días marca el {d5}), "
        f"por SEMANA (últimos 7 días marca el {w7}), "
        f"por MES (mes actual marca el {m}) "
        f"y la ventana amplia de 30 días marca el {d30}. "
    )
    if sequences.get("sequence_text"):
        msg += (
            f"La secuencia de {dlabel} (solo ese horario, premio #1) fue: "
            f"{sequences['sequence_text']}. "
        )

    msg += (
        f"Comparando qué método acertó más en el pasado, ganó el análisis "
        f"{win['label']} ({win['hit_rate_pct']}% de aciertos en {win['tests']} sorteos). "
        f"Por eso, históricamente lo más coherente para el próximo sorteo es el {digit} "
        f"(confianza del modelo {confidence:.0%}). "
        f"No es certeza: cada sorteo es independiente."
    )
    return msg


def _build_verdict_reasons(
    digit: int,
    comparison: dict,
    sequences: dict,
    preds: dict,
    winner_mode: str,
) -> list[str]:
    lines: list[str] = []
    win = comparison["winner"]
    lines.append(
        f"Modelo más preciso en tu historial: {win['label']} "
        f"({win['hit_rate_pct']}% aciertos en {win['tests']} pruebas)."
    )

    if winner_mode == "daily_5":
        lines.append(
            f"Por DÍA (5 días): sugiere el **{preds['daily_5']['digit']}**."
        )
    elif winner_mode == "weekly_7":
        lines.append(
            f"Por SEMANA (7 días): sugiere el **{preds['weekly_7']['digit']}** "
            f"({preds['weekly_7'].get('samples', 0)} sorteos en la semana)."
        )
    elif winner_mode == "daily_30":
        lines.append(
            f"Ventana de 30 días sugiere el **{preds['daily_30']['digit']}**; "
            f"hay más datos y la señal es más estable que solo 5 días."
        )
    else:
        m = preds["monthly"]
        lines.append(
            f"Patrón del mes ({m['month']}) apunta al **{m['digit']}** "
            f"({m['samples']} sorteos en el mes)."
        )

    if sequences.get("sequence_text"):
        lines.append(f"Últimas terminaciones: {sequences['sequence_text']}.")
        st = sequences.get("current_streak", {})
        if st.get("length", 0) >= 2:
            lines.append(
                f"Racha: salió **{st['digit']}** {st['length']} veces seguidas "
                f"(puede repetir o cortar; Markov sugiere "
                f"{sequences['after_last_digit']['markov_suggests']} después del "
                f"{sequences['after_last_digit']['last']})."
            )

    hot = sequences.get("hot_in_sequence", [])
    if hot:
        lines.append(
            f"En los últimos sorteos, lo más salidor fue **{hot[0][0]}** ({hot[0][1]} veces)."
        )

    lines.append(
        f"**Conclusión:** combinando día/mes, secuencias y Markov, "
        f"el dígito con más peso es **{digit}**."
    )
    return lines


def _today_result(draws: list[dict], draw_date: str, draw_type: str) -> dict | None:
    row = next(
        (
            d
            for d in draws
            if d["draw_date"] == draw_date
            and d["draw_type"] == draw_type
            and d["position"] == 1
        ),
        None,
    )
    if not row:
        return None
    return {
        "number": row["number"],
        "last_digit": row["last_digit"],
    }


def _compact_expert(expert: dict) -> dict:
    return {
        "pick": expert["my_pick"],
        "confidence": expert["confidence"],
        "play_callout": expert["play_callout"],
        "agent_says": expert["agent_says"],
        "ranking_top3": expert.get("alternatives", [])[:2],
        "precision_winner": expert["precision_comparison"]["winner"]["label"],
        "precision_pct": expert["precision_comparison"]["winner"]["hit_rate_pct"],
        "last_sequence": expert["sequences"].get("last_digits", [])[-6:],
        "models": expert["model_predictions"],
    }


def analyze_full_day(
    draws: list[dict],
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    """Estadistica y probabilidad completa para las 4 quinielas del dia."""
    from backend.ai_agent import analyze_5_days
    from backend.analyzer import get_next_draw, predict_digit

    next_info = get_next_draw(province=province)
    target_date = next_info["target_date"]
    completed = set(next_info.get("completed_today") or [])
    day_snap = latest_day_snapshot(draws)

    slots: list[dict] = []
    for slot in DRAW_TIMES:
        sid = slot["id"]
        expert = expert_recommendation(draws, sid, province)
        math = predict_digit(draws, sid, use_all_numbers=True)
        ai = analyze_5_days(draws, sid, province=province)

        status = "done" if sid in completed else "next" if sid == next_info["next_draw"] else "pending"
        today_res = _today_result(draws, target_date, sid) if status == "done" else None

        yesterday = next(
            (d for d in day_snap.get("draws", []) if d["draw_type"] == sid),
            None,
        )

        slots.append(
            {
                "draw_type": sid,
                "draw_name": slot["name"],
                "hour": slot["hour"],
                "minute": slot.get("minute", 0),
                "time": f"{slot['hour']:02d}:{slot.get('minute', 0):02d} hs",
                "status": status,
                "today_result": today_res,
                "yesterday": yesterday,
                "expert": _compact_expert(expert),
                "math": {
                    "digit": math["digit"],
                    "probability": math["probability"],
                    "ranking": math["ranking"][:5],
                    "sample_size": math["sample_size"],
                },
                "ai": {
                    "digit": ai["recommended_digit"],
                    "confidence": ai["confidence"],
                },
            }
        )

    # Stats del dia completo: terminaciones 30d de las 4 quinielas (premio #1)
    dates_30 = sorted({d["draw_date"] for d in draws}, reverse=True)[:30]
    subset = [d for d in draws if d["draw_date"] in dates_30 and d["position"] == 1]
    by_slot: dict[str, Counter] = {s["id"]: Counter() for s in DRAW_TIMES}
    global_c = Counter()
    for row in subset:
        by_slot[row["draw_type"]][row["last_digit"]] += 1
        global_c[row["last_digit"]] += 1

    total = len(subset) or 1
    cross = _cross_draw_analysis(
        draws, subset, slots, target_date, completed, next_info, global_c, by_slot, total
    )

    return {
        "province": province,
        "target_date": target_date,
        "next_draw": next_info,
        "completed_today": list(completed),
        "draws": slots,
        "latest_day": day_snap,
        "cross_draw": cross,
        "stats_30d_four_draws": {
            "global": [
                {"digit": d, "count": global_c.get(d, 0), "pct": round(100 * global_c.get(d, 0) / total, 1)}
                for d in range(10)
            ],
            "by_draw": {
                sid: [
                    {"digit": d, "count": by_slot[sid].get(d, 0)}
                    for d in range(10)
                ]
                for sid in by_slot
            },
        },
    }


def _daily_chains(draws: list[dict], dates: list[str]) -> list[dict]:
    """Por cada dia, las 4 terminaciones del premio #1 en orden."""
    order = {s["id"]: i for i, s in enumerate(DRAW_TIMES)}
    chains: list[dict] = []
    for day in sorted(dates):
        rows = [
            d
            for d in draws
            if d["draw_date"] == day and d["position"] == 1
        ]
        if len(rows) < 3:
            continue
        rows.sort(key=lambda x: order.get(x["draw_type"], 99))
        digits = [r["last_digit"] for r in rows if r["draw_type"] in order]
        if len(digits) < 3:
            continue
        chains.append(
            {
                "date": day,
                "digits": digits,
                "draw_types": [r["draw_type"] for r in rows[: len(digits)]],
                "unique": len(set(digits)),
            }
        )
    return chains


def _transition_matrix(chains: list[dict]) -> dict[str, dict[int, Counter]]:
    """Transiciones entre quinielas consecutivas del mismo dia."""
    order_ids = [s["id"] for s in DRAW_TIMES]
    trans: dict[str, Counter] = {}
    for chain in chains:
        dts = chain["draw_types"]
        digs = chain["digits"]
        for i in range(len(digs) - 1):
            if dts[i] not in order_ids or dts[i + 1] not in order_ids:
                continue
            key = f"{dts[i]}->{dts[i + 1]}"
            pair = (digs[i], digs[i + 1])
            trans.setdefault(key, Counter())[pair] += 1
    result: dict[str, dict[int, Counter]] = {}
    for key, counter in trans.items():
        by_from: dict[int, Counter] = defaultdict(Counter)
        for (a, b), c in counter.items():
            by_from[a][b] += c
        result[key] = dict(by_from)
    return result


def _cross_draw_analysis(
    draws: list[dict],
    subset: list[dict],
    slots: list[dict],
    target_date: str,
    completed: set[str],
    next_info: dict,
    global_c: Counter,
    by_slot: dict[str, Counter],
    total: int,
) -> dict[str, Any]:
    dates_30 = sorted({d["draw_date"] for d in subset}, reverse=True)[:30]
    chains = _daily_chains(draws, dates_30)
    trans = _transition_matrix(chains)

    global_probs = {d: global_c.get(d, 0) / total for d in range(10)}
    best_global = max(global_probs, key=global_probs.get)

    # Voto cruzado: promedio de las 4 predicciones + frecuencia global
    vote: Counter[int] = Counter()
    slot_votes: dict[str, int] = {}
    for slot in slots:
        sid = slot["draw_type"]
        pick = slot["expert"]["pick"]
        prob = slot["math"]["probability"]
        slot_votes[sid] = pick
        vote[pick] += prob * 1.5
        vote[pick] += global_probs.get(pick, 0)

    # Cadena de hoy: sorteos ya completados + transicion al proximo
    today_digits: list[dict] = []
    for slot in DRAW_TIMES:
        sid = slot["id"]
        if sid not in completed:
            continue
        res = _today_result(draws, target_date, sid)
        if res:
            today_digits.append({"draw_type": sid, "draw_name": slot["name"], **res})

    next_sid = next_info["next_draw"]
    transition_pick = None
    transition_prob = 0.0
    transition_reason = ""
    if today_digits:
        last = today_digits[-1]
        key = f"{last['draw_type']}->{next_sid}"
        if key in trans and last["last_digit"] in trans[key]:
            nxt = trans[key][last["last_digit"]]
            total_t = sum(nxt.values()) or 1
            transition_pick = max(nxt.keys(), key=lambda k: nxt[k])
            transition_prob = nxt[transition_pick] / total_t
            transition_reason = (
                f"Tras {last['draw_name']} con terminacion {last['last_digit']}, "
                f"historicamente en el mismo dia {next_info['next_draw_name']} "
                f"suele salir {transition_pick} ({transition_prob:.0%} de {total_t} casos)."
            )
            vote[transition_pick] += transition_prob * 2

    consensus = max(vote, key=vote.get) if vote else best_global
    vote_total = sum(vote.values()) or 1
    consensus_conf = round(vote[consensus] / vote_total, 4)

    # Comparacion entre las 4 quinielas
    comparison = []
    for slot in DRAW_TIMES:
        sid = slot["id"]
        c = by_slot[sid]
        slot_total = sum(c.values()) or 1
        hot = max(range(10), key=lambda d: c.get(d, 0))
        hot_pct = round(100 * c.get(hot, 0) / slot_total, 1)
        avg_pct = round(100 / 10, 1)
        comparison.append(
            {
                "draw_type": sid,
                "draw_name": slot["name"],
                "predicted": slot_votes.get(sid),
                "math_prob": next(s["math"]["probability"] for s in slots if s["draw_type"] == sid),
                "hot_digit": hot,
                "hot_pct": hot_pct,
                "vs_uniform": round(hot_pct - avg_pct, 1),
                "frequency": [
                    {"digit": d, "count": c.get(d, 0), "pct": round(100 * c.get(d, 0) / slot_total, 1)}
                    for d in range(10)
                ],
            }
        )

    # Patrones intra-dia
    same_all = sum(1 for ch in chains if len(set(ch["digits"])) == 1)
    avg_unique = sum(ch["unique"] for ch in chains) / len(chains) if chains else 0

    ranking = sorted(
        [{"digit": d, "prob": round(global_probs[d], 4), "count": global_c.get(d, 0)} for d in range(10)],
        key=lambda x: -x["prob"],
    )

    agent = (
        f"Entre las 4 quinielas del dia (30 dias, {total} sorteos analizados), "
        f"la terminacion mas frecuente global es el {best_global} ({global_probs[best_global]:.1%}). "
        f"Cruzando las 4 predicciones individuales + transiciones del mismo dia, "
        f"JUGA ESTE el {consensus} en las quinielas pendientes ({consensus_conf:.0%} peso combinado). "
    )
    if transition_reason:
        agent += transition_reason + " "
    agent += (
        f"En un dia tipico salen {avg_unique:.1f} terminaciones distintas entre las 4 quinielas."
    )

    return {
        "consensus": {
            "digit": consensus,
            "confidence": consensus_conf,
            "play_message": "JUGA ESTE",
            "play_callout": f"TERMINACION {consensus} — CRUZANDO LAS 4 QUINIELAS",
            "agent_says": agent,
        },
        "global_combined": {
            "best_digit": best_global,
            "probability": round(global_probs[best_global], 4),
            "total_observations": total,
            "ranking": ranking,
        },
        "comparison": comparison,
        "today_chain": {
            "date": target_date,
            "completed": today_digits,
            "next_draw": next_sid,
            "transition_suggestion": transition_pick,
            "transition_prob": round(transition_prob, 4),
            "transition_reason": transition_reason,
        },
        "within_day": {
            "days_analyzed": len(chains),
            "avg_unique_digits": round(avg_unique, 2),
            "same_digit_all_four_pct": round(100 * same_all / len(chains), 1) if chains else 0,
            "recent_days": chains[-7:],
        },
        "slot_picks": slot_votes,
    }
