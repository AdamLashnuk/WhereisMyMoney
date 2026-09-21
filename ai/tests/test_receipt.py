"""Mocked unit tests for Person C receipt vision. No NVIDIA key required."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.pop("NVIDIA_API_KEY", None)

from ai.receipt import (  # noqa: E402
    SYSTEM_PROMPT,
    categorize_receipt,
    coerce_amount_cents,
    format_original_text,
    jpeg_bytes_for_vision,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BERGHOTEL = FIXTURES / "berghotel_grosse_scheidegg.png"


def _client_returning(payload: str | dict):
    content = payload if isinstance(payload, str) else json.dumps(payload)

    class FakeMessage:
        def __init__(self):
            self.content = content

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            assert kwargs["model"] == "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
            extra = kwargs.get("extra_body") or {}
            assert extra.get("chat_template_kwargs", {}).get("enable_thinking") is False
            messages = kwargs["messages"]
            assert messages[0]["role"] == "system"
            user = messages[1]["content"]
            assert any(part.get("type") == "image_url" for part in user)
            return FakeResponse()

    completions = FakeCompletions()

    class FakeChat:
        def __init__(self):
            self.completions = completions

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()

    return FakeClient(), completions


def test_categorize_receipt_without_key_is_flagged(tmp_path) -> None:
    image = tmp_path / "lunch.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fake")
    result = categorize_receipt(str(image))
    assert result["amount_cents"] is None
    assert result["needs_review"] is True
    assert result["category"] == "Other"
    assert result["confidence"] == 0.0
    assert result["nemotron_failed"] is True
    assert "lunch.jpg" in result["original_text"]


def test_categorize_receipt_maps_vision_json(monkeypatch, tmp_path) -> None:
    image = tmp_path / "chipotle.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fake")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    client, completions = _client_returning(
        {
            "merchant": "Chipotle",
            "amount_cents": 1450,
            "category": "Food",
            "confidence": 0.91,
            "needs_review": False,
        }
    )
    monkeypatch.setattr("ai.receipt._get_client", lambda: client)
    result = categorize_receipt(str(image))
    assert len(completions.calls) == 1
    assert result["merchant"] == "Chipotle"
    assert result["amount_cents"] == 1450
    assert result["category"] == "Food"
    assert result["confidence"] == 0.91
    assert result["needs_review"] is False
    assert result["nemotron_failed"] is False
    assert result["original_text"] == "Chipotle · $14.50"


def test_berghotel_receipt_total_is_5450_not_line_item_or_fx(monkeypatch) -> None:
    """Regression: TOTAL CHF 54.50 — not Schnitzel 22.00, MwSt 3.85, or EUR 36.33."""
    assert BERGHOTEL.is_file()
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    client, completions = _client_returning(
        {
            "merchant": "Berghotel Grosse Scheidegg",
            "amount_cents": 5450,
            "currency": "CHF",
            "category": "Food",
            "confidence": 0.93,
            "needs_review": False,
        }
    )
    monkeypatch.setattr("ai.receipt._get_client", lambda: client)
    result = categorize_receipt(str(BERGHOTEL))
    assert len(completions.calls) == 1
    assert result["amount_cents"] == 5450
    assert result["category"] == "Food"
    merchant = (result["merchant"] or "").lower()
    assert "berghotel" in merchant
    assert "scheidegg" in merchant
    assert result["original_text"] == "Berghotel Grosse Scheidegg · CHF 54.50"
    assert result["nemotron_failed"] is False
    prompt = completions.calls[0]["messages"][0]["content"]
    user_text = completions.calls[0]["messages"][1]["content"][0]["text"]
    blob = f"{prompt}\n{user_text}\n{SYSTEM_PROMPT}".lower()
    assert "mwst" in blob
    assert "summe" in blob
    assert "entspricht" in blob
    assert "line-item" in blob or "line item" in blob


def test_berghotel_coerces_major_minor_and_european_comma(monkeypatch) -> None:
    assert BERGHOTEL.is_file()
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    for raw in ("CHF 54.50", "54,50", 54.50, "5450"):
        client, _completions = _client_returning(
            {
                "merchant": "Berghotel Grosse Scheidegg",
                "amount_cents": raw,
                "currency": "CHF",
                "category": "Food",
                "confidence": 0.9,
                "needs_review": False,
            }
        )
        monkeypatch.setattr("ai.receipt._get_client", lambda client=client: client)
        result = categorize_receipt(str(BERGHOTEL))
        assert result["amount_cents"] == 5450, raw
        assert result["category"] == "Food"
        assert "Scheidegg" in (result["merchant"] or "")
        assert "CHF 54.50" in result["original_text"]


def test_coerce_amount_cents_helpers() -> None:
    assert coerce_amount_cents(1400) == 1400
    assert coerce_amount_cents("1400") == 1400
    assert coerce_amount_cents("14.00") == 1400
    assert coerce_amount_cents("$14") == 1400
    assert coerce_amount_cents("$14.00") == 1400
    assert coerce_amount_cents("CHF 54.50") == 5450
    assert coerce_amount_cents("54,50") == 5450
    assert coerce_amount_cents("CHF 54,50") == 5450
    assert coerce_amount_cents(54.50) == 5450
    assert coerce_amount_cents(5450) == 5450
    assert coerce_amount_cents(None) is None
    assert coerce_amount_cents("") is None
    assert coerce_amount_cents("lunch") is None
    assert coerce_amount_cents(True) is None
    assert coerce_amount_cents(-14) is None
    assert coerce_amount_cents("MwSt") is None


def test_jpeg_resize_produces_smaller_jpeg(tmp_path) -> None:
    from PIL import Image

    huge = tmp_path / "huge.png"
    Image.new("RGB", (4000, 3000), (240, 240, 240)).save(huge, format="PNG")
    original = huge.stat().st_size
    jpeg, meta = jpeg_bytes_for_vision(str(huge))
    assert jpeg[:3] == b"\xff\xd8\xff"
    assert meta["resized"] is True
    assert meta["max_edge"] <= 1280
    assert meta["jpeg_bytes"] < original
    assert len(jpeg) < original
    assert len(jpeg) < 400_000


def test_berghotel_fixture_encodes_as_jpeg() -> None:
    assert BERGHOTEL.is_file()
    jpeg, meta = jpeg_bytes_for_vision(str(BERGHOTEL))
    assert jpeg[:3] == b"\xff\xd8\xff"
    assert meta["fallback"] is False
    assert meta["max_edge"] <= 1280
    assert meta["jpeg_bytes"] <= meta["original_bytes"]


def test_vision_parse_error_is_single_attempt_by_default(monkeypatch, tmp_path) -> None:
    image = tmp_path / "blur.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fake")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.delenv("RECEIPT_VISION_RETRIES", raising=False)

    class FakeMessage:
        content = "not-json"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(1)
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("ai.receipt._get_client", lambda: FakeClient())
    result = categorize_receipt(str(image))
    assert len(calls) == 1
    assert result["amount_cents"] is None
    assert result["nemotron_failed"] is True


def test_format_original_text_includes_chf() -> None:
    text = format_original_text(
        "berghotel.png",
        "Berghotel Grosse Scheidegg",
        5450,
        "CHF",
    )
    assert text == "Berghotel Grosse Scheidegg · CHF 54.50"
