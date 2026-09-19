from ai.nemotron import ask_nemotron_json

SYSTEM_PROMPT = """You are an expense categorizer for a budgeting app. You read messy, \
spoken-style text describing a purchase and return structured data. You never talk to \
the user directly — you only return JSON.

Respond with ONLY a JSON object, no markdown fences, no commentary. The object must have \
exactly these fields:

{
  "merchant": string or null,
  "amount_cents": integer or null,
  "category": one of "Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other",
  "confidence": float from 0 to 1,
  "needs_review": boolean
}

Rules:
- Amounts are always whole cents as an integer. "Fourteen bucks" is 1400. "Twelve oh one" is 1201.
- If no amount is stated or is genuinely ambiguous, set amount_cents to null and confidence low.
- If two separate purchases are mentioned in one message, only categorize the first one and \
lower your confidence — don't try to split them yourself.
- category must be exactly one of the six listed. Never invent a new one.
- needs_review must be true whenever confidence is below 0.6, or amount_cents is null.
- Never guess a plausible-sounding amount you're not confident about. Getting the amount \
wrong is worse than admitting you don't know, because it decides whether a phone call fires.
- Do not think out loud, do not explain your reasoning, do not show your work. Output the \
JSON object and nothing else, immediately.
"""


def categorize_expense(raw_text):
    """
    Takes raw text (from Whisper transcription or receipt OCR) and returns a dict
    matching the expense shape from CONTRACT.md, or a flagged fallback if Nemotron
    fails to produce something usable.
    """
    result = ask_nemotron_json(
        system_prompt=SYSTEM_PROMPT,
        user_message=raw_text,
        max_tokens=600
    )

    if result is None:
        # Nemotron failed twice — never crash the server, flag it instead.
        # nemotron_failed lets the backend fall back to the heuristic parser
        # instead of treating this as a successful "I don't know the amount".
        return {
            "original_text": raw_text,
            "merchant": None,
            "amount_cents": None,
            "category": "Other",
            "confidence": 0.0,
            "needs_review": True,
            "nemotron_failed": True,
        }

    # defend against a malformed-but-parseable response (missing keys, wrong types)
    category = result.get("category")
    valid_categories = {"Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other"}
    if category not in valid_categories:
        category = "Other"

    return {
        "original_text": raw_text,
        "merchant": result.get("merchant"),
        "amount_cents": result.get("amount_cents"),
        "category": category,
        "confidence": result.get("confidence", 0.0),
        "needs_review": result.get("needs_review", True),
        "nemotron_failed": False,
    }