"""Carga snapshot local de sorteos si la DB arranca vacia."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.database import get_draws, upsert_draws

logger = logging.getLogger(__name__)
SEED_FILE = Path(__file__).resolve().parent / "draws_30d.json"


def load_seed_draws() -> int:
    if not SEED_FILE.exists():
        logger.warning("Seed file missing: %s", SEED_FILE)
        return 0
    rows = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    added = upsert_draws(rows)
    logger.info("Seed loaded: %s rows upserted from %s", added, SEED_FILE.name)
    return added


def ensure_draws(min_records: int = 1) -> dict[str, int | bool]:
    """Carga seed si no hay sorteos en la base."""
    current = len(get_draws(days=30))
    if current >= min_records:
        return {"seeded": False, "records_before": current, "records_added": 0}
    added = load_seed_draws()
    after = len(get_draws(days=30))
    return {"seeded": added > 0, "records_before": current, "records_added": added, "records_after": after}
