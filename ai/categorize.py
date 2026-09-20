from ai.nemotron import ask_nemotron_json
from ai.receipt import coerce_amount_cents

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


VALID_CATEGORIES = {"Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other"}

LIST_SYSTEM_PROMPT = """You are an expense categorizer for a budgeting app. You read messy, \
spoken-style text that may list one or more purchases and return structured data. You never \
talk to the user directly — you only return JSON.

Respond with ONLY a JSON object, no markdown fences, no commentary. The object must have \
exactly this shape:

{
  "expenses": [
    {
      "original_text": string (the fragment describing this one purchase),
      "merchant": string or null,
      "amount_cents": integer or null,
      "category": one of "Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other",
      "confidence": float from 0 to 1,
      "needs_review": boolean
    }
  ]
}

Rules:
- Amounts are always whole cents as an integer. "Fourteen bucks" is 1400. "Twelve dollars" is 1200. "Five hundred" is 50000.
- Split the utterance into separate purchases when the speaker lists multiple spends (and, commas, or repeated money amounts). "Twelve dollars on drinks and five hundred on groceries" is TWO expenses.
- A longer list is fine — one object per spend, in spoken order, until they stop.
- If only one purchase is mentioned, return a one-element array.
- If no amount is stated or is genuinely ambiguous for an item, set that item's amount_cents to null and confidence low. Omit items you cannot parse at all.
- If the whole utterance has no usable amounts, return {"expenses": []}.
- category must be exactly one of the six listed. Never invent a new one.
- needs_review must be true whenever confidence is below 0.6, or amount_cents is null.
- Never guess a plausible-sounding amount you're not confident about. Getting the amount \
wrong is worse than admitting you don't know, because it decides whether a phone call fires.
- Do not think out loud, do not explain your reasoning, do not show your work. Output the \
JSON object and nothing else, immediately.
"""


def _normalize_item(raw_text, item):
    """Coerce one model item onto the expense dict shape."""
    if not isinstance(item, dict):
        return None
    category = item.get("category")
    if category not in VALID_CATEGORIES:
        category = "Other"
    amount_cents = coerce_amount_cents(item.get("amount_cents"))
    fragment = item.get("original_text") or item.get("original") or item.get("fragment") or raw_text
    return {
        "original_text": str(fragment),
        "merchant": item.get("merchant"),
        "amount_cents": amount_cents,
        "category": category,
        "confidence": item.get("confidence", 0.0),
        "needs_review": item.get("needs_review", True) if amount_cents is not None else True,
        "nemotron_failed": False,
    }


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
        # Nemotron failed — never crash the server, flag it instead.
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

    item = _normalize_item(raw_text, result)
    if item is None:
        return {
            "original_text": raw_text,
            "merchant": None,
            "amount_cents": None,
            "category": "Other",
            "confidence": 0.0,
            "needs_review": True,
            "nemotron_failed": True,
        }
    return item


def categorize_expenses(raw_text):
    """Split spoken text into N ≥ 0 expense dicts via Nemotron.

    Returns ``{"expenses": [...], "nemotron_failed": bool}``. On API/parse
    failure ``nemotron_failed`` is True so the backend can use the heuristic
    list splitter instead of treating this as "no amounts found".
    """
    result = ask_nemotron_json(
        system_prompt=LIST_SYSTEM_PROMPT,
        user_message=raw_text,
        max_tokens=1200,
    )

    if result is None:
        return {"expenses": [], "nemotron_failed": True}

    raw_items = None
    if isinstance(result, list):
        raw_items = result
    elif isinstance(result, dict):
        maybe = result.get("expenses")
        if maybe is None:
            maybe = result.get("items")
        if isinstance(maybe, list):
            raw_items = maybe
        elif "amount_cents" in result or "category" in result:
            raw_items = [result]

    if raw_items is None:
        return {"expenses": [], "nemotron_failed": True}

    expenses = []
    for item in raw_items:
        normalized = _normalize_item(raw_text, item)
        if normalized is not None:
            expenses.append(normalized)
    return {"expenses": expenses, "nemotron_failed": False}