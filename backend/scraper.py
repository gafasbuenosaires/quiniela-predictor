import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

from backend.config import (
    DEFAULT_PROVINCE,
    HISTORY_DAYS,
    PROVINCES,
    SITE_BASE,
    USER_AGENT,
)
from backend.database import log_sync, upsert_draws

DRAW_NAME_MAP = {
    "la primera": "primera",
    "primera": "primera",
    "el primero": "primera",
    "el primer": "primera",
    "matutina": "matutina",
    "vespertina": "vespertina",
    "nocturna": "nocturna",
}

FOUR_DIGIT = re.compile(r"\b(\d{4})\b")
SORTEO_LINK = re.compile(r"sorteo-(\d{2})-(\d{2})-(\d{4})\.htm", re.I)


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    )


def _normalize_draw_type(name: str) -> str | None:
    key = name.strip().lower().replace("la ", "")
    return DRAW_NAME_MAP.get(key)


def _last_digit(number: str) -> int:
    return int(number[-1])


def parse_html(html: str, draw_date: str, province: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict[str, Any]] = []

    for tag in soup.find_all(["h2", "h3"]):
        dtype = _normalize_draw_type(tag.get_text())
        if not dtype:
            continue
        table = tag.find_next("table")
        if not table:
            continue
        numbers = FOUR_DIGIT.findall(table.get_text(" ", strip=True))
        for pos, num in enumerate(numbers[:20], start=1):
            rows.append(
                {
                    "province": province,
                    "draw_date": draw_date,
                    "draw_type": dtype,
                    "position": pos,
                    "number": num.zfill(4),
                    "last_digit": _last_digit(num),
                }
            )

    if rows:
        return rows

    panel_map = {1: "primera", 2: "matutina", 3: "vespertina", 4: "nocturna"}
    for panel_id, dtype in panel_map.items():
        panel = soup.find(id=f"q_ResultadosQuiniela{panel_id}_Panel1")
        if not panel:
            continue
        spans = panel.find_all(
            "span", id=re.compile(rf"q_ResultadosQuiniela{panel_id}_u\d+")
        )
        for pos, span in enumerate(spans[:20], start=1):
            num = span.get_text(strip=True)
            if len(num) == 4 and num.isdigit():
                rows.append(
                    {
                        "province": province,
                        "draw_date": draw_date,
                        "draw_type": dtype,
                        "position": pos,
                        "number": num,
                        "last_digit": _last_digit(num),
                    }
                )
    return rows


def _parse_date_from_title(html: str, fallback: date) -> str:
    m = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", html)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{mo}-{d}"
    return fallback.isoformat()


def _url_for_day(province_id: str, d: date) -> tuple[str, str]:
    cfg = PROVINCES[province_id]
    slug = cfg["slug"]
    iso = d.isoformat()

    if province_id == "nacional":
        if d == date.today():
            return f"{SITE_BASE}/nacional/", iso
        if d == date.today() - timedelta(days=1):
            return f"{SITE_BASE}/nacional/ayer.aspx", iso
        dd = f"{d.day:02d}-{d.month:02d}-{d.year}"
        return f"{SITE_BASE}/nacional/sorteo-{dd}.htm", iso

    if d == date.today():
        return f"{SITE_BASE}/{slug}-hoy.aspx", iso
    if d == date.today() - timedelta(days=1):
        return f"{SITE_BASE}/{slug}-ayer.aspx", iso
    dd = f"{d.day:02d}-{d.month:02d}-{d.year}"
    return f"{SITE_BASE}/{slug}-sorteo-{dd}.htm", iso


def fetch_sorteo_links(province_id: str, client: httpx.Client, limit: int = 35) -> list[str]:
    """Enlaces históricos (solo nacional tiene listado directo)."""
    if province_id != "nacional":
        return []
    url = f"{SITE_BASE}/nacional/sorteos-anteriores.aspx"
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError:
        return []
    links: list[str] = []
    for m in SORTEO_LINK.finditer(resp.text):
        dd, mm, yyyy = m.groups()
        path = f"/quinielas/nacional/sorteo-{dd}-{mm}-{yyyy}.htm"
        full = f"https://www.quini-6-resultados.com.ar{path}"
        if full not in links:
            links.append(full)
        if len(links) >= limit:
            break
    return links


def fetch_url(url: str, draw_date: str, province: str, client: httpx.Client) -> list[dict]:
    try:
        resp = client.get(url)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
    except httpx.HTTPError:
        return []
    parsed_date = _parse_date_from_title(resp.text[:3000], date.fromisoformat(draw_date))
    return parse_html(resp.text, parsed_date, province)


def fetch_day(province_id: str, d: date, client: httpx.Client) -> list[dict[str, Any]]:
    url, draw_date = _url_for_day(province_id, d)
    return fetch_url(url, draw_date, province_id, client)


def sync_province(province_id: str, days: int = HISTORY_DAYS) -> dict[str, Any]:
    if province_id not in PROVINCES:
        raise ValueError(f"Provincia desconocida: {province_id}")

    cfg = PROVINCES[province_id]
    today = date.today()
    all_rows: list[dict[str, Any]] = []
    days_ok = 0
    seen_dates: set[str] = set()

    with _client() as client:
        if cfg.get("has_history_htm"):
            for link in fetch_sorteo_links(province_id, client, limit=days + 5):
                m = SORTEO_LINK.search(link)
                if not m:
                    continue
                dd, mm, yyyy = m.groups()
                draw_date = f"{yyyy}-{mm}-{dd}"
                if draw_date in seen_dates:
                    continue
                rows = fetch_url(link, draw_date, province_id, client)
                if rows:
                    all_rows.extend(rows)
                    seen_dates.add(draw_date)
                    days_ok += 1

        for offset in range(days + 1):
            d = today - timedelta(days=offset)
            iso = d.isoformat()
            if iso in seen_dates:
                continue
            rows = fetch_day(province_id, d, client)
            if rows:
                all_rows.extend(rows)
                seen_dates.add(iso)
                days_ok += 1

    added = upsert_draws(all_rows)
    name = cfg["name"]
    log_sync(
        days_ok,
        added,
        f"{name}: {days_ok} días, {added} registros",
        province=province_id,
    )
    return {
        "province": province_id,
        "province_name": name,
        "days_requested": days,
        "days_with_data": days_ok,
        "records_upserted": added,
    }


def sync_all_provinces(days: int = HISTORY_DAYS) -> dict[str, Any]:
    results: dict[str, Any] = {}
    total_records = 0
    for pid in PROVINCES:
        try:
            results[pid] = sync_province(pid, days)
            total_records += results[pid]["records_upserted"]
        except Exception as exc:
            results[pid] = {"error": str(exc)}
    return {
        "provinces": results,
        "total_records_upserted": total_records,
    }


# Compatibilidad con código anterior
def sync_history(days: int = HISTORY_DAYS, province: str = DEFAULT_PROVINCE) -> dict[str, Any]:
    if province == "all":
        return sync_all_provinces(days)
    return sync_province(province, days)
