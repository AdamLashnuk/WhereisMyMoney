"""Mocked unit tests for Person C receipt vision. No NVIDIA key required."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.pop("NVIDIA_API_KEY", None)

from ai.receipt import categorize_receipt  # noqa: E402


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

    class FakeMessage:
        content = '{"merchant":"Chipotle","amount_cents":1450,"category":"Food","confidence":0.91,"needs_review":false}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["model"] == "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
            messages = kwargs["messages"]
            assert messages[0]["role"] == "system"
            user = messages[1]["content"]
            assert any(part.get("type") == "image_url" for part in user)
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("ai.receipt._get_client", lambda: FakeClient())
    result = categorize_receipt(str(image))
    assert result["merchant"] == "Chipotle"
    assert result["amount_cents"] == 1450
    assert result["category"] == "Food"
    assert result["confidence"] == 0.91
    assert result["needs_review"] is False
    assert result["nemotron_failed"] is False
    assert Path(result["original_text"]).name.endswith("chipotle.jpg]") or "chipotle.jpg" in result["original_text"]
