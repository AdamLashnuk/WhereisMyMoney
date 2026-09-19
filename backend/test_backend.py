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
os.environ.pop("NVIDIA_API_KEY", None)
os.environ.pop("ELEVENLABS_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from categorizer import UnknownAmountError, parse_expense  # noqa: E402
from db import (  # noqa: E402
    configure_db,
    has_successful_call,
    init_db,
    insert_expense,
    log_call,
    sunday_week_start,
)
from main import app, over_limit_speech, weekly_summary_speech  # noqa: E402
from twilio_client import place_call  # noqa: E402
from whisper_client import (  # noqa: E402
    ELEVENLABS_STT_URL,
    STUB_VOICE_TEXT,
    transcribe_audio,
)

# load_dotenv in main.py may restore NVIDIA_API_KEY from a local .env
os.environ.pop("NVIDIA_API_KEY", None)


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
        assert body["nemotronConfigured"] is False

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
        assert payload["parse"]["engine"] == "heuristic"
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


def test_nemotron_import_without_key_does_not_crash() -> None:
    os.environ.pop("NVIDIA_API_KEY", None)
    import ai.nemotron as nemotron

    assert nemotron.ask_nemotron_json("sys", "user") is None


def test_heuristic_used_when_key_missing() -> None:
    os.environ.pop("NVIDIA_API_KEY", None)
    parsed = parse_expense("spent fourteen bucks on lunch")
    assert parsed.engine == "heuristic"
    assert parsed.amount_cents == 1400
    assert parsed.category == "Food"


def test_nemotron_parse_path(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    def fake_categorize(text: str) -> dict:
        return {
            "original_text": text,
            "merchant": "Cafe",
            "amount_cents": 1400,
            "category": "Food",
            "confidence": 0.94,
            "needs_review": False,
            "nemotron_failed": False,
        }

    monkeypatch.setattr("ai.categorize.categorize_expense", fake_categorize)
    parsed = parse_expense("weird phrasing at the cafe")
    assert parsed.engine == "nemotron"
    assert parsed.amount_cents == 1400
    assert parsed.merchant == "Cafe"
    assert parsed.category == "Food"
    assert parsed.original_text == "weird phrasing at the cafe"
    assert parsed.needs_review is False


def test_nemotron_failure_falls_back_to_heuristic(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    def fake_failed(_text: str) -> dict:
        return {
            "original_text": _text,
            "merchant": None,
            "amount_cents": None,
            "category": "Other",
            "confidence": 0.0,
            "needs_review": True,
            "nemotron_failed": True,
        }

    monkeypatch.setattr("ai.categorize.categorize_expense", fake_failed)
    parsed = parse_expense("spent fourteen bucks on lunch")
    assert parsed.engine == "heuristic"
    assert parsed.amount_cents == 1400
    assert parsed.category == "Food"


def test_nemotron_null_amount_does_not_invent_cents(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    def fake_unknown(text: str) -> dict:
        return {
            "original_text": text,
            "merchant": None,
            "amount_cents": None,
            "category": "Bills",
            "confidence": 0.4,
            "needs_review": True,
            "nemotron_failed": False,
        }

    monkeypatch.setattr("ai.categorize.categorize_expense", fake_unknown)
    try:
        parse_expense("paid rent")
        raise AssertionError("expected UnknownAmountError")
    except UnknownAmountError as exc:
        assert "amount" in str(exc).lower()

    _fresh_db()
    with TestClient(app) as client:
        response = client.post(
            "/log-expense",
            data={"source": "voice", "text": "paid rent"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["ok"] is False
        assert "amount" in str(body.get("error") or "").lower()


def test_log_expense_uses_nemotron_cents(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    def fake_categorize(text: str) -> dict:
        return {
            "original_text": text,
            "merchant": None,
            "amount_cents": 2599,
            "category": "Transport",
            "confidence": 0.88,
            "needs_review": False,
            "nemotron_failed": False,
        }

    monkeypatch.setattr("ai.categorize.categorize_expense", fake_categorize)
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/log-expense",
            data={"source": "voice", "text": "uber downtown"},
        )
        assert posted.status_code == 200
        payload = posted.json()
        assert payload["parse"]["engine"] == "nemotron"
        assert payload["expense"]["amountCents"] == 2599
        assert payload["expense"]["category"] == "Transport"
        assert payload["expense"]["originalText"] == "uber downtown"


def test_over_limit_speech_uses_nemotron_and_falls_back(monkeypatch) -> None:
    os.environ.pop("NVIDIA_API_KEY", None)
    template = over_limit_speech("Food", 1400, 1000, 400)
    assert "Food" in template
    assert "over by" in template.lower()

    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr(
        "ai.overlimit_alert.overlimit_alert_sentence",
        lambda category, limit_cents, over_by_cents: f"Nemotron alert {category} {over_by_cents}",
    )
    spoken = over_limit_speech("Food", 1400, 1000, 400)
    assert spoken == "Nemotron alert Food 400"

    monkeypatch.setattr(
        "ai.overlimit_alert.overlimit_alert_sentence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    spoken = over_limit_speech("Food", 1400, 1000, 400)
    assert spoken == template


def test_weekly_summary_appends_nemotron_pattern(monkeypatch) -> None:
    totals = {"Food": 1400, "Transport": 0, "Subscriptions": 0, "Shopping": 0, "Bills": 0, "Other": 0}
    os.environ.pop("NVIDIA_API_KEY", None)
    base = weekly_summary_speech(totals, 1400)
    assert "Food" in base

    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr(
        "ai.weekly_pattern.weekly_pattern_sentence",
        lambda this_week, last_week: "Food spending jumped compared to last week.",
    )
    spoken = weekly_summary_speech(totals, 1400, last_week_totals={**totals, "Food": 100})
    assert spoken.startswith(base)
    assert "jumped" in spoken


def test_elevenlabs_transcription_uses_mocked_http(monkeypatch, tmp_path) -> None:
    import httpx

    monkeypatch.setenv("WHISPER_STUB", "0")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")
    monkeypatch.setenv("ELEVENLABS_STT_MODEL", "scribe_v2")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"ID3fake-audio-bytes")

    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["data"] = kwargs.get("data")
        captured["files"] = kwargs.get("files")
        return httpx.Response(200, json={"text": "spent fourteen bucks on lunch"})

    monkeypatch.setattr("httpx.post", fake_post)
    text, engine = transcribe_audio(audio, source="voice")
    assert engine == "elevenlabs"
    assert text == "spent fourteen bucks on lunch"
    assert captured["url"] == ELEVENLABS_STT_URL
    assert captured["headers"] == {"xi-api-key": "test-elevenlabs-key"}
    assert captured["data"] == {"model_id": "scribe_v2", "language_code": "eng"}
    files = captured["files"]
    assert isinstance(files, dict)
    assert files["file"][0] == "sample.mp3"


def test_elevenlabs_missing_key_falls_back_to_stub(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WHISPER_STUB", "0")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"ID3fake-audio-bytes")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("ElevenLabs HTTP should not run without a key")

    monkeypatch.setattr("httpx.post", fail_if_called)
    text, engine = transcribe_audio(audio, source="voice")
    assert engine == "stub"
    assert text == STUB_VOICE_TEXT


def test_elevenlabs_http_error_falls_back_to_stub(monkeypatch, tmp_path) -> None:
    import httpx

    monkeypatch.setenv("WHISPER_STUB", "0")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"ID3fake-audio-bytes")

    def fake_post(url, **kwargs):
        return httpx.Response(401, json={"detail": "invalid api key"})

    monkeypatch.setattr("httpx.post", fake_post)
    text, engine = transcribe_audio(audio, source="voice")
    assert engine == "stub"
    assert text == STUB_VOICE_TEXT
