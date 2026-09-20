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
os.environ.pop("PUBLIC_BASE_URL", None)
os.environ.pop("CALL_AUDIO_BASE_URL", None)
os.environ.pop("CALL_AUDIO_DIR", None)

from fastapi.testclient import TestClient  # noqa: E402

from categorizer import UnknownAmountError, parse_expense, parse_receipt_image  # noqa: E402
from db import (  # noqa: E402
    CATEGORIES,
    configure_db,
    has_successful_call,
    init_db,
    insert_expense,
    log_call,
    sunday_week_start,
)
from main import app, over_limit_speech, weekly_summary_speech  # noqa: E402
from call_intents import (  # noqa: E402
    classify_spoken_reply,
    heuristic_spoken_limit,
    looks_like_ack,
    looks_like_limit,
)
from twilio_client import (  # noqa: E402
    call_audio_dir,
    call_audio_path,
    place_call,
    render_play_twiml,
    twimlets_say_url,
)
from whisper_client import (  # noqa: E402
    ELEVENLABS_STT_URL,
    STUB_VOICE_TEXT,
    transcribe_audio,
)

# load_dotenv in main.py may restore keys from a local .env
os.environ.pop("NVIDIA_API_KEY", None)
os.environ.pop("PUBLIC_BASE_URL", None)
os.environ.pop("CALL_AUDIO_BASE_URL", None)
os.environ.pop("ELEVENLABS_API_KEY", None)


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
        assert body["receiptOcrEnabled"] is False
        assert body["capabilities"]["receiptOCR"] is False
        assert body["capabilities"]["nemotron"] is False
        assert body["capabilities"]["voiceStt"] is False

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


