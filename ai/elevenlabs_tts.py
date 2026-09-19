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