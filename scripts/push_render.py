"""Empuja sorteos locales a la app en Render."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import PROVINCES  # noqa: E402
from backend.database import get_draws  # noqa: E402
from backend.scraper import sync_all_provinces  # noqa: E402
from backend.seed.loader import SEED_FILE, export_draws_snapshot  # noqa: E402

RENDER_URL = os.getenv("RENDER_URL", "https://quiniela-predictor-xxbq.onrender.com").rstrip("/")
APP_PASSWORD = os.getenv("APP_PASSWORD", "quini1236")


def main() -> None:
    print("Sincronizando local...")
    try:
        sync_all_provinces(30)
    except Exception as exc:
        print(f"Sync local parcial: {exc}")

    rows = export_draws_snapshot(30)
    print(f"Enviando {len(rows)} registros a {RENDER_URL} ...")

    resp = httpx.post(
        f"{RENDER_URL}/api/import-draws",
        json={"rows": rows},
        headers={"X-App-Password": APP_PASSWORD},
        timeout=180.0,
    )
    resp.raise_for_status()
    data = resp.json()
    print(f"Render: +{data.get('records_upserted', 0)} registros")
    caja = data.get("state", {}).get("caja", {})
    print(f"Caja: {caja.get('jugadas', 0)} jugadas · neto ${caja.get('neto', 0):,.0f}")

    SEED_FILE.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"Seed actualizado: {SEED_FILE.name}")


if __name__ == "__main__":
    main()
