"""SQLite persistence for Where Is My Money.

Money is always stored as integer cents. The only user is ``demo``.
The database file defaults to ``whereismymoney.db`` next to this module
and is gitignored via the root ``*.db`` rule.

Tables: expenses, limits, settings, call_log.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CATEGORIES = ("Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other")
USER_ID = "demo"

DEFAULT_LIMIT_CENTS = 5000  # $50.00 per category, so the app is usable out of the box
DEFAULT_CALL_DAY = 0  # Sunday (JS Date.getDay convention)
DEFAULT_CALL_HOUR = 18

CallKind = Literal["over_limit", "weekly_summary"]

_DB_PATH = Path(os.environ.get("WHEREISMYMONEY_DB") or Path(__file__).resolve().parent / "whereismymoney.db")
_lock = threading.RLock()


def db_path() -> Path:
    return _DB_PATH


def configure_db(path: Path | str) -> None:
    """Point at a different SQLite file (used by tests)."""
    global _DB_PATH
    _DB_PATH = Path(path)


def get_tz():
    name = os.getenv("TZ", "America/New_York")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, Exception):
        return datetime.now().astimezone().tzinfo or timezone.utc


def local_now() -> datetime:
    return datetime.now(get_tz())


def sunday_week_start(when: datetime | None = None) -> date:
    """Return the Sunday (callDay=0) that starts the week containing ``when``."""
    now = when or local_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=get_tz())
    else:
        now = now.astimezone(get_tz())
    js_weekday = (now.weekday() + 1) % 7  # Sunday = 0
    return (now - timedelta(days=js_weekday)).date()


def week_end(start: date) -> date:
    return start + timedelta(days=6)


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def in_week(created_at: str, start: date) -> bool:
    dt = parse_iso(created_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(get_tz()).date()
    return start <= local <= week_end(start)


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    """Create tables and seed the demo user if needed."""
    default_phone = (os.getenv("MY_PHONE_NUMBER") or "").strip()
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                original_text TEXT NOT NULL,
                source TEXT NOT NULL,
                merchant TEXT,
                amount_cents INTEGER NOT NULL,
                category TEXT NOT NULL,
                confidence REAL NOT NULL,
                needs_review INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS limits (
                user_id TEXT NOT NULL,
                category TEXT NOT NULL,
                limit_cents INTEGER NOT NULL,
                PRIMARY KEY (user_id, category)
            );

            CREATE TABLE IF NOT EXISTS settings (
                user_id TEXT PRIMARY KEY,
                call_day INTEGER NOT NULL,
                call_hour INTEGER NOT NULL,
                phone_number TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS call_log (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                category TEXT,
                week_start TEXT NOT NULL,
                ok INTEGER NOT NULL,
                message TEXT,
                sid TEXT,
                called_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_expenses_user_created
                ON expenses (user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_call_log_week
                ON call_log (user_id, kind, week_start, category);
            """
        )
        for category in CATEGORIES:
            conn.execute(
                """
                INSERT OR IGNORE INTO limits (user_id, category, limit_cents)
                VALUES (?, ?, ?)
                """,
                (USER_ID, category, DEFAULT_LIMIT_CENTS),
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO settings (user_id, call_day, call_hour, phone_number)
            VALUES (?, ?, ?, ?)
            """,
            (USER_ID, DEFAULT_CALL_DAY, DEFAULT_CALL_HOUR, default_phone),
        )


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def expense_to_api(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "userId": data["user_id"],
        "originalText": data["original_text"],
        "source": data["source"],
        "merchant": data["merchant"],
        "amountCents": int(data["amount_cents"]),
        "category": data["category"],
        "confidence": float(data["confidence"]),
        "needsReview": bool(data["needs_review"]),
        "createdAt": data["created_at"],
    }


def insert_expense(
    *,
    original_text: str,
    source: str,
    merchant: str | None,
    amount_cents: int,
    category: str,
    confidence: float,
    needs_review: bool,
    user_id: str = USER_ID,
    created_at: str | None = None,
) -> dict[str, Any]:
    expense_id = _new_id("exp")
    created = created_at or datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO expenses (
                id, user_id, original_text, source, merchant,
                amount_cents, category, confidence, needs_review, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                expense_id,
                user_id,
                original_text,
                source,
                merchant,
                int(amount_cents),
                category,
                float(confidence),
                1 if needs_review else 0,
                created,
            ),
        )
    return {
        "id": expense_id,
        "userId": user_id,
        "originalText": original_text,
        "source": source,
        "merchant": merchant,
        "amountCents": int(amount_cents),
        "category": category,
        "confidence": float(confidence),
        "needsReview": bool(needs_review),
        "createdAt": created,
    }


def list_expenses(user_id: str = USER_ID, week_start: date | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    expenses = [expense_to_api(r) for r in rows]
    if week_start is not None:
        expenses = [e for e in expenses if in_week(e["createdAt"], week_start)]
    return expenses


def week_totals(user_id: str = USER_ID, week_start: date | None = None) -> dict[str, int]:
    start = week_start or sunday_week_start()
    totals = {c: 0 for c in CATEGORIES}
    for expense in list_expenses(user_id, start):
        cat = expense["category"]
        if cat in totals:
            totals[cat] += int(expense["amountCents"])
    return totals


def week_total_for_category(category: str, user_id: str = USER_ID, week_start: date | None = None) -> int:
    return week_totals(user_id, week_start).get(category, 0)


def get_limits(user_id: str = USER_ID) -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, limit_cents FROM limits WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    limits = {c: DEFAULT_LIMIT_CENTS for c in CATEGORIES}
    for row in rows:
        limits[row["category"]] = int(row["limit_cents"])
    return limits


def set_limit(category: str, limit_cents: int, user_id: str = USER_ID) -> dict[str, int]:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO limits (user_id, category, limit_cents)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, category) DO UPDATE SET limit_cents = excluded.limit_cents
            """,
            (user_id, category, int(limit_cents)),
        )
    return get_limits(user_id)


