from ai.money_speech import cents_to_speech, rewrite_money_for_speech
from ai.nemotron import ask_nemotron_json

SYSTEM_PROMPT = """You write one short spoken sentence for a budgeting app's weekly phone \
call. You're given this week's spending by category and last week's spending by category, \
already written as spoken US dollars and cents. You find the single most notable change \
and describe it in plain, natural spoken English.

Respond with ONLY a JSON object, no markdown fences, no commentary:

{
  "sentence": string
}

Rules:
- The sentence must be under 20 words.
- It gets read aloud by a text-to-speech voice on a phone call. Write it the way a person \
would say it out loud, not the way you'd write it in a report. No hedging like "it appears" \
or "it seems." State it plainly.
- Amounts are spoken US dollars. Never treat a raw cent integer as dollars. Never say CHF, \
francs, euros, or use $ or other currency symbols.
- Pick the single category with the biggest change (by dollar amount or by being new/gone), \
not a list of everything that changed.
- If nothing notable changed, say something simple and true, like spending stayed about the \
same as last week. Never invent a pattern that isn't there.
- Do not think out loud, do not explain your reasoning, do not show your work. Output the \
JSON object and nothing else, immediately.
"""


def weekly_pattern_sentence(this_week_totals, last_week_totals):
    """
    this_week_totals and last_week_totals: dicts like
        {"Food": 8500, "Transport": 4000, "Subscriptions": 1200, "Shopping": 0, "Bills": 15000, "Other": 300}
    (amounts in cents, one key per category, 0 if nothing spent)

    Returns a plain string — the sentence to be read aloud. Falls back to a safe generic
    sentence if Nemotron fails, so a broken response never breaks the call.
    """
    this_week = {
        category: cents_to_speech(amount)
        for category, amount in this_week_totals.items()
    }
    last_week = {
        category: cents_to_speech(amount)
        for category, amount in last_week_totals.items()
    }
    user_message = (
        f"This week's spending by category (spoken US dollars): {this_week}\n"
        f"Last week's spending by category (spoken US dollars): {last_week}"
    )

    result = ask_nemotron_json(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        max_tokens=200
    )

    if result is None or not result.get("sentence"):
        return "Here's your spending summary for the week."

    return rewrite_money_for_speech(result["sentence"])