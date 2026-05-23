import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from backend.config import DATA_DIR, DB_PATH, DEFAULT_PROVINCE

DATA_DIR.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    with get_conn() as conn:
        _migrate_legacy(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS draws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                province TEXT NOT NULL DEFAULT 'nacional',
                draw_date TEXT NOT NULL,
                draw_type TEXT NOT NULL,
                position INTEGER NOT NULL,
                number TEXT NOT NULL,
                last_digit INTEGER NOT NULL,
                scraped_at TEXT NOT NULL,
                UNIQUE(province, draw_date, draw_type, position)
            );
            CREATE INDEX IF NOT EXISTS idx_draws_province ON draws(province);
            CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(draw_date);

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                province TEXT NOT NULL DEFAULT 'nacional',
                created_at TEXT NOT NULL,
                target_date TEXT NOT NULL,
                target_draw TEXT NOT NULL,
                predicted_digit INTEGER NOT NULL,
                confidence REAL NOT NULL,
                method TEXT NOT NULL,
                hit INTEGER
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                synced_at TEXT NOT NULL,
                province TEXT,
                days_fetched INTEGER NOT NULL,
                records_added INTEGER NOT NULL,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS betting_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                initial_balance REAL NOT NULL DEFAULT 0,
                default_stake REAL NOT NULL DEFAULT 30000,
                payout_multiplier REAL NOT NULL DEFAULT 7,
                auto_advance INTEGER NOT NULL DEFAULT 0,
                double_after_losses INTEGER NOT NULL DEFAULT 6,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS betting_slots (
                province TEXT NOT NULL,
                draw_type TEXT NOT NULL,
                active_digit INTEGER NOT NULL,
                stake REAL NOT NULL DEFAULT 30000,
                base_stake REAL NOT NULL DEFAULT 30000,
                loss_streak INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (province, draw_type)
            );

            CREATE TABLE IF NOT EXISTS betting_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                province TEXT NOT NULL,
                draw_type TEXT NOT NULL,
                draw_date TEXT NOT NULL,
                digit_played INTEGER NOT NULL,
                stake REAL NOT NULL,
                result_digit INTEGER NOT NULL,
                hit INTEGER NOT NULL DEFAULT 0,
                payout REAL NOT NULL DEFAULT 0,
                new_digit INTEGER,
                note TEXT,
                processed_at TEXT NOT NULL,
                UNIQUE(province, draw_type, draw_date)
            );
            CREATE INDEX IF NOT EXISTS idx_betting_entries_date ON betting_entries(draw_date DESC);
            """
        )
        _migrate_sync_log(conn)
        _migrate_betting(conn)
        _seed_betting_settings(conn)


def _migrate_betting(conn: sqlite3.Connection) -> None:
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "betting_settings" not in tables:
        return
    scols = {r[1] for r in conn.execute("PRAGMA table_info(betting_settings)").fetchall()}
    if "double_after_losses" not in scols:
        conn.execute(
            "ALTER TABLE betting_settings ADD COLUMN double_after_losses INTEGER NOT NULL DEFAULT 6"
        )
    if "betting_slots" in tables:
        bcols = {r[1] for r in conn.execute("PRAGMA table_info(betting_slots)").fetchall()}
        if "base_stake" not in bcols:
            conn.execute(
                "ALTER TABLE betting_slots ADD COLUMN base_stake REAL NOT NULL DEFAULT 30000"
            )
        if "loss_streak" not in bcols:
            conn.execute(
                "ALTER TABLE betting_slots ADD COLUMN loss_streak INTEGER NOT NULL DEFAULT 0"
            )


def _seed_betting_settings(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT id FROM betting_settings WHERE id = 1").fetchone()
    now = datetime.now().isoformat(timespec="seconds")
    if not row:
        conn.execute(
            """
            INSERT INTO betting_settings (
                id, initial_balance, default_stake, payout_multiplier,
                auto_advance, double_after_losses, updated_at
            ) VALUES (1, 0, 30000, 7, 0, 6, ?)
            """,
            (now,),
        )


def _migrate_sync_log(conn: sqlite3.Connection) -> None:
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "sync_log" not in tables:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sync_log)").fetchall()}
    if "province" not in cols:
        conn.execute("ALTER TABLE sync_log ADD COLUMN province TEXT")
    if "predictions" in tables:
        pcols = {r[1] for r in conn.execute("PRAGMA table_info(predictions)").fetchall()}
        if "province" not in pcols:
            conn.execute(
                "ALTER TABLE predictions ADD COLUMN province TEXT DEFAULT 'nacional'"
            )


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "draws" not in tables:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(draws)").fetchall()}
    if "province" in cols:
        return
    conn.execute("ALTER TABLE draws RENAME TO draws_old")
    conn.executescript(
        """
        CREATE TABLE draws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            province TEXT NOT NULL DEFAULT 'nacional',
            draw_date TEXT NOT NULL,
            draw_type TEXT NOT NULL,
            position INTEGER NOT NULL,
            number TEXT NOT NULL,
            last_digit INTEGER NOT NULL,
            scraped_at TEXT NOT NULL,
            UNIQUE(province, draw_date, draw_type, position)
        );
        INSERT INTO draws (province, draw_date, draw_type, position, number, last_digit, scraped_at)
        SELECT 'nacional', draw_date, draw_type, position, number, last_digit, scraped_at
        FROM draws_old;
        DROP TABLE draws_old;
        CREATE INDEX IF NOT EXISTS idx_draws_province ON draws(province);
        CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(draw_date);
        """
    )


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_draws(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    added = 0
    with get_conn() as conn:
        for row in rows:
            province = row.get("province", DEFAULT_PROVINCE)
            cur = conn.execute(
                """
                INSERT INTO draws (province, draw_date, draw_type, position, number, last_digit, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(province, draw_date, draw_type, position) DO UPDATE SET
                    number = excluded.number,
                    last_digit = excluded.last_digit,
                    scraped_at = excluded.scraped_at
                """,
                (
                    province,
                    row["draw_date"],
                    row["draw_type"],
                    row["position"],
                    row["number"],
                    row["last_digit"],
                    now,
                ),
            )
            if cur.rowcount:
                added += 1
    return added


def get_draws(
    days: int | None = None,
    draw_type: str | None = None,
    from_date: str | None = None,
    province: str = DEFAULT_PROVINCE,
) -> list[dict]:
    query = "SELECT * FROM draws WHERE province = ?"
    params: list[Any] = [province]
    if draw_type:
        query += " AND draw_type = ?"
        params.append(draw_type)
    if from_date:
        query += " AND draw_date >= ?"
        params.append(from_date)
    query += " ORDER BY draw_date DESC, draw_type, position"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    result = [dict(r) for r in rows]
    if days and not from_date:
        dates = sorted({r["draw_date"] for r in result}, reverse=True)[:days]
        date_set = set(dates)
        result = [r for r in result if r["draw_date"] in date_set]
    return result


def get_province_stats(province: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) as records,
                   COUNT(DISTINCT draw_date) as days
            FROM draws WHERE province = ?
            """,
            (province,),
        ).fetchone()
    return dict(row) if row else {"records": 0, "days": 0}