def get_settings(user_id: str = USER_ID) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT call_day, call_hour, phone_number FROM settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return {
            "callDay": DEFAULT_CALL_DAY,
            "callHour": DEFAULT_CALL_HOUR,
            "phoneNumber": (os.getenv("MY_PHONE_NUMBER") or "").strip(),
        }
    return {
        "callDay": int(row["call_day"]),
        "callHour": int(row["call_hour"]),
        "phoneNumber": row["phone_number"] or "",
    }


def set_settings(
    call_day: int,
    call_hour: int,
    phone_number: str,
    user_id: str = USER_ID,
) -> dict[str, Any]:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO settings (user_id, call_day, call_hour, phone_number)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                call_day = excluded.call_day,
                call_hour = excluded.call_hour,
                phone_number = excluded.phone_number
            """,
            (user_id, int(call_day), int(call_hour), phone_number),
        )
    return get_settings(user_id)


def log_call(
    *,
    kind: CallKind,
    category: str | None,
    week_start: date,
    ok: bool,
    message: str,
    sid: str | None = None,
    user_id: str = USER_ID,
    called_at: str | None = None,
) -> dict[str, Any]:
    call_id = _new_id("call")
    when = called_at or datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO call_log (
                id, user_id, kind, category, week_start, ok, message, sid, called_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call_id,
                user_id,
                kind,
                category,
                week_start.isoformat(),
                1 if ok else 0,
                message,
                sid,
                when,
            ),
        )
    return {
        "id": call_id,
        "userId": user_id,
        "kind": kind,
        "category": category,
        "weekStart": week_start.isoformat(),
        "ok": ok,
        "message": message,
        "sid": sid,
        "calledAt": when,
    }


def has_successful_call(
    kind: CallKind,
    category: str | None,
    week_start: date,
    user_id: str = USER_ID,
) -> bool:
    with get_conn() as conn:
        if category is None:
            row = conn.execute(
                """
                SELECT 1 FROM call_log
                WHERE user_id = ? AND kind = ? AND week_start = ?
                  AND category IS NULL AND ok = 1
                LIMIT 1
                """,
                (user_id, kind, week_start.isoformat()),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT 1 FROM call_log
                WHERE user_id = ? AND kind = ? AND week_start = ?
                  AND category = ? AND ok = 1
                LIMIT 1
                """,
                (user_id, kind, week_start.isoformat(), category),
            ).fetchone()
    return row is not None
