"""Agente de análisis: últimos 5 días + opcional OpenAI."""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from backend.analyzer import _frequency, _gap_scores, _markov_scores, _weighted_blend, predict_digit
from backend.config import AI_ANALYSIS_DAYS, DEFAULT_PROVINCE, DRAW_TIMES, PROVINCES
from backend.database import get_draws


def _build_context(draws: list[dict], draw_type: str) -> str:
    dates = sorted({d["draw_date"] for d in draws}, reverse=True)[:AI_ANALYSIS_DAYS]
    lines = [f"Análisis últimos {AI_ANALYSIS_DAYS} días para sorteo '{draw_type}':"]
    lines.append("Última cifra del premio #1 por fecha y sorteo:\n")

    for d in sorted(dates):
        day_rows = [
            r
            for r in draws
            if r["draw_date"] == d and r["draw_type"] == draw_type and r["position"] == 1
        ]
        if day_rows:
            num = day_rows[0]["number"]
            digit = day_rows[0]["last_digit"]
            lines.append(f"  {d}: {num} → terminación {digit}")

    subset = [r for r in draws if r["draw_date"] in dates and r["draw_type"] == draw_type]
    all_last = [r["last_digit"] for r in subset]
    freq = Counter(all_last)
    lines.append("\nFrecuencia última cifra (todos los 20 números, 5 días):")
    for digit, count in freq.most_common():
        lines.append(f"  {digit}: {count} veces")

    examples = []
    for r in subset[:15]:
        examples.append(r["number"])
    if examples:
        lines.append(f"\nEjemplos recientes: {', '.join(examples[:12])}")
        term = [n[-1] for n in examples[:12]]
        lines.append(f"Terminaciones: {''.join(term)}")

    return "\n".join(lines)


def analyze_5_days(
    draws: list[dict] | None = None,
    draw_type: str = "primera",
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    draws = draws or get_draws(province=province)
    dates = sorted({d["draw_date"] for d in draws}, reverse=True)[:AI_ANALYSIS_DAYS]
    subset = [d for d in draws if d["draw_date"] in dates]

    type_subset = [d for d in subset if d["draw_type"] == draw_type]
    prize_digits = [d["last_digit"] for d in type_subset if d["position"] == 1]
    all_digits = [d["last_digit"] for d in type_subset]

    freq_prize = _frequency(prize_digits)
    freq_all = _frequency(all_digits)
    gaps = _gap_scores(subset, draw_type)
    markov = _markov_scores(subset, draw_type)

    # Pesos más agresivos en recencia (5 días)
    # Prioriza terminaciones de los 20 números (ej. 4354→4, 7664→4)
    probs = _weighted_blend(freq_all, gaps, markov, (0.50, 0.25, 0.25))
    best = max(probs, key=probs.get)

    reasoning = _local_reasoning(dates, type_subset, best, probs, freq_all)

    result: dict[str, Any] = {
        "agent": "estadístico-IA-local",
        "province": province,
        "province_name": PROVINCES.get(province, {}).get("name", province),
        "analysis_days": AI_ANALYSIS_DAYS,
        "target_draw_type": draw_type,
        "recommended_digit": best,
        "confidence": round(probs[best], 4),
        "probabilities": {str(k): round(v, 4) for k, v in sorted(probs.items(), key=lambda x: -x[1])},
        "reasoning": reasoning,
        "context_summary": _build_context(draws, draw_type),
        "comparison_30d": predict_digit(draws, draw_type),
    }

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            ai_text = _openai_analysis(_build_context(draws, draw_type), openai_key)
            result["openai_insight"] = ai_text
            result["agent"] = "híbrido (local + OpenAI)"
        except Exception as exc:
            result["openai_error"] = str(exc)

    return result


def _local_reasoning(
    dates: list[str],
    rows: list[dict],
    digit: int,
    probs: dict[int, float],
    freq: dict[int, float],
) -> list[str]:
    lines = [
        f"JUGA ESTE: {digit}.",
        f"Ventana: {len(dates)} días calendario con datos.",
        f"Dígito recomendado: {digit} (prob. estimada {probs[digit]:.1%}).",
    ]
    top3 = sorted(probs.items(), key=lambda x: -x[1])[:3]
    lines.append(
        "Top 3: " + ", ".join(f"{d} ({p:.1%})" for d, p in top3)
    )
    hot = sorted(freq.items(), key=lambda x: -x[1])[:2]
    cold = sorted(freq.items(), key=lambda x: x[1])[:2]
    lines.append(f"Más salidores (5d, todos los números): {hot[0][0]} y {hot[1][0]}")
    lines.append(f"Menos salidores: {cold[0][0]} y {cold[1][0]}")
    lines.append(
        "Método: frecuencia reciente + atraso (gap) + cadena de Markov sobre premio #1."
    )
    lines.append(
        "Aviso: cada sorteo es independiente; la estadística describe el pasado, no predice con certeza."
    )
    return lines


def _openai_analysis(context: str, api_key: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": (
                    "Sos un analista de quiniela argentina. Respondé en español, breve. "
                    "Solo analizás la ÚLTIMA CIFRA (0-9) de los números. "
                    "Indicá un dígito recomendado y 3 razones numéricas. "
                    "Siempre aclarar que no hay garantía de acierto."
                ),
            },
            {"role": "user", "content": context + "\n\n¿Qué terminación (0-9) es más probable en el próximo sorteo?"},
        ],
        max_tokens=400,
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


def analyze_all_draws(
    draws: list[dict] | None = None,
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    draws = draws or get_draws(province=province)
    return {
        d["id"]: analyze_5_days(draws, d["id"], province=province)
        for d in DRAW_TIMES
    }