def test_trigger_call_phone_number_override(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_place(to, spoken):
        captured["to"] = to
        captured["spoken"] = spoken
        return {"ok": False, "error": "Twilio is not configured", "to": to}

    monkeypatch.setattr("main.place_call", fake_place)
    _fresh_db()
    with TestClient(app) as client:
        saved = client.post(
            "/settings",
            json={"callDay": 0, "callHour": 18, "phoneNumber": "+15555550111"},
        )
        assert saved.status_code == 200

        weekly = client.post(
            "/trigger-call",
            json={"kind": "weekly_summary", "phoneNumber": "+15555550999"},
        )
        assert weekly.status_code == 200
        assert captured["to"] == "+15555550999"
        assert weekly.json()["to"] == "+15555550999"

        default = client.post("/trigger-call", json={"kind": "weekly_summary"})
        assert default.status_code == 200
        assert captured["to"] == "+15555550111"
        assert default.json()["to"] == "+15555550111"

        over = client.post(
            "/trigger-call",
            json={"kind": "over_limit", "category": "Food", "phoneNumber": "+15555550888"},
        )
        assert over.status_code == 200
        assert captured["to"] == "+15555550888"
        assert over.json()["to"] == "+15555550888"

        bad = client.post("/trigger-call", json={"kind": "weekly_summary", "phoneNumber": "12"})
        assert bad.status_code == 400
        err = bad.json()
        assert "phone" in str(err.get("error") or "").lower()


def test_health_advertises_receipt_ocr_when_nvidia_key(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("WHISPER_STUB", "0")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")
    _fresh_db()
    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["nemotronConfigured"] is True
        assert body["receiptOcrEnabled"] is True
        assert body["capabilities"]["receiptOCR"] is True
        assert body["capabilities"]["nemotron"] is True
        assert body["capabilities"]["voiceStt"] is True
        assert body["whisperStub"] is False


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


def test_over_limit_speech_uses_spoken_usd_not_symbols_or_raw_cents() -> None:
    os.environ.pop("NVIDIA_API_KEY", None)
    spoken = over_limit_speech("Food", 18550, 5000, 13550)
    assert spoken == (
        "This is Where Is My Money. You went over your Food limit. "
        "You are over by one hundred thirty-five dollars and fifty cents."
    )
    assert "$" not in spoken
    assert "CHF" not in spoken
    assert "franc" not in spoken.lower()
    assert "13550" not in spoken
    assert "185.50" not in spoken


def test_weekly_summary_speech_uses_spoken_usd_for_large_total() -> None:
    os.environ.pop("NVIDIA_API_KEY", None)
    totals = {
        "Food": 18550,
        "Transport": 0,
        "Subscriptions": 0,
        "Shopping": 0,
        "Bills": 0,
        "Other": 0,
    }
    spoken = weekly_summary_speech(totals, 18550)
    assert "one hundred eighty-five dollars and fifty cents" in spoken
    assert "You spent one hundred eighty-five dollars and fifty cents this week." in spoken
    assert "$" not in spoken
    assert "CHF" not in spoken
    assert "18550" not in spoken


def test_over_limit_speech_rewrites_nemotron_currency_fragments(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr(
        "ai.overlimit_alert.overlimit_alert_sentence",
        lambda *_args, **_kwargs: "Alert: you are $185.50 over, same as CHF 185.50.",
    )
    spoken = over_limit_speech("Food", 23550, 5000, 18550)
    assert "one hundred eighty-five dollars and fifty cents" in spoken
    assert "$" not in spoken
    assert "CHF" not in spoken
    assert "185.50" not in spoken


def test_over_limit_speech_uses_nemotron_and_falls_back(monkeypatch) -> None:
    os.environ.pop("NVIDIA_API_KEY", None)
    template = over_limit_speech("Food", 1400, 1000, 400)
    assert "Food" in template
    assert "over by" in template.lower()
    assert "four dollars" in template
    assert "4 dollars" not in template
    assert len(template.split()) <= 40

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
    assert len(base.split()) <= 40
    long_totals = {category: 1000 for category in CATEGORIES}
    long_base = weekly_summary_speech(long_totals, 6000)
    assert len(long_base.split()) <= 40
    assert long_base.count("dollars") <= 2

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
        captured["timeout"] = kwargs.get("timeout")
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"text": "spent fourteen bucks on lunch"},
        )

    monkeypatch.setattr("httpx.post", fake_post)
    text, engine = transcribe_audio(audio, source="voice")
    assert engine == "elevenlabs"
    assert text == "spent fourteen bucks on lunch"
    assert captured["url"] == ELEVENLABS_STT_URL
    assert captured["headers"] == {"xi-api-key": "test-elevenlabs-key"}
    assert captured["data"] == {"model_id": "scribe_v2", "language_code": "eng"}
    assert captured["timeout"] == 20.0
    files = captured["files"]
    assert isinstance(files, dict)
    assert files["file"][0] == "sample.mp3"
    assert files["file"][2] == "audio/mpeg"


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
        return httpx.Response(
            401,
            request=httpx.Request("POST", url),
            json={"detail": "invalid api key"},
        )

    monkeypatch.setattr("httpx.post", fake_post)
    text, engine = transcribe_audio(audio, source="voice")
    assert engine == "stub"
    assert text == STUB_VOICE_TEXT


def test_elevenlabs_error_does_not_cascade_to_openai(monkeypatch, tmp_path) -> None:
    import httpx

    monkeypatch.setenv("WHISPER_STUB", "0")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"ID3fake-audio-bytes")

    def fake_post(url, **kwargs):
        return httpx.Response(
            503,
            request=httpx.Request("POST", url),
            json={"detail": "busy"},
        )

    def fail_openai(*_args, **_kwargs):
        raise AssertionError("OpenAI Whisper must not run when ElevenLabs is configured")

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("whisper_client._try_openai", fail_openai)
    text, engine = transcribe_audio(audio, source="voice")
    assert engine == "stub"
    assert text == STUB_VOICE_TEXT


