"""Unit tests for spoken-USD TTS money formatting. No API keys required."""

from __future__ import annotations

from ai.money_speech import cents_to_speech, rewrite_money_for_speech


def test_cents_to_speech_small_mid_large() -> None:
    assert cents_to_speech(5450) == "fifty-four dollars and fifty cents"
    assert cents_to_speech(18550) == "one hundred eighty-five dollars and fifty cents"
    assert cents_to_speech(999999) == (
        "nine thousand nine hundred ninety-nine dollars and ninety-nine cents"
    )


def test_cents_to_speech_singulars_and_zero() -> None:
    assert cents_to_speech(0) == "zero dollars"
    assert cents_to_speech(1) == "one cent"
    assert cents_to_speech(2) == "two cents"
    assert cents_to_speech(100) == "one dollar"
    assert cents_to_speech(101) == "one dollar and one cent"
    assert cents_to_speech(200) == "two dollars"


def test_cents_to_speech_thousands_and_millions() -> None:
    assert cents_to_speech(100_000) == "one thousand dollars"
    assert cents_to_speech(1_000_000) == "ten thousand dollars"
    assert cents_to_speech(100_000_000) == "one million dollars"
    assert cents_to_speech(-400) == "four dollars"


def test_cents_to_speech_is_usd_words_never_symbols_or_raw_cents() -> None:
    spoken = cents_to_speech(18550)
    assert "dollar" in spoken
    assert "cent" in spoken
    assert "CHF" not in spoken
    assert "franc" not in spoken.lower()
    assert "$" not in spoken
    assert "18550" not in spoken
    assert "185.50" not in spoken


def test_rewrite_history_chf_line_to_spoken_usd() -> None:
    spoken = rewrite_money_for_speech("Berghotel Grosse Scheidegg · CHF 54.50")
    assert spoken == "Berghotel Grosse Scheidegg fifty-four dollars and fifty cents"
    assert "CHF" not in spoken
    assert "franc" not in spoken.lower()
    assert "$" not in spoken
    assert "54.50" not in spoken


def test_rewrite_dollar_and_euro_symbols() -> None:
    assert rewrite_money_for_speech("over by $185.50") == (
        "over by one hundred eighty-five dollars and fifty cents"
    )
    assert rewrite_money_for_speech("Entspricht in Euro €36.33") == (
        "Entspricht in Euro thirty-six dollars and thirty-three cents"
    )
    assert "CHF" not in rewrite_money_for_speech("total 54,50 CHF")
    assert rewrite_money_for_speech("total 54,50 CHF") == (
        "total fifty-four dollars and fifty cents"
    )


def test_overlimit_fallback_uses_spoken_usd(monkeypatch) -> None:
    from ai.overlimit_alert import overlimit_alert_sentence

    monkeypatch.setattr("ai.overlimit_alert.ask_nemotron_json", lambda **_kwargs: None)
    spoken = overlimit_alert_sentence("Food", 5000, 18550)
    assert spoken == (
        "This is your spending limit alert. You've gone over your Food "
        "limit by one hundred eighty-five dollars and fifty cents."
    )
    assert "$" not in spoken
    assert "CHF" not in spoken


def test_weekly_pattern_sends_spoken_usd_not_raw_cents(monkeypatch) -> None:
    from ai.weekly_pattern import weekly_pattern_sentence

    captured: dict[str, str] = {}

    def fake_ask(*, system_prompt, user_message, max_tokens):
        captured["user_message"] = user_message
        captured["system_prompt"] = system_prompt
        return {"sentence": "Food jumped to $185.50 this week."}

    monkeypatch.setattr("ai.weekly_pattern.ask_nemotron_json", fake_ask)
    spoken = weekly_pattern_sentence(
        {"Food": 18550, "Transport": 0, "Subscriptions": 0, "Shopping": 0, "Bills": 0, "Other": 0},
        {"Food": 5000, "Transport": 0, "Subscriptions": 0, "Shopping": 0, "Bills": 0, "Other": 0},
    )
    assert "one hundred eighty-five dollars and fifty cents" in captured["user_message"]
    assert "fifty dollars" in captured["user_message"]
    assert "18550" not in captured["user_message"]
    assert "(cents)" not in captured["user_message"]
    assert spoken == "Food jumped to one hundred eighty-five dollars and fifty cents this week."
    assert "$" not in spoken
    assert "CHF" not in spoken
