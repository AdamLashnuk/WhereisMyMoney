from ai.nemotron import ask_nemotron_json

result = ask_nemotron_json(
    system_prompt="Respond only with JSON. No commentary, no markdown fences.",
    user_message='Return this exact JSON: {"status": "ok", "number": 42}'
)
print(result)