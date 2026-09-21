"""Mocked unit tests for Person C spoken-limit parser. No NVIDIA key required."""

from __future__ import annotations

import os

os.environ.pop("NVIDIA_API_KEY", None)

from ai.spoken_limit import understand_spoken_limit  # noqa: E402


def test_understand_spoken_limit_without_key_is_null() -> None:
    result = understand_spoken_limit("cap my food spending at a hundred a week")
    assert result == {
        "category": None,
        "amount_cents": None,
        "period": "weekly",
        "confidence": 0.0,
    }


def test_understand_spoken_limit_maps_json(monkeypatch) -> None:
    def fake_ask(system_prompt, user_message, max_tokens=150):
        assert "limit" in system_prompt.lower()
        assert "hundred" in user_message
        assert max_tokens == 150
        return {
            "category": "Food",
            "amount_cents": 10000,
            "period": "weekly",
            "confidence": 0.93,
        }

    monkeypatch.setattr("ai.spoken_limit.ask_nemotron_json", fake_ask)
    result = understand_spoken_limit("cap my food spending at a hundred a week")
    assert result["category"] == "Food"
    assert result["amount_cents"] == 10000
    assert result["period"] == "weekly"
    assert result["confidence"] == 0.93


def test_understand_spoken_limit_invalid_category_becomes_null(monkeypatch) -> None:
    monkeypatch.setattr(
        "ai.spoken_limit.ask_nemotron_json",
        lambda **_kwargs: {
            "category": "Snacks",
            "amount_cents": 500,
            "period": "monthly",
            "confidence": 0.4,
        },
    )
    result = understand_spoken_limit("limit snacks to five bucks")
    assert result["category"] is None
    assert result["amount_cents"] == 500
    assert result["period"] == "weekly"
    assert result["confidence"] == 0.4
