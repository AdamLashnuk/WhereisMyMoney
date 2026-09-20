"""Outbound phone calls via Twilio.

Missing credentials must never crash the process: ``place_call`` returns
``{"ok": False, ...}`` so FastAPI can still boot and serve the app.

When ElevenLabs TTS succeeds and ``PUBLIC_BASE_URL`` (or ``CALL_AUDIO_BASE_URL``)
is a public HTTPS origin, the call ``url=`` points at our first-party TwiML
``/twiml/play/{token}`` which ``<Play>``s ``/call-audio/{token}.ulaw``.

Otherwise we fall back to a Twimlets message URL (trial-safe ``<Say>``).
Trial accounts often reject inline ``twiml=`` on Calls.create.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

logger = logging.getLogger("whereismymoney.twilio")

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BACKEND_DIR = Path(__file__).resolve().parent
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

CALL_AUDIO_EXTENSION = ".ulaw"
CALL_AUDIO_MEDIA_TYPE = "audio/x-mulaw"

try:
    from ai.elevenlabs_tts import (
        AUDIO_EXTENSION as CALL_AUDIO_EXTENSION,
        AUDIO_MEDIA_TYPE as CALL_AUDIO_MEDIA_TYPE,
        get_call_audio,
    )
except Exception:  # pragma: no cover - module always present after this PR
    def get_call_audio(sentence, output_path):  # type: ignore[misc]
        return {"success": False, "fallback_text": sentence}

try:
    from ai.money_speech import rewrite_money_for_speech
except Exception:  # pragma: no cover
    def rewrite_money_for_speech(text):  # type: ignore[misc]
        return text


def twilio_configured() -> bool:
    return bool(
        os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        and os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        and os.getenv("TWILIO_PHONE_NUMBER", "").strip()
    )


def destination_phone(explicit: str | None = None) -> str:
    return (explicit or os.getenv("MY_PHONE_NUMBER") or "").strip()


def public_base_url() -> str:
    """HTTPS origin Twilio can reach (ngrok). Empty if unset."""
    return (
        os.getenv("PUBLIC_BASE_URL", "").strip()
        or os.getenv("CALL_AUDIO_BASE_URL", "").strip()
    ).rstrip("/")


def call_audio_dir() -> Path:
    raw = os.getenv("CALL_AUDIO_DIR", "").strip()
    path = Path(raw) if raw else _BACKEND_DIR / "call_audio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_call_audio_token(token: str) -> bool:
    return bool(token and _TOKEN_RE.fullmatch(token))


def call_audio_filename(token: str) -> str:
    return f"{token}{CALL_AUDIO_EXTENSION}"


def call_audio_path(token: str) -> Path | None:
    if not is_call_audio_token(token):
        return None
    audio_dir = call_audio_dir().resolve()
    path = (audio_dir / call_audio_filename(token)).resolve()
    try:
        path.relative_to(audio_dir)
    except ValueError:
        return None
    return path


def twiml_play_url(token: str, *, base: str | None = None) -> str | None:
    origin = (base or public_base_url()).rstrip("/")
    if not origin:
        return None
    return f"{origin}/twiml/play/{token}"


def call_audio_public_url(token: str, *, base: str | None = None) -> str | None:
    origin = (base or public_base_url()).rstrip("/")
    if not origin:
        return None
    return f"{origin}/call-audio/{call_audio_filename(token)}"


def render_play_twiml(token: str, *, base: str | None = None) -> str | None:
    audio_url = call_audio_public_url(token, base=base)
    if not audio_url:
        return None
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>"
        f"<Play>{xml_escape(audio_url)}</Play>"
        "</Response>"
    )


def twimlets_say_url(spoken_text: str) -> str:
    message = rewrite_money_for_speech((spoken_text or "Where Is My Money.").strip())[:900]
    return "https://twimlets.com/message?Message%5B0%5D=" + quote(message)


def place_call(to: str | None, spoken_text: str) -> dict[str, Any]:
    """Place a TTS phone call. Returns ``ok: false`` instead of raising."""
    dest = destination_phone(to)
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_PHONE_NUMBER", "").strip()

    if not (sid and token and from_number):
        logger.info("Twilio keys missing — not placing a call")
        return {
            "ok": False,
            "error": "Twilio is not configured (set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER)",
            "to": dest or None,
        }
    if not dest:
        return {"ok": False, "error": "No destination phone number in settings or MY_PHONE_NUMBER"}

    try:
        from twilio.rest import Client
    except ImportError:
        logger.warning("twilio package is not installed")
        return {"ok": False, "error": "twilio package is not installed"}

    message = rewrite_money_for_speech((spoken_text or "Where Is My Money.").strip())[:900]
    twiml_url, voice = _outbound_twiml_url(message)

    try:
        client = Client(sid, token)
        call = client.calls.create(to=dest, from_=from_number, url=twiml_url)
        return {"ok": True, "sid": call.sid, "to": dest, "voice": voice, "twimlUrl": twiml_url}
    except Exception as exc:
        logger.warning("Twilio call failed: %s", exc)
        return {"ok": False, "error": str(exc), "to": dest, "voice": voice}


def _outbound_twiml_url(message: str) -> tuple[str, str]:
    """Return ``(url, voice)`` — ElevenLabs Play TwiML or Twimlets Say fallback."""
    audio_token = uuid.uuid4().hex
    output_path = call_audio_dir() / call_audio_filename(audio_token)
    try:
        result = get_call_audio(message, str(output_path))
    except Exception as exc:
        logger.warning("ElevenLabs get_call_audio raised: %s", exc)
        result = {"success": False, "fallback_text": message}

    play_url = None
    if isinstance(result, dict) and result.get("success"):
        audio_path = Path(str(result.get("audio_path") or output_path))
        if audio_path.is_file() and audio_path.stat().st_size > 0:
            play_url = twiml_play_url(audio_token)
        else:
            logger.warning("ElevenLabs reported success but audio file is missing")

    if play_url:
        logger.info("Using ElevenLabs Play TwiML at %s", play_url)
        return play_url, "elevenlabs"

    if public_base_url() == "":
        logger.info("PUBLIC_BASE_URL unset — falling back to Twimlets Say")
    else:
        logger.info("ElevenLabs TTS unavailable — falling back to Twimlets Say")
    return twimlets_say_url(message), "twimlets"
