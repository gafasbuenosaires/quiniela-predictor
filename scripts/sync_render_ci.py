"""Scrapea sorteos y los empuja a Render — pensado para GitHub Actions (sin PC)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database import init_db  # noqa: E402
from backend.scraper import sync_all_provinces  # noqa: E402
from backend.seed.loader import export_draws_snapshot  # noqa: E402

RENDER_URL = os.getenv("RENDER_URL", "https://quiniela-predictor-xxbq.onrender.com").rstrip("/")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
DAYS = int(os.getenv("SYNC_DAYS", "30"))


def wake_render(client: httpx.Client) -> None:
    try:
        r = client.get(f"{RENDER_URL}/health", timeout=90.0)
        print(f"Render wake: {r.status_code}")
    except Exception as exc:
        print(f"Render wake (continua igual): {exc}")


def main() -> None:
    if not APP_PASSWORD:
        print("ERROR: falta APP_PASSWORD en secrets de GitHub")
        sys.exit(1)

    init_db()
    print("Scrapeando sorteos...")
    try:
        result = sync_all_provinces(DAYS)
        print(f"Scrape OK: {result.get('total_records_upserted', 0)} registros")
    except Exception as exc:
        print(f"Scrape parcial/error: {exc}")

    rows = export_draws_snapshot(DAYS)
    if not rows:
        print("ERROR: sin sorteos para enviar")
        sys.exit(1)

    print(f"Enviando {len(rows)} registros a {RENDER_URL} ...")
    with httpx.Client() as client:
        wake_render(client)
        resp = client.post(
            f"{RENDER_URL}/api/import-draws",
            json={"rows": rows},
            headers={"X-App-Password": APP_PASSWORD},
            timeout=180.0,
        )
        resp.raise_for_status()
        data = resp.json()

    print(f"Render: +{data.get('records_upserted', 0)} registros")
    synced = data.get("draw_sync") or data.get("state", {}).get("session", {}).get("auto_sync", {}).get("draws_today")
    if synced:
        done = [d for d in synced if isinstance(d, dict) and d.get("has_result")]
        print(f"Sorteos hoy con resultado: {len(done)}")
    caja = data.get("state", {}).get("caja", {})
    if caja:
        print(f"Caja: {caja.get('jugadas', 0)} jugadas · neto ${caja.get('neto', 0):,.0f}")


if __name__ == "__main__":
    main()
