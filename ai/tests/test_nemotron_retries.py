"""Mocked tests for Nemotron JSON helper retries. No NVIDIA key required."""

from __future__ import annotations

import os

os.environ.pop("NVIDIA_API_KEY", None)

from ai.nemotron import ask_nemotron_json  # noqa: E402


def test_ask_nemotron_json_single_attempt_by_default(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.delenv("NEMOTRON_RETRIES", raising=False)
    calls = []

    class FakeMessage:
        content = "not-json"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            extra = kwargs.get("extra_body") or {}
            assert extra.get("chat_template_kwargs", {}).get("enable_thinking") is False
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("ai.nemotron._get_client", lambda: FakeClient())
    assert ask_nemotron_json("sys", "user") is None
    assert len(calls) == 1


def test_ask_nemotron_json_parse_retry_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setenv("NEMOTRON_RETRIES", "2")
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(1)
            if len(calls) == 1:

                class Msg:
                    content = "not-json"

                class Choice:
                    message = Msg()

                class Resp:
                    choices = [Choice()]

                return Resp()

            class Msg:
                content = '{"ok": true}'

            class Choice:
                message = Msg()

            class Resp:
                choices = [Choice()]

            return Resp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("ai.nemotron._get_client", lambda: FakeClient())
    result = ask_nemotron_json("sys", "user")
    assert result == {"ok": True}
    assert len(calls) == 2
