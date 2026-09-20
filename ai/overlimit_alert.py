from ai.money_speech import cents_to_speech, rewrite_money_for_speech
from ai.nemotron import ask_nemotron_json

SYSTEM_PROMPT = """You write a short spoken alert for a budgeting app. The user just went \
over a spending limit they set themselves, and the app is calling them right now to tell \
them. You write what the voice says on that call.

You will be given the category, the limit, and how far over — already written as spoken \
US dollars and cents. Do not do any math yourself. Phrase those exact spoken amounts \
naturally. Never say francs, CHF, euros, or read a currency code. Never use $ or other \
currency symbols.

Respond with ONLY a JSON object, no markdown fences, no commentary:

{
  "sentence": string
}

Rules:
- One or two sentences, under 30 words total.
- The very first thing said must make clear this is an over-limit alert call, not the \
weekly summary — someone answering the phone needs to immediately know which kind of call \
this is, from the first few words.
- Use the exact spoken US dollar amounts you were given. Do not recalculate or round them.
- Calm and factual, not alarming, not scolding, not apologetic. The tone is a friendly \
heads-up, not a warning siren. This app doesn't guilt-trip people.
- Do not think out loud, do not explain your reasoning, do not show your work. Output the \
JSON object and nothing else, immediately.
"""


def overlimit_alert_sentence(category, limit_cents, over_by_cents):
    """
    category: e.g. "Food"
    limit_cents: the limit that was set, in cents
    over_by_cents: how far over, in cents (could be as small as 1)

    All the math happens here in Python, not in the model — Nemotron only phrases
    numbers we've already computed correctly. Falls back to a safe, correct sentence
    if Nemotron fails.
    """
    limit_str = cents_to_speech(limit_cents)
    over_str = cents_to_speech(over_by_cents)

    user_message = (
        f"Category: {category}\n"
        f"Limit: {limit_str}\n"
        f"Over by: {over_str}"
    )

    result = ask_nemotron_json(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        max_tokens=150
    )

    if result is None or not result.get("sentence"):
        return (
            f"This is your spending limit alert. You've gone over your {category} "
            f"limit by {over_str}."
        )

    return rewrite_money_for_speech(result["sentence"])