def log_sync(
    days_fetched: int,
    records_added: int,
    message: str = "",
    province: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sync_log (synced_at, province, days_fetched, records_added, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                province,
                days_fetched,
                records_added,
                message,
            ),
        )


def get_last_sync(province: str | None = None) -> dict | None:
    with get_conn() as conn:
        if province:
            row = conn.execute(
                "SELECT * FROM sync_log WHERE province = ? ORDER BY id DESC LIMIT 1",
                (province,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
    return dict(row) if row else None


def save_prediction(
    province: str,
    target_date: str,
    target_draw: str,
    predicted_digit: int,
    confidence: float,
    method: str,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO predictions (province, created_at, target_date, target_draw,
                predicted_digit, confidence, method, hit)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                province,
                datetime.now().isoformat(timespec="seconds"),
                target_date,
                target_draw,
                predicted_digit,
                confidence,
                method,
            ),
        )
        return int(cur.lastrowid)


def resolve_predictions(province: str | None = None) -> int:
    updated = 0
    with get_conn() as conn:
        if province:
            pending = conn.execute(
                "SELECT * FROM predictions WHERE hit IS NULL AND province = ?",
                (province,),
            ).fetchall()
        else:
            pending = conn.execute(
                "SELECT * FROM predictions WHERE hit IS NULL"
            ).fetchall()
        for pred in pending:
            row = conn.execute(
                """
                SELECT last_digit FROM draws
                WHERE province = ? AND draw_date = ? AND draw_type = ? AND position = 1
                """,
                (pred["province"], pred["target_date"], pred["target_draw"]),
            ).fetchone()
            if not row:
                continue
            hit = 1 if row["last_digit"] == pred["predicted_digit"] else 0
            conn.execute(
                "UPDATE predictions SET hit = ? WHERE id = ?",
                (hit, pred["id"]),
            )
            updated += 1
    return updated


def get_betting_settings() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM betting_settings WHERE id = 1").fetchone()
    if not row:
        return None
    d = dict(row)
    d["auto_advance"] = bool(d["auto_advance"])
    return d


def upsert_betting_settings(data: dict[str, Any]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO betting_settings (
                id, initial_balance, default_stake, payout_multiplier,
                auto_advance, double_after_losses, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                initial_balance = excluded.initial_balance,
                default_stake = excluded.default_stake,
                payout_multiplier = excluded.payout_multiplier,
                auto_advance = excluded.auto_advance,
                double_after_losses = excluded.double_after_losses,
                updated_at = excluded.updated_at
            """,
            (
                data["initial_balance"],
                data["default_stake"],
                data["payout_multiplier"],
                1 if data.get("auto_advance", False) else 0,
                int(data.get("double_after_losses", 6)),
                now,
            ),
        )


def get_betting_slots() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM betting_slots ORDER BY province, draw_type"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        result.append(d)
    return result


def upsert_betting_slot(
    province: str,
    draw_type: str,
    active_digit: int,
    stake: float,
    enabled: bool,
    *,
    base_stake: float | None = None,
    loss_streak: int | None = None,
    reset_streak: bool = False,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    base = base_stake if base_stake is not None else stake
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT active_digit, loss_streak, base_stake FROM betting_slots WHERE province = ? AND draw_type = ?",
            (province, draw_type),
        ).fetchone()
        streak = 0 if reset_streak else (loss_streak if loss_streak is not None else (existing["loss_streak"] if existing else 0))
        if existing and int(existing["active_digit"]) != active_digit and not reset_streak:
            streak = 0
        if existing and base_stake is None:
            base = existing["base_stake"]
        conn.execute(
            """
            INSERT INTO betting_slots (
                province, draw_type, active_digit, stake, base_stake,
                loss_streak, enabled, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(province, draw_type) DO UPDATE SET
                active_digit = excluded.active_digit,
                stake = excluded.stake,
                base_stake = excluded.base_stake,
                loss_streak = excluded.loss_streak,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (province, draw_type, active_digit, stake, base, streak, 1 if enabled else 0, now),
        )


def disable_betting_slots_except(active_keys: set[str]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        rows = conn.execute("SELECT province, draw_type FROM betting_slots").fetchall()
        for row in rows:
            key = f"{row['province']}|{row['draw_type']}"
            if key not in active_keys:
                conn.execute(
                    "UPDATE betting_slots SET enabled = 0, updated_at = ? WHERE province = ? AND draw_type = ?",
                    (now, row["province"], row["draw_type"]),
                )


def clear_betting_entries(
    provinces: list[str] | None = None,
    draw_type: str | None = None,
    from_date: str | None = None,
) -> int:
    query = "DELETE FROM betting_entries WHERE 1=1"
    params: list[Any] = []
    if provinces:
        query += f" AND province IN ({','.join('?' * len(provinces))})"
        params.extend(provinces)
    if draw_type:
        query += " AND draw_type = ?"
        params.append(draw_type)
    if from_date:
        query += " AND draw_date >= ?"
        params.append(from_date)
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return cur.rowcount


def get_last_betting_entry_date(province: str, draw_type: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT draw_date FROM betting_entries
            WHERE province = ? AND draw_type = ?
            ORDER BY draw_date DESC LIMIT 1
            """,
            (province, draw_type),
        ).fetchone()
    return row["draw_date"] if row else None


def purge_betting_entries_before_session(
    session_start: str,
    provinces: list[str] | None = None,
) -> int:
    query = "DELETE FROM betting_entries WHERE draw_date < ?"
    params: list[Any] = [session_start]
    if provinces:
        query += f" AND province IN ({','.join('?' * len(provinces))})"
        params.extend(provinces)
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return cur.rowcount


def purge_betting_entries_excluded_draws(
    session_start: str,
    excluded_draw_types: list[str],
    provinces: list[str] | None = None,
) -> int:
    if not excluded_draw_types:
        return 0
    placeholders = ",".join("?" * len(excluded_draw_types))
    query = f"DELETE FROM betting_entries WHERE draw_date = ? AND draw_type IN ({placeholders})"
    params: list[Any] = [session_start, *excluded_draw_types]
    if provinces:
        query += f" AND province IN ({','.join('?' * len(provinces))})"
        params.extend(provinces)
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return cur.rowcount


def get_betting_entries_filtered(
    *,
    provinces: list[str] | None = None,
    draw_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    query = "SELECT * FROM betting_entries WHERE 1=1"
    params: list[Any] = []
    if provinces:
        query += f" AND province IN ({','.join('?' * len(provinces))})"
        params.extend(provinces)
    if draw_type:
        query += " AND draw_type = ?"
        params.append(draw_type)
    query += " ORDER BY draw_date DESC, draw_type DESC, province LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_betting_entries(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM betting_entries
            ORDER BY draw_date DESC, draw_type DESC, province
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_processed_draw_keys() -> set[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT province, draw_type, draw_date FROM betting_entries"
        ).fetchall()
    return {f"{r['province']}|{r['draw_type']}|{r['draw_date']}" for r in rows}


def insert_betting_entry(data: dict[str, Any]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO betting_entries (
                province, draw_type, draw_date, digit_played, stake,
                result_digit, hit, payout, new_digit, note, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["province"],
                data["draw_type"],
                data["draw_date"],
                data["digit_played"],
                data["stake"],
                data["result_digit"],
                data["hit"],
                data["payout"],
                data.get("new_digit"),
                data.get("note", ""),
                data["processed_at"],
            ),
        )
        return int(cur.lastrowid)
