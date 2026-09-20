"""Audio → text.

Tries a real transcriber when ``WHISPER_STUB`` is not ``1``:
1. ElevenLabs Scribe if ``ELEVENLABS_API_KEY`` is set
2. OpenAI Whisper API if ``OPENAI_API_KEY`` is set and the ``openai`` package exists
3. Local ``whisper`` (openai-whisper) if installed

Falls back to a deterministic stub so the server never crashes without a model.
Set ``WHISPER_STUB=1`` to force the stub (recommended for laptop demos).
Live ElevenLabs Scribe requires ``WHISPER_STUB=0`` (or unset) and ``ELEVENLABS_API_KEY``.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path

logger = logging.getLogger("whereismymoney.whisper")

STUB_VOICE_TEXT = "spent fourteen bucks on lunch"
STUB_RECEIPT_TEXT = "RECEIPT TOTAL 14.00 LUNCH"

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
DEFAULT_ELEVENLABS_MODEL = "scribe_v2"
_AUDIO_MIME = {
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".mp3": "audio/mpeg",
    ".mpeg": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
    ".caf": "audio/x-caf",
}


def whisper_stub_enabled() -> bool:
    return os.getenv("WHISPER_STUB", "").strip() in {"1", "true", "True", "yes", "YES"}


def _audio_mime(path: Path, content_type: str = "") -> str:
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype == "video/mp4":
        return "audio/mp4"
    if ctype.startswith("audio/"):
        return ctype
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed:
        return guessed
    return _AUDIO_MIME.get(path.suffix.lower(), "application/octet-stream")


def _upload_name(path: Path, filename: str = "") -> str:
    raw = (filename or "").strip() or path.name
    name = Path(raw).name or path.name
    if Path(name).suffix:
        return name
    return path.name or "expense.m4a"


def transcribe_audio(
    path: str | Path,
    *,
    source: str = "voice",
    content_type: str = "",
    filename: str = "",
) -> tuple[str, str]:
    """Return ``(text, engine)``: ``elevenlabs``, ``openai``, ``local``, or ``stub``.

    Never raises on missing models or keys — returns the stub instead.
    Live STT requires ``WHISPER_STUB=0`` (or unset) and ``ELEVENLABS_API_KEY``.
    """
    fallback = STUB_VOICE_TEXT if source == "voice" else STUB_RECEIPT_TEXT
    if whisper_stub_enabled():
        logger.info("WHISPER_STUB=1 — skipping real transcription")
        return fallback, "stub"

    audio_path = Path(path)
    if not audio_path.is_file() or audio_path.stat().st_size == 0:
        logger.warning("No audio bytes at %s; using stub", audio_path)
        return fallback, "stub"

    text = _try_elevenlabs(audio_path, content_type=content_type, filename=filename)
    if text:
        return text, "elevenlabs"

    text = _try_openai(audio_path)
    if text:
        return text, "openai"

    text = _try_local_whisper(audio_path)
    if text:
        return text, "local"

    logger.info("No speech-to-text backend available; using stub transcription")
    return fallback, "stub"


def _try_elevenlabs(path: Path, *, content_type: str = "", filename: str = "") -> str | None:
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import httpx
    except ImportError:
        logger.info("httpx package not installed; skip ElevenLabs STT")
        return None
    model_id = os.getenv("ELEVENLABS_STT_MODEL", "").strip() or DEFAULT_ELEVENLABS_MODEL
    mime = _audio_mime(path, content_type)
    upload_name = _upload_name(path, filename)
    try:
        with path.open("rb") as handle:
            response = httpx.post(
                ELEVENLABS_STT_URL,
                headers={"xi-api-key": api_key},
                data={"model_id": model_id, "language_code": "eng"},
                files={"file": (upload_name, handle, mime)},
                timeout=60.0,
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        text = (payload.get("text") or "").strip()
        return text or None
    except Exception as exc:
        logger.warning("ElevenLabs STT failed: %s", exc)
        return None


def _try_openai(path: Path) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        logger.info("openai package not installed; skip OpenAI Whisper")
        return None
    try:
        client = OpenAI(api_key=api_key)
        with path.open("rb") as handle:
            result = client.audio.transcriptions.create(model="whisper-1", file=handle)
        text = (getattr(result, "text", None) or "").strip()
        return text or None
    except Exception as exc:  # pragma: no cover - network / API failures
        logger.warning("OpenAI Whisper failed: %s", exc)
        return None


def _try_local_whisper(path: Path) -> str | None:
    try:
        import whisper
    except ImportError:
        return None
    try:
        model_name = os.getenv("WHISPER_MODEL", "base")
        model = _load_local_model(whisper, model_name)
        result = model.transcribe(str(path))
        text = (result.get("text") or "").strip()
        return text or None
    except Exception as exc:  # pragma: no cover
        logger.warning("Local Whisper failed: %s", exc)
        return None


_local_model = None


def _load_local_model(whisper_mod, model_name: str):
    global _local_model
    if _local_model is None:
        logger.info("Loading local Whisper model %s", model_name)
        _local_model = whisper_mod.load_model(model_name)
    return _local_model
