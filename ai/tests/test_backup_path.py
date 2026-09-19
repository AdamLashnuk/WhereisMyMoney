from ai.elevenlabs_tts import get_call_audio

# Normal case — should succeed
result = get_call_audio(
    "This is your Food spending alert. You've gone five cents over your limit.",
    "backup_test_success.mp3"
)
print("Normal case:", result)

# Simulated failure — temporarily break the API key to prove the fallback works
import ai.elevenlabs_tts as tts_module
original_url = tts_module.TTS_URL
tts_module.TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/invalid-voice-id"

result = get_call_audio(
    "This is your Food spending alert. You've gone five cents over your limit.",
    "backup_test_failure.mp3"
)
print("Simulated failure case:", result)

tts_module.TTS_URL = original_url  # restore it