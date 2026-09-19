"""Logic + API tests. Run from backend/: python3 -m pytest test_backend.py -q"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp()) / "test.db"
os.environ["WHEREISMYMONEY_DB"] = str(_TMP)
os.environ["WHISPER_STUB"] = "1"
os.environ.pop("TWILIO_ACCOUNT_SID", None)
os.environ.pop("TWILIO_AUTH_TOKEN", None)
os.environ.pop("TWILIO_PHONE_NUMBER", None)
os.environ.pop("MY_PHONE_NUMBER", None)

from fastapi.testclient import TestClient  # noqa: E402

from categorizer import parse_expense  # noqa: E402
from db import (  # noqa: E402
    configure_db,
    has_successful_call,
    init_db,
    insert_expense,
    log_call,
    sunday_week_start,
)
from main import app  # noqa: E402
from twilio_client import place_call  # noqa: E402


def _fresh_db() -> None:
    configure_db(_TMP)
    if _TMP.exists():
        _TMP.unlink()
    wal = Path(str(_TMP) + "-wal")
    shm = Path(str(_TMP) + "-shm")
    if wal.exists():
        wal.unlink()
    if shm.exists():
        shm.unlink()
    init_db()


def test_parse_demo_phrases() -> None:
    lunch = parse_expense("spent fourteen bucks on lunch")
    assert lunch.amount_cents == 1400
    assert lunch.category == "Food"
    assert lunch.original_text == "spent fourteen bucks on lunch"

    bus = parse_expense("two fifty for the bus")
    assert bus.amount_cents == 250
    assert bus.category == "Transport"

    groceries = parse_expense("thirty two forty five on groceries")
    assert groceries.amount_cents == 3245
    assert groceries.category == "Food"

    receipt = parse_expense("RECEIPT TOTAL 14.00 LUNCH")
    assert receipt.amount_cents == 1400
    assert receipt.category == "Food"


def test_twilio_missing_keys_does_not_raise() -> None:
    result = place_call("+15555550100", "hello")
    assert result["ok"] is False
    assert "Twilio" in result["error"]


def test_health_and_defaults() -> None:
    _fresh_db()
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "ok"
        assert body["mode"] == "live"
        assert body["twilioConfigured"] is False
        assert body["whisperStub"] is True

        settings = client.get("/settings").json()["settings"]
        assert settings["callDay"] == 0
        assert settings["callHour"] == 18

        limits = client.get("/limits").json()["limits"]
        assert set(limits) == {"Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other"}
        assert all(v == 5000 for v in limits.values())


def test_log_expense_and_once_per_week_call() -> None:
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post("/limits", json={"category": "Food", "limitCents": 1000})
        assert posted.status_code == 200
        first = client.post(
            "/log-expense",
            data={"source": "voice", "text": "spent fourteen bucks on lunch"},
        )
        assert first.status_code == 200
        payload = first.json()
        assert payload["expense"]["amountCents"] == 1400
        assert payload["expense"]["category"] == "Food"
        assert payload["expense"]["originalText"] == "spent fourteen bucks on lunch"
        check = payload["limitCheck"]
        assert check["weekTotalCents"] == 1400
        assert check["limitCents"] == 1000
        assert check["overByCents"] == 400
        assert check["action"] == "call_failed"  # keys missing → ok:false, no crash

        log_call(
            kind="over_limit",
            category="Food",
            week_start=sunday_week_start(),
            ok=True,
            message="already",
        )
        assert has_successful_call("over_limit", "Food", sunday_week_start())
        again = client.post(
            "/log-expense",
            data={"source": "voice", "text": "spent fourteen bucks on lunch"},
        ).json()
        assert again["limitCheck"]["overByCents"] > 0
        assert again["limitCheck"]["action"] == "already_called"

        history = client.get("/expenses").json()
        assert history["weekTotalCents"] >= 2800
        assert history["totalsByCategory"]["Food"] >= 2800


def test_settings_and_trigger_call() -> None:
    _fresh_db()
    with TestClient(app) as client:
        saved = client.post(
            "/settings",
            json={"callDay": 3, "callHour": 9, "phoneNumber": "+15555550123"},
        )
        assert saved.status_code == 200
        assert saved.json()["settings"]["callDay"] == 3
        assert saved.json()["settings"]["callHour"] == 9

        weekly = client.post("/trigger-call", json={"kind": "weekly_summary"})
        assert weekly.status_code == 200
        body = weekly.json()
        assert body["kind"] == "weekly_summary"
        assert body["ok"] is False

        missing = client.post("/trigger-call", json={"kind": "over_limit"})
        assert missing.status_code == 400
        err = missing.json()
        assert "category" in str(err.get("error") or err.get("detail") or err)

        over = client.post("/trigger-call", json={"kind": "over_limit", "category": "Food"})
        assert over.status_code == 200
        assert over.json()["ok"] is False


def test_insert_helper_keeps_original_text() -> None:
    _fresh_db()
    row = insert_expense(
        original_text="keep this forever",
        source="voice",
        merchant="Cafe",
        amount_cents=99,
        category="Other",
        confidence=0.4,
        needs_review=True,
    )
    assert row["originalText"] == "keep this forever"
    assert row["amountCents"] == 99
