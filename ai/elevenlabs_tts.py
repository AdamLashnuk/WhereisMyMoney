"""Person C — ElevenLabs TTS (Victoria) for outbound Twilio calls.

Soft-loads ``ELEVENLABS_API_KEY`` so a missing key never crashes FastAPI boot.
Person B should call ``get_call_audio`` and fall back to Twilio/Twimlets
``<Say>`` when ``success`` is False.

Telephony: request ``ulaw_8000`` (8 kHz μ-law) so Twilio ``<Play>`` can send
native phone audio instead of re-encoding a default MP3 down to 8 kHz.
"""

from dotenv import load_dotenv
import os

load_dotenv()

VOICE_ID = "XoUkt2bf6DlvSzRmvA8X"  # Victoria
OUTPUT_FORMAT = "ulaw_8000"
AUDIO_EXTENSION = ".ulaw"
# Twilio <Play> lists audio/ulaw; many Twilio guides also accept audio/x-mulaw.
AUDIO_MEDIA_TYPE = "audio/x-mulaw"
TTS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"


def elevenlabs_api_key():
    """Return ELEVENLABS_API_KEY or None. Never raises on a missing key."""
    key = os.getenv("ELEVENLABS_API_KEY")
    if key is None:
        return None
    key = str(key).strip()
    return key or None


# Soft-loaded at import (may be None). Prefer elevenlabs_api_key() at call time
# so tests / dotenv after import still see a later-set key.
ELEVENLABS_API_KEY = elevenlabs_api_key()


def text_to_speech(sentence, output_path):
    """
    Turns a sentence into a telephony μ-law file at output_path
    (e.g. "demo/weekly_call.ulaw"). Returns True on success, False on failure.
    """
    api_key = elevenlabs_api_key()
    if not api_key:
        print("[elevenlabs] ELEVENLABS_API_KEY is not set; skipping TTS")
        return False

    try:
        import requests
    except ImportError:
        print("[elevenlabs] requests package is not installed; skipping TTS")
        return False

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "text": sentence,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            # Slightly higher stability than the default 0.5 — clearer on 8 kHz
            # phone audio without switching to a flash/turbo model.
            "stability": 0.65,
            "similarity_boost": 0.75,
            "use_speaker_boost": True,
        }
    }

    try:
        response = requests.post(
            TTS_URL,
            params={"output_format": OUTPUT_FORMAT},
            json=payload,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"[elevenlabs] failed to generate speech: {e}")
        return False


def get_call_audio(sentence, output_path):
    """
    Person B calls this instead of text_to_speech() directly.

    Tries ElevenLabs first. Returns a dict telling the backend exactly what happened,
    so it always knows what to do next — never a silent failure that could kill a call.

    Returns:
        {"success": True, "audio_path": output_path}
            → ElevenLabs worked. Use this audio file for the Twilio call.
        {"success": False, "fallback_text": sentence}
            → ElevenLabs failed. Pass `sentence` directly to Twilio's own
              <Say> verb instead — Twilio will read it aloud itself, in a
              worse voice, but the call still happens.
    """
    success = text_to_speech(sentence, output_path)
    if success:
        return {"success": True, "audio_path": output_path}
    else:
        return {"success": False, "fallback_text": sentence}
