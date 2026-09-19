from dotenv import load_dotenv
import os
import requests

load_dotenv()

ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
VOICE_ID = "XoUkt2bf6DlvSzRmvA8X"  # Victoria

TTS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"


def text_to_speech(sentence, output_path):
    """
    Turns a sentence into an audio file, saved at output_path (e.g. "demo/weekly_call.mp3").
    Returns True on success, False on failure.
    """
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": sentence,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    try:
        response = requests.post(TTS_URL, json=payload, headers=headers, timeout=15)
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
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
VOICE_ID = "XoUkt2bf6DlvSzRmvA8X"  # Victoria

TTS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"


def text_to_speech(sentence, output_path):
    """
    Turns a sentence into an audio file, saved at output_path (e.g. "demo/weekly_call.mp3").
    Returns True on success, False on failure — caller falls back to Twilio's own
    text-to-speech if this fails, per the guide's backup plan.
    """
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": sentence,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    try:
        response = requests.post(TTS_URL, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"[elevenlabs] failed to generate speech: {e}")
        return False