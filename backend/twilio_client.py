"""Outbound phone calls via Twilio.

Missing credentials must never crash the process: ``place_call`` returns
``{"ok": False, ...}`` so FastAPI can still boot and serve the app.

When ElevenLabs TTS succeeds and ``PUBLIC_BASE_URL`` (or ``CALL_AUDIO_BASE_URL``)
is a public HTTPS origin, the call ``url=`` points at our first-party TwiML
``/twiml/play/{token}`` which ``<Play>``s ``/call-audio/{token}.ulaw``, then
``<Gather input="speech dtmf">`` so the callee can talk back. Twilio posts
``SpeechResult`` to ``/twiml/gather``. After each bot reply we Gather again
until the callee hangs up.

If Gather TwiML cannot be built, we serve play-only (alert/summary still
plays). If ``PUBLIC_BASE_URL`` is missing or TTS fails, we fall back to a
Twimlets message URL (trial-safe ``<Say>``, one-way). Trial accounts often
reject inline ``twiml=`` on Calls.create.
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

GATHER_TIMEOUT_SECONDS = 8
GATHER_PROMPT = "You can reply now."
GATHER_HINTS = "spent,lunch,food,limit,thanks,okay,dollars,budget"

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


def twiml_gather_url(*, base: str | None = None) -> str | None:
    origin = (base or public_base_url()).rstrip("/")
    if not origin:
        return None
    return f"{origin}/twiml/gather"


def call_audio_public_url(token: str, *, base: str | None = None) -> str | None:
    origin = (base or public_base_url()).rstrip("/")
    if not origin:
        return None
    return f"{origin}/call-audio/{call_audio_filename(token)}"


def _xml_response(*verbs: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<Response>{''.join(verbs)}</Response>"
    )


def _say_verb(text: str) -> str:
    spoken = rewrite_money_for_speech((text or "").strip())
    if not spoken:
        return ""
    return f"<Say>{xml_escape(spoken)}</Say>"


def _play_verb(url: str) -> str:
    return f"<Play>{xml_escape(url)}</Play>"


def _gather_verb(*, action: str, inner: str = "") -> str:
    return (
        f'<Gather input="speech dtmf" timeout="{GATHER_TIMEOUT_SECONDS}" '
        'speechTimeout="auto" actionOnEmptyResult="true" method="POST" '
        f'language="en-US" hints="{xml_escape(GATHER_HINTS)}" '
        f'action="{xml_escape(action)}">'
        f"{inner}"
        "</Gather>"
    )


def _gather_action(base: str | None) -> str:
    """Absolute gather URL when we have an origin, else a relative path Twilio can resolve."""
    return twiml_gather_url(base=base) or "/twiml/gather"


def _gather_followup_verbs(*, base: str | None, inner: str | None = None) -> list[str]:
    action = _gather_action(base)
    prompt = inner if inner is not None else _say_verb(GATHER_PROMPT)
    return [
        _gather_verb(action=action, inner=prompt),
        f"<Redirect>{xml_escape(action)}</Redirect>",
    ]


def render_play_twiml(
    token: str,
    *,
    base: str | None = None,
    include_gather: bool = True,
) -> str | None:
    """Alert/summary ``<Play>``, then speech ``<Gather>`` when a public origin exists.

    If Gather setup fails, returns play-only TwiML so the outbound message still
    plays (one-way). Missing ``PUBLIC_BASE_URL`` already keeps ``place_call`` on
    Twimlets; this is the extra safety net when Twilio is fetching our TwiML.
    """
    audio_url = call_audio_public_url(token, base=base)
    if not audio_url:
        return None
    verbs = [_play_verb(audio_url)]
    if include_gather:
        try:
            verbs.extend(_gather_followup_verbs(base=base))
        except Exception:
            logger.warning("Gather TwiML setup failed; serving play-only", exc_info=True)
    return _xml_response(*verbs)


def cache_call_audio(sentence: str) -> str | None:
    """Synthesize Victoria μ-law. Returns a 32-hex token on success, else None."""
    message = rewrite_money_for_speech((sentence or "Where Is My Money.").strip())[:900]
    audio_token = uuid.uuid4().hex
    output_path = call_audio_dir() / call_audio_filename(audio_token)
    try:
        result = get_call_audio(message, str(output_path))
    except Exception as exc:
        logger.warning("ElevenLabs get_call_audio raised: %s", exc)
        return None
    if isinstance(result, dict) and result.get("success"):
        audio_path = Path(str(result.get("audio_path") or output_path))
        if audio_path.is_file() and audio_path.stat().st_size > 0:
            return audio_token
        logger.warning("ElevenLabs reported success but audio file is missing")
    return None


def render_spoken_twiml(
    spoken_text: str,
    *,
    base: str | None = None,
    gather_again: bool = True,
) -> str:
    """Reply TwiML: ElevenLabs ``<Play>`` when possible, else ``<Say>``.

    Always follows the reply with ``<Gather>`` so the callee can talk again
    until they hang up. Empty ``spoken_text`` is a silent re-listen (timeout).

    All money in ``spoken_text`` is rewritten to spoken USD before TTS/Say.
    """
    spoken = rewrite_money_for_speech((spoken_text or "").strip())[:900]
    origin = (base or public_base_url()).rstrip("/")
    lead = ""
    if spoken:
        token = cache_call_audio(spoken)
        play_url = call_audio_public_url(token, base=origin or None) if token else None
        lead = _play_verb(play_url) if play_url else _say_verb(spoken)

    if gather_again:
        try:
            follow = _gather_followup_verbs(base=origin or None, inner="")
            if follow:
                return _xml_response(*(v for v in (lead, *follow) if v))
        except Exception:
            logger.warning("Gather loop TwiML setup failed; playing reply only", exc_info=True)
    if lead:
        return _xml_response(lead)
    return _xml_response(_say_verb(GATHER_PROMPT))


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
    audio_token = cache_call_audio(message)
    play_url = twiml_play_url(audio_token) if audio_token else None
    if play_url:
        logger.info("Using ElevenLabs Play TwiML at %s", play_url)
        return play_url, "elevenlabs"

    if public_base_url() == "":
        logger.info("PUBLIC_BASE_URL unset — falling back to Twimlets Say")
    else:
        logger.info("ElevenLabs TTS unavailable — falling back to Twimlets Say")
    return twimlets_say_url(message), "twimlets"