def _twilio_env(monkeypatch, tmp_path, **extra: str | None) -> None:
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtestaccountsid")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15551111111")
    monkeypatch.setenv("CALL_AUDIO_DIR", str(tmp_path / "call_audio"))
    for key, value in extra.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def _install_fake_twilio(monkeypatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    class FakeCall:
        sid = "CAffffffffffffffffffffffffffffffff"

    class FakeCalls:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeCall()

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            self.calls = FakeCalls()

    monkeypatch.setattr("twilio.rest.Client", FakeClient)
    return captured


def test_elevenlabs_tts_posts_victoria_voice(monkeypatch, tmp_path) -> None:
    import requests

    import ai.elevenlabs_tts as tts

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")
    out = tmp_path / "victoria.ulaw"
    captured: dict[str, object] = {}

    class FakeResponse:
        content = b"\x00\x01ulaw"

        def raise_for_status(self) -> None:
            return None

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        captured["params"] = kwargs.get("params")
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    assert tts.text_to_speech("You went over your Food limit.", str(out)) is True
    assert out.read_bytes() == b"\x00\x01ulaw"
    assert captured["url"] == "https://api.elevenlabs.io/v1/text-to-speech/XoUkt2bf6DlvSzRmvA8X"
    assert captured["params"] == {"output_format": "ulaw_8000"}
    assert captured["headers"] == {
        "xi-api-key": "test-elevenlabs-key",
        "Content-Type": "application/json",
    }
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["text"] == "You went over your Food limit."
    assert payload["model_id"] == "eleven_multilingual_v2"
    assert payload["voice_settings"]["stability"] == 0.65
    assert tts.VOICE_ID == "XoUkt2bf6DlvSzRmvA8X"
    assert tts.AUDIO_EXTENSION == ".ulaw"
    assert tts.AUDIO_MEDIA_TYPE == "audio/x-mulaw"

    assert tts.text_to_speech("Over by $185.50 after CHF 54.50", str(out)) is True
    spoken_payload = captured["json"]["text"]
    assert "one hundred eighty-five dollars and fifty cents" in spoken_payload
    assert "fifty-four dollars and fifty cents" in spoken_payload
    assert "$" not in spoken_payload
    assert "CHF" not in spoken_payload

    result = tts.get_call_audio("again", str(tmp_path / "again.ulaw"))
    assert result["success"] is True


def test_elevenlabs_tts_import_without_key_does_not_crash(monkeypatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    import ai.elevenlabs_tts as tts

    assert tts.elevenlabs_api_key() is None
    assert tts.text_to_speech("hello", "/tmp/unused.mp3") is False
    result = tts.get_call_audio("hello", "/tmp/unused.mp3")
    assert result == {"success": False, "fallback_text": "hello"}


def test_place_call_plays_elevenlabs_audio_via_twiml_url(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")
    captured = _install_fake_twilio(monkeypatch)

    def fake_success(sentence, output_path):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x01ulaw")
        return {"success": True, "audio_path": output_path}

    monkeypatch.setattr("twilio_client.get_call_audio", fake_success)
    result = place_call("+15555550100", "You went over your Food limit.")
    assert result["ok"] is True
    assert result["voice"] == "elevenlabs"
    url = str(captured["url"])
    assert url.startswith("https://demo.ngrok-free.app/twiml/play/")
    assert "twimlets.com" not in url
    token = url.rsplit("/", 1)[-1]
    audio = call_audio_path(token)
    assert audio is not None and audio.is_file()
    assert audio.suffix == ".ulaw"
    assert audio.read_bytes() == b"\x00\x01ulaw"

    with TestClient(app) as client:
        twiml = client.get(f"/twiml/play/{token}")
        assert twiml.status_code == 200
        body = twiml.text
        assert "<Play>" in body
        assert f"https://demo.ngrok-free.app/call-audio/{token}.ulaw" in body
        assert ".mp3" not in body
        assert body.index("<Play>") < body.index("<Gather")
        assert 'input="speech dtmf"' in body
        assert 'timeout="8"' in body
        assert "actionOnEmptyResult" in body
        assert "https://demo.ngrok-free.app/twiml/gather" in body
        assert "You can reply now" in body
        assert "<Redirect>" in body
        assert "<Hangup" not in body

        posted = client.post(f"/twiml/play/{token}")
        assert posted.status_code == 200
        assert f"/call-audio/{token}.ulaw" in posted.text
        assert "<Gather" in posted.text

        ulaw = client.get(f"/call-audio/{token}.ulaw")
        assert ulaw.status_code == 200
        assert ulaw.content == b"\x00\x01ulaw"
        content_type = ulaw.headers.get("content-type") or ""
        assert "audio/x-mulaw" in content_type

        assert client.get(f"/call-audio/{token}.mp3").status_code == 404


def test_place_call_falls_back_to_twimlets_when_elevenlabs_fails(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")
    captured = _install_fake_twilio(monkeypatch)

    def fake_failure(sentence, output_path):
        return {"success": False, "fallback_text": sentence}

    monkeypatch.setattr("twilio_client.get_call_audio", fake_failure)
    result = place_call("+15555550100", "Weekly summary: you spent fourteen dollars.")
    assert result["ok"] is True
    assert result["voice"] == "twimlets"
    url = str(captured["url"])
    assert url.startswith("https://twimlets.com/message?")
    assert "fourteen" in url


def test_twimlets_and_place_call_rewrite_chf_and_dollar_symbols(monkeypatch, tmp_path) -> None:
    url = twimlets_say_url("Berghotel Grosse Scheidegg · CHF 54.50")
    assert "fifty-four" in url
    assert "dollars" in url
    assert "CHF" not in url
    assert "%24" not in url  # encoded $

    _twilio_env(monkeypatch, tmp_path)
    captured = _install_fake_twilio(monkeypatch)

    def fake_failure(sentence, output_path):
        return {"success": False, "fallback_text": sentence}

    monkeypatch.setattr("twilio_client.get_call_audio", fake_failure)
    result = place_call("+15555550100", "You are over by $185.50")
    assert result["ok"] is True
    assert "one%20hundred%20eighty-five" in str(captured["url"])
    assert "CHF" not in str(captured["url"])
    assert "$" not in str(captured["url"])


def test_place_call_falls_back_to_twimlets_without_public_base_url(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("CALL_AUDIO_BASE_URL", raising=False)
    captured = _install_fake_twilio(monkeypatch)

    def fake_success(sentence, output_path):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x01ulaw")
        return {"success": True, "audio_path": output_path}

    monkeypatch.setattr("twilio_client.get_call_audio", fake_success)
    result = place_call("+15555550100", "You went over your Food limit.")
    assert result["ok"] is True
    assert result["voice"] == "twimlets"
    url = str(captured["url"])
    assert url.startswith("https://twimlets.com/message?")
    assert "Food" in url
    assert "twiml/play" not in url


def test_call_audio_unknown_token_is_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CALL_AUDIO_DIR", str(tmp_path / "empty_audio"))
    call_audio_dir()
    with TestClient(app) as client:
        missing = "0" * 32
        assert client.get(f"/call-audio/{missing}.ulaw").status_code == 404
        assert client.get(f"/call-audio/{missing}.mp3").status_code == 404
        assert client.get(f"/twiml/play/{missing}").status_code == 404
        assert client.get("/twiml/play/../secret").status_code == 404


_FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"fake-receipt-bytes"


def test_receipt_import_without_key_does_not_crash(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    import ai.receipt as receipt

    missing = tmp_path / "nope.jpg"
    result = receipt.categorize_receipt(str(missing))
    assert result["amount_cents"] is None
    assert result["needs_review"] is True
    assert result["category"] == "Other"
    assert result["nemotron_failed"] is True


def test_spoken_limit_import_without_key_is_null_safe(monkeypatch) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    from ai.spoken_limit import understand_spoken_limit

    result = understand_spoken_limit("cap my food spending at a hundred a week")
    assert result["category"] is None
    assert result["amount_cents"] is None
    assert result["period"] == "weekly"
    assert result["confidence"] == 0.0


def test_parse_receipt_image_maps_vision_dict(monkeypatch, tmp_path) -> None:
    image = tmp_path / "chipotle.jpg"
    image.write_bytes(_FAKE_JPEG)

    def fake_receipt(image_path: str) -> dict:
        assert Path(image_path).is_file()
        return {
            "original_text": "[receipt photo: chipotle.jpg]",
            "merchant": "Chipotle",
            "amount_cents": 1450,
            "category": "Food",
            "confidence": 0.91,
            "needs_review": False,
            "nemotron_failed": False,
        }

    monkeypatch.setattr("ai.receipt.categorize_receipt", fake_receipt)
    parsed = parse_receipt_image(str(image), original_text="[receipt photo: chipotle.jpg]")
    assert parsed.engine == "nemotron-vision"
    assert parsed.amount_cents == 1450
    assert parsed.merchant == "Chipotle"
    assert parsed.category == "Food"
    assert parsed.needs_review is False


def test_log_expense_receipt_image_uses_vision(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    def fake_receipt(image_path: str) -> dict:
        assert Path(image_path).is_file()
        return {
            "original_text": "[receipt photo: lunch.jpg]",
            "merchant": "Chipotle",
            "amount_cents": 1450,
            "category": "Food",
            "confidence": 0.91,
            "needs_review": False,
            "nemotron_failed": False,
        }

    monkeypatch.setattr("ai.receipt.categorize_receipt", fake_receipt)
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/log-expense",
            data={"source": "receipt"},
            files={"file": ("lunch.jpg", _FAKE_JPEG, "image/jpeg")},
        )
        assert posted.status_code == 200
        payload = posted.json()
        assert payload["parse"]["engine"] == "nemotron-vision"
        assert payload["parse"]["textEngine"] == "receipt"
        assert payload["expense"]["amountCents"] == 1450
        assert payload["expense"]["category"] == "Food"
        assert payload["expense"]["merchant"] == "Chipotle"
        assert payload["expense"]["originalText"] == "[receipt photo: lunch.jpg]"
        assert payload["expense"]["source"] == "receipt"


def test_log_expense_berghotel_receipt_is_5450_food(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    fixture = Path(__file__).resolve().parent.parent / "ai" / "tests" / "fixtures" / "berghotel_grosse_scheidegg.png"
    image_bytes = fixture.read_bytes()

    def fake_receipt(image_path: str) -> dict:
        assert Path(image_path).is_file()
        return {
            "original_text": "Berghotel Grosse Scheidegg · CHF 54.50",
            "merchant": "Berghotel Grosse Scheidegg",
            "amount_cents": 5450,
            "category": "Food",
            "confidence": 0.93,
            "needs_review": False,
            "nemotron_failed": False,
        }

    monkeypatch.setattr("ai.receipt.categorize_receipt", fake_receipt)
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/log-expense",
            data={"source": "receipt"},
            files={"file": ("berghotel.png", image_bytes, "image/png")},
        )
        assert posted.status_code == 200
        payload = posted.json()
        assert payload["expense"]["amountCents"] == 5450
        assert payload["expense"]["category"] == "Food"
        assert "Scheidegg" in payload["expense"]["merchant"]
        assert payload["expense"]["originalText"] == "Berghotel Grosse Scheidegg · CHF 54.50"


def test_parse_receipt_image_coerces_chf_string_to_5450(monkeypatch, tmp_path) -> None:
    image = tmp_path / "berghotel.jpg"
    image.write_bytes(_FAKE_JPEG)

    def fake_receipt(_image_path: str) -> dict:
        return {
            "original_text": "Berghotel Grosse Scheidegg · CHF 54.50",
            "merchant": "Berghotel Grosse Scheidegg",
            "amount_cents": "CHF 54.50",
            "category": "Food",
            "confidence": 0.9,
            "needs_review": False,
            "nemotron_failed": False,
        }

    monkeypatch.setattr("ai.receipt.categorize_receipt", fake_receipt)
    parsed = parse_receipt_image(str(image))
    assert parsed.amount_cents == 5450
    assert parsed.category == "Food"
    assert "Scheidegg" in (parsed.merchant or "")


def test_log_expense_receipt_image_null_amount_is_400(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    def fake_null(_image_path: str) -> dict:
        return {
            "original_text": "[receipt photo: blurry.jpg]",
            "merchant": None,
            "amount_cents": None,
            "category": "Other",
            "confidence": 0.2,
            "needs_review": True,
            "nemotron_failed": False,
        }

    monkeypatch.setattr("ai.receipt.categorize_receipt", fake_null)
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/log-expense",
            data={"source": "receipt"},
            files={"file": ("blurry.jpg", _FAKE_JPEG, "image/jpeg")},
        )
        assert posted.status_code == 400
        body = posted.json()
        assert body["ok"] is False
        assert "amount" in str(body.get("error") or "").lower()
        history = client.get("/expenses").json()
        assert history["weekTotalCents"] == 0


def test_log_expense_receipt_image_does_not_use_text_stub(monkeypatch) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    os.environ["WHISPER_STUB"] = "1"

    def fail_if_text_parse(text: str):
        raise AssertionError(f"text heuristic should not run for receipt images: {text!r}")

    monkeypatch.setattr("main.parse_expense", fail_if_text_parse)
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/log-expense",
            data={"source": "receipt"},
            files={"file": ("lunch.jpg", _FAKE_JPEG, "image/jpeg")},
        )
        assert posted.status_code == 400
        body = posted.json()
        assert body["ok"] is False
        assert "amount" in str(body.get("error") or "").lower()


def test_log_expense_voice_file_uses_elevenlabs_and_nemotron(monkeypatch) -> None:
    monkeypatch.setenv("WHISPER_STUB", "0")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    def fake_transcribe(path, **_kwargs):
        assert Path(path).is_file()
        assert Path(path).stat().st_size > 0
        assert Path(path).suffix.lower() == ".m4a"
        return "spent fourteen bucks on lunch", "elevenlabs"

    def fake_categorize(text: str) -> dict:
        assert text == "spent fourteen bucks on lunch"
        return {
            "original_text": text,
            "merchant": None,
            "amount_cents": 1400,
            "category": "Food",
            "confidence": 0.94,
            "needs_review": False,
            "nemotron_failed": False,
        }

    monkeypatch.setattr("main.transcribe_audio", fake_transcribe)
    monkeypatch.setattr("ai.categorize.categorize_expense", fake_categorize)
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/log-expense",
            data={"source": "voice"},
            files={"file": ("expense.m4a", b"fake-m4a-bytes", "audio/mp4")},
        )
        assert posted.status_code == 200
        payload = posted.json()
        assert payload["parse"]["textEngine"] == "elevenlabs"
        assert payload["parse"]["engine"] == "nemotron"
        assert payload["expense"]["originalText"] == "spent fourteen bucks on lunch"
        assert payload["expense"]["amountCents"] == 1400
        assert payload["expense"]["source"] == "voice"


def test_log_expense_voice_file_prefers_audio_over_form_text(monkeypatch) -> None:
    monkeypatch.setenv("WHISPER_STUB", "0")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")

    def fake_transcribe(path, **_kwargs):
        assert Path(path).stat().st_size > 0
        return "two fifty for the bus", "elevenlabs"

    monkeypatch.setattr("main.transcribe_audio", fake_transcribe)
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/log-expense",
            data={"source": "voice", "text": "should not be used"},
            files={"file": ("expense.m4a", b"fake-m4a-bytes", "audio/mp4")},
        )
        assert posted.status_code == 200
        payload = posted.json()
        assert payload["parse"]["textEngine"] == "elevenlabs"
        assert payload["expense"]["originalText"] == "two fifty for the bus"
        assert payload["expense"]["amountCents"] == 250
        assert payload["expense"]["category"] == "Transport"


def test_log_expense_receipt_text_still_uses_parser() -> None:
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/log-expense",
            data={"source": "receipt", "text": "RECEIPT TOTAL 14.00 LUNCH"},
        )
        assert posted.status_code == 200
        payload = posted.json()
        assert payload["parse"]["engine"] == "heuristic"
        assert payload["expense"]["amountCents"] == 1400
        assert payload["expense"]["category"] == "Food"


def test_parse_limit_returns_spoken_dict_without_saving(monkeypatch) -> None:
    def fake_limit(raw_text: str) -> dict:
        assert "hundred" in raw_text
        return {
            "category": "Food",
            "amount_cents": 10000,
            "period": "weekly",
            "confidence": 0.93,
        }

    monkeypatch.setattr("ai.spoken_limit.understand_spoken_limit", fake_limit)
    _fresh_db()
    with TestClient(app) as client:
        before = client.get("/limits").json()["limits"]
        posted = client.post(
            "/parse-limit",
            json={"text": "cap my food spending at a hundred a week"},
        )
        assert posted.status_code == 200
        body = posted.json()
        assert body["category"] == "Food"
        assert body["amount_cents"] == 10000
        assert body["period"] == "weekly"
        assert body["confidence"] == 0.93
        assert body["readyToSave"] is True
        assert "/limits" in body["saveHint"]
        after = client.get("/limits").json()["limits"]
        assert after == before
        assert after["Food"] == 5000

        saved = client.post("/limits", json={"category": "Food", "limitCents": 10000})
        assert saved.status_code == 200
        assert saved.json()["limits"]["Food"] == 10000


def test_parse_limit_null_safe_on_failure(monkeypatch) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post("/parse-limit", json={"text": "I want to spend less this month"})
        assert posted.status_code == 200
        body = posted.json()
        assert body["category"] is None
        assert body["amount_cents"] is None
        assert body["period"] == "weekly"
        assert body["confidence"] == 0.0
        assert body["readyToSave"] is False
        assert client.get("/limits").json()["limits"]["Food"] == 5000


def test_parse_limit_rejects_empty_text() -> None:
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post("/parse-limit", json={"text": ""})
        assert posted.status_code == 422
        # Existing limits body is unchanged
        saved = client.post("/limits", json={"category": "Transport", "limitCents": 2500})
        assert saved.status_code == 200
        assert saved.json()["limits"]["Transport"] == 2500


def _fake_call_audio(captured: list[str]):
    def fake_success(sentence, output_path):
        captured.append(sentence)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x01ulaw")
        return {"success": True, "audio_path": output_path}

    return fake_success


def test_classify_spoken_reply_intents() -> None:
    assert classify_spoken_reply("").name == "empty"
    assert classify_spoken_reply("   ").name == "empty"
    assert looks_like_ack("okay thanks")
    assert classify_spoken_reply("okay").name == "ack"
    assert classify_spoken_reply("Thanks!").name == "ack"
    assert classify_spoken_reply("got it").name == "ack"

    expense = classify_spoken_reply("I spent twenty dollars on lunch")
    assert expense.name == "log_expense"
    assert expense.amount_cents == 2000
    assert expense.category == "Food"

    assert looks_like_limit("set food limit to fifty")
    limit = classify_spoken_reply("set food limit to fifty")
    assert limit.name == "set_limit"
    assert limit.category == "Food"
    assert limit.amount_cents == 5000

    cap = heuristic_spoken_limit("cap my food spending at a hundred a week")
    assert cap is not None
    assert cap["category"] == "Food"
    assert cap["amount_cents"] == 10000
    assert classify_spoken_reply("cap my food spending at a hundred a week").name == "set_limit"

    assert classify_spoken_reply("what's the weather").name == "unknown"
    assert classify_spoken_reply("set food limit to fifty").name != "log_expense"


def test_render_play_twiml_play_only_when_gather_setup_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CALL_AUDIO_DIR", str(tmp_path / "call_audio"))
    token = "ab" * 16
    audio = call_audio_path(token)
    assert audio is not None
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"\x00\x01ulaw")

    xml = render_play_twiml(token, base="https://demo.ngrok-free.app", include_gather=False)
    assert xml is not None
    assert "<Play>" in xml
    assert "<Gather" not in xml

    def boom(**_kwargs):
        raise RuntimeError("no gather url")

    monkeypatch.setattr("twilio_client.twiml_gather_url", boom)
    xml = render_play_twiml(token, base="https://demo.ngrok-free.app")
    assert xml is not None
    assert f"https://demo.ngrok-free.app/call-audio/{token}.ulaw" in xml
    assert "<Gather" not in xml


def _assert_keeps_listening(body: str) -> None:
    assert "<Gather" in body
    assert 'input="speech dtmf"' in body
    assert "actionOnEmptyResult" in body
    assert "/twiml/gather" in body
    assert "<Redirect>" in body
    assert "<Hangup" not in body


def test_gather_ack_keeps_listening(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")
    spoken: list[str] = []
    monkeypatch.setattr("twilio_client.get_call_audio", _fake_call_audio(spoken))
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/twiml/gather",
            data={"SpeechResult": "okay thanks", "Confidence": "0.91"},
        )
        assert posted.status_code == 200
        assert "xml" in (posted.headers.get("content-type") or "")
        body = posted.text
        assert "<Response>" in body
        assert "<Play>" in body
        _assert_keeps_listening(body)
        assert spoken
        assert "Got it" in spoken[0]
        assert "Goodbye" not in spoken[0]
        assert "$" not in spoken[0]


def test_gather_logs_expense_from_speech(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")
    spoken: list[str] = []
    monkeypatch.setattr("twilio_client.get_call_audio", _fake_call_audio(spoken))
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/twiml/gather",
            data={"SpeechResult": "I spent twenty dollars on lunch", "Confidence": "0.88"},
        )
        assert posted.status_code == 200
        body = posted.text
        assert "<Play>" in body
        _assert_keeps_listening(body)
        assert "Goodbye" not in body
        history = client.get("/expenses").json()
        assert history["weekTotalCents"] == 2000
        assert history["expenses"][0]["category"] == "Food"
        assert history["expenses"][0]["amountCents"] == 2000
        assert history["expenses"][0]["source"] == "voice"
        assert history["expenses"][0]["originalText"] == "I spent twenty dollars on lunch"
        assert spoken
        assert "twenty dollars" in spoken[0]
        assert "Food" in spoken[0]
        assert "$" not in spoken[0]
        assert "CHF" not in spoken[0]
        assert "2000" not in spoken[0]


def test_gather_expense_mentions_over_limit_in_spoken_usd(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")
    spoken: list[str] = []
    monkeypatch.setattr("twilio_client.get_call_audio", _fake_call_audio(spoken))
    _fresh_db()
    with TestClient(app) as client:
        client.post("/limits", json={"category": "Food", "limitCents": 1000})
        posted = client.post(
            "/twiml/gather",
            data={"SpeechResult": "I spent twenty dollars on lunch"},
        )
        assert posted.status_code == 200
        assert spoken
        assert "twenty dollars" in spoken[0]
        assert "ten dollars" in spoken[0]
        assert "$" not in spoken[0]
        assert "CHF" not in spoken[0]


def test_gather_sets_limit_from_speech_heuristic(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")
    spoken: list[str] = []
    monkeypatch.setattr("twilio_client.get_call_audio", _fake_call_audio(spoken))
    _fresh_db()
    with TestClient(app) as client:
        assert client.get("/limits").json()["limits"]["Food"] == 5000
        posted = client.post(
            "/twiml/gather",
            data={"SpeechResult": "set food limit to thirty"},
        )
        assert posted.status_code == 200
        _assert_keeps_listening(posted.text)
        assert client.get("/limits").json()["limits"]["Food"] == 3000
        assert spoken
        assert "thirty dollars" in spoken[0]
        assert "Food" in spoken[0]
        assert "$" not in spoken[0]
        assert "3000" not in spoken[0]


def test_gather_sets_limit_from_spoken_limit_parser(monkeypatch, tmp_path) -> None:
    def fake_limit(raw_text: str) -> dict:
        assert "hundred" in raw_text
        return {
            "category": "Food",
            "amount_cents": 10000,
            "period": "weekly",
            "confidence": 0.93,
        }

    monkeypatch.setattr("ai.spoken_limit.understand_spoken_limit", fake_limit)
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")
    spoken: list[str] = []
    monkeypatch.setattr("twilio_client.get_call_audio", _fake_call_audio(spoken))
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/twiml/gather",
            data={"SpeechResult": "cap my food spending at a hundred a week"},
        )
        assert posted.status_code == 200
        _assert_keeps_listening(posted.text)
        assert client.get("/limits").json()["limits"]["Food"] == 10000
        assert spoken
        assert "one hundred dollars" in spoken[0]
        assert "$" not in spoken[0]


def test_gather_empty_keeps_listening_silently(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")
    spoken: list[str] = []
    monkeypatch.setattr("twilio_client.get_call_audio", _fake_call_audio(spoken))
    _fresh_db()
    with TestClient(app) as client:
        first = client.post("/twiml/gather", data={"SpeechResult": ""})
        assert first.status_code == 200
        _assert_keeps_listening(first.text)
        assert 'timeout="8"' in first.text
        assert "<Play>" not in first.text
        assert spoken == []

        second = client.post("/twiml/gather", data={"SpeechResult": ""})
        assert second.status_code == 200
        _assert_keeps_listening(second.text)
        assert spoken == []


def test_gather_unknown_keeps_listening(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")
    spoken: list[str] = []
    monkeypatch.setattr("twilio_client.get_call_audio", _fake_call_audio(spoken))
    _fresh_db()
    with TestClient(app) as client:
        first = client.post(
            "/twiml/gather",
            data={"SpeechResult": "what is the weather in Pittsburgh"},
        )
        assert first.status_code == 200
        _assert_keeps_listening(first.text)
        assert spoken
        assert "didn't catch" in spoken[0]
        assert "Goodbye" not in spoken[0]

        second = client.post(
            "/twiml/gather",
            data={"SpeechResult": "still nonsense"},
        )
        assert second.status_code == 200
        _assert_keeps_listening(second.text)
        assert len(spoken) == 2
        assert "didn't catch" in spoken[1]


def test_gather_falls_back_to_say_when_tts_fails(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")

    def fake_failure(sentence, output_path):
        return {"success": False, "fallback_text": sentence}

    monkeypatch.setattr("twilio_client.get_call_audio", fake_failure)
    _fresh_db()
    with TestClient(app) as client:
        posted = client.post(
            "/twiml/gather",
            data={"SpeechResult": "I spent twenty dollars on lunch"},
        )
        assert posted.status_code == 200
        body = posted.text
        assert "<Say>" in body
        _assert_keeps_listening(body)
        assert "twenty dollars" in body
        assert "Goodbye" not in body
        assert "$" not in body
        assert "CHF" not in body
        assert "2000" not in body
        assert client.get("/expenses").json()["weekTotalCents"] == 2000


def test_gather_say_fallback_rewrites_raw_money(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")

    def fake_failure(sentence, output_path):
        return {"success": False, "fallback_text": sentence}

    monkeypatch.setattr("twilio_client.get_call_audio", fake_failure)
    monkeypatch.setattr(
        "main.handle_spoken_reply",
        lambda *_args, **_kwargs: type(
            "Outcome",
            (),
            {"spoken": "You are over by $20.00 after CHF 54.50", "gather_again": True, "intent": "ack"},
        )(),
    )
    with TestClient(app) as client:
        posted = client.post("/twiml/gather", data={"SpeechResult": "okay"})
        assert posted.status_code == 200
        body = posted.text
        _assert_keeps_listening(body)
        assert "twenty dollars" in body
        assert "fifty-four dollars and fifty cents" in body
        assert "$" not in body
        assert "CHF" not in body


def test_gather_multi_turn_expense_then_limit(monkeypatch, tmp_path) -> None:
    _twilio_env(monkeypatch, tmp_path, PUBLIC_BASE_URL="https://demo.ngrok-free.app")
    spoken: list[str] = []
    monkeypatch.setattr("twilio_client.get_call_audio", _fake_call_audio(spoken))
    _fresh_db()
    with TestClient(app) as client:
        first = client.post(
            "/twiml/gather",
            data={"SpeechResult": "I spent twenty dollars on lunch"},
        )
        assert first.status_code == 200
        _assert_keeps_listening(first.text)
        assert client.get("/expenses").json()["weekTotalCents"] == 2000

        second = client.post(
            "/twiml/gather",
            data={"SpeechResult": "set food limit to eighty"},
        )
        assert second.status_code == 200
        _assert_keeps_listening(second.text)
        assert client.get("/limits").json()["limits"]["Food"] == 8000
        assert client.get("/expenses").json()["weekTotalCents"] == 2000
        assert any("twenty dollars" in line for line in spoken)
        assert any("eighty dollars" in line for line in spoken)
        assert all("Goodbye" not in line for line in spoken)
