from ai.elevenlabs_tts import text_to_speech

success = text_to_speech(
    "This is your Food spending alert. You've gone five cents over your one hundred dollar limit.",
    "test_output.mp3"
)
print(f"Success: {success}")