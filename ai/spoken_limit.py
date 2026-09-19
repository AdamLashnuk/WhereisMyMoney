from ai.nemotron import ask_nemotron_json

SYSTEM_PROMPT = """You read a spoken sentence where someone sets a spending limit for a \
budgeting app, and return structured data. You never talk to the user — only return JSON.

Respond with ONLY a JSON object, no markdown fences, no commentary:

{
  "category": one of "Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other", or null,
  "amount_cents": integer or null,
  "period": "weekly" (this app only supports weekly limits right now),
  "confidence": float from 0 to 1
}

Rules:
- Amounts are always whole cents as an integer. "A hundred a week" is 10000.
- category must be exactly one of the six listed, or null if it's genuinely unclear which \
category they mean.
- If the sentence doesn't clearly state both a category and an amount, set the missing \
field to null and lower confidence accordingly.
- Never guess an amount or category you're not confident about — the Limits screen has a \
manual entry fallback, so it's fine to return low confidence rather than a wrong guess.
- Do not think out loud, do not explain your reasoning, do not show your work. Output the \
JSON object and nothing else, immediately.
"""


def understand_spoken_limit(raw_text):
    """
    Takes raw spoken text describing a limit and returns a dict with category,
    amount_cents, period, and confidence. Falls back to a fully-null, zero-confidence
    result if Nemotron fails — the app should treat that as "ask the user to use the
    manual inputs instead," never crash.
    """
    result = ask_nemotron_json(
        system_prompt=SYSTEM_PROMPT,
        user_message=raw_text,
        max_tokens=150
    )

    if result is None:
        return {
            "category": None,
            "amount_cents": None,
            "period": "weekly",
            "confidence": 0.0
        }

    category = result.get("category")
    valid_categories = {"Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other", None}
    if category not in valid_categories:
        category = None

    return {
        "category": category,
        "amount_cents": result.get("amount_cents"),
        "period": "weekly",
        "confidence": result.get("confidence", 0.0)
    }