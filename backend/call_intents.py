"""Demo intent routing for Twilio ``<Gather>`` speech on outbound calls.

Keeps the loop small and reliable: acknowledge, log an expense, set a weekly
limit, or ask the callee to try again. The call stays open after every reply
until the callee hangs up. Money in spoken replies always goes through
``cents_to_speech`` / ``rewrite_money_for_speech``.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from categorizer import UnknownAmountError, extract_amount_cents, guess_category, parse_expense
from db import CATEGORIES, get_limits, insert_expense, set_limit, week_total_for_category

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.money_speech import cents_to_speech, rewrite_money_for_speech  # noqa: E402

logger = logging.getLogger("whereismymoney.gather")

PARSE_LIMIT_SAVE_CONFIDENCE = 0.6

ACK_SPEECH = "Got it."
RETRY_SPEECH = "I didn't catch that. You can try again."
EMPTY_RETRY_SPEECH = ""
ERROR_SPEECH = "Sorry, something went wrong. You can try again."

_ACK_RE = re.compile(
    r"^(?:(?:ok(?:ay)?|thanks?|thank you|got it|gotcha|yes|yeah|yep|yup|"
    r"sure|alright|all right|sounds good|cool|bye|goodbye|copy|"
    r"acknowledged|fine|that's fine|that is fine|uh huh|mm hmm|mhm)"
    r"[\s.,!]*)+$",
    re.IGNORECASE,
)
_LIMIT_CUE_RE = re.compile(
    r"\b(?:set|change|update|raise|lower|increase|decrease)\b.+\b(?:limit|budget|cap)\b"
    r"|\b(?:limit|budget)\b.+\b(?:to|at|of)\b"
    r"|\bcap\b.+\b(?:at|to|of|spending|limit|budget)\b"
    r"|\b(?:weekly\s+)?(?:limit|budget)\s+(?:for|on)\b",
    re.IGNORECASE,
)
_SPEND_RE = re.compile(
    r"\b(?:spent|spend|paid|pay|bought|buy|cost|costs|charged|purchase|purchased|"
    r"i\s+got|add(?:ed)?(?:\s+an?)?\s+expense|log(?:ged)?(?:\s+an?)?\s+expense)\b",
    re.IGNORECASE,
)
_MONEY_WORD_RE = re.compile(r"\b(?:dollars?|bucks|usd|cents?)\b", re.IGNORECASE)
_HUNDRED_RE = re.compile(r"\b(?:a|one)\s+hundred\b", re.IGNORECASE)


@dataclass(frozen=True)
class SpokenIntent:
    name: str
    speech: str
    amount_cents: int | None = None
    category: str | None = None
    parsed_expense: Any = None


@dataclass(frozen=True)
class GatherOutcome:
    intent: str
    spoken: str
    gather_again: bool


def _null_limit() -> dict[str, Any]:
    return {
        "category": None,
        "amount_cents": None,
        "period": "weekly",
        "confidence": 0.0,
    }


def parse_limit_text(text: str) -> dict[str, Any]:
    """Same result as ``POST /parse-limit``. Does not persist."""
    from ai.spoken_limit import understand_spoken_limit

    try:
        parsed = understand_spoken_limit(text)
    except Exception:
        logger.exception("spoken limit parse failed")
        parsed = _null_limit()

    if not isinstance(parsed, dict):
        parsed = _null_limit()

    category = parsed.get("category")
    if category not in CATEGORIES:
        category = None

    amount_cents = parsed.get("amount_cents")
    if isinstance(amount_cents, bool) or amount_cents is None:
        amount_cents = None
    elif isinstance(amount_cents, int):
        amount_cents = amount_cents if amount_cents >= 0 else None
    elif isinstance(amount_cents, float) and abs(amount_cents - round(amount_cents)) <= 1e-6:
        coerced = int(round(amount_cents))
        amount_cents = coerced if coerced >= 0 else None
    else:
        amount_cents = None

    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence != confidence:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    ready = (
        category is not None
        and amount_cents is not None
        and confidence >= PARSE_LIMIT_SAVE_CONFIDENCE
    )
    return {
        "category": category,
        "amount_cents": amount_cents,
        "period": "weekly",
        "confidence": confidence,
        "readyToSave": ready,
        "saveHint": (
            "POST /limits with {category, limitCents: amount_cents} when readyToSave is true. "
            "This endpoint does not persist."
        ),
    }


def _category_from_speech(text: str) -> str | None:
    lowered = text.lower()
    for category in CATEGORIES:
        if re.search(rf"\b{re.escape(category.lower())}\b", lowered):
            return category
    category, conf = guess_category(text)
    if category in CATEGORIES and conf >= 0.8:
        return category
    return None


def _limit_amount_cents(text: str) -> int | None:
    if _HUNDRED_RE.search(text or ""):
        return 10_000
    cents = extract_amount_cents(text or "")
    if cents is None or cents <= 0:
        return None
    return int(cents)


def heuristic_spoken_limit(text: str) -> dict[str, Any] | None:
    """Offline demo parser for phrases like ``set food limit to fifty``."""
    category = _category_from_speech(text)
    amount_cents = _limit_amount_cents(text)
    if not category or amount_cents is None:
        return None
    return {
        "category": category,
        "amount_cents": amount_cents,
        "period": "weekly",
        "confidence": 0.75,
    }


def looks_like_limit(text: str) -> bool:
    return bool(_LIMIT_CUE_RE.search(text or ""))


def looks_like_ack(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return bool(_ACK_RE.fullmatch(cleaned))


def looks_like_expense_text(text: str) -> bool:
    speech = text or ""
    if _SPEND_RE.search(speech):
        return True
    if _MONEY_WORD_RE.search(speech) and _category_from_speech(speech):
        return True
    return False


def classify_spoken_reply(text: str) -> SpokenIntent:
    speech = (text or "").strip()
    if not speech:
        return SpokenIntent("empty", speech)

    if looks_like_limit(speech):
        parsed = parse_limit_text(speech)
        if parsed.get("readyToSave"):
            return SpokenIntent(
                "set_limit",
                speech,
                int(parsed["amount_cents"]),
                str(parsed["category"]),
            )
        heuristic = heuristic_spoken_limit(speech)
        if heuristic:
            return SpokenIntent(
                "set_limit",
                speech,
                int(heuristic["amount_cents"]),
                str(heuristic["category"]),
            )
        return SpokenIntent("unknown", speech)

    if looks_like_ack(speech):
        return SpokenIntent("ack", speech)

    if looks_like_expense_text(speech):
        try:
            parsed_expense = parse_expense(speech)
        except UnknownAmountError:
            return SpokenIntent("unknown", speech)
        if int(parsed_expense.amount_cents) > 0:
            return SpokenIntent(
                "log_expense",
                speech,
                int(parsed_expense.amount_cents),
                parsed_expense.category,
                parsed_expense,
            )
        return SpokenIntent("unknown", speech)

    return SpokenIntent("unknown", speech)


def _over_limit_clause(category: str) -> str:
    limits = get_limits()
    limit = int(limits.get(category, 0))
    total = week_total_for_category(category)
    over_by = max(0, total - limit)
    if over_by <= 0:
        return ""
    return f" You are over your {category} limit by {cents_to_speech(over_by)}."


def _spoken(text: str) -> str:
    return rewrite_money_for_speech((text or "").strip())


def handle_spoken_reply(
    text: str,
    *,
    speech_confidence: float | None = None,
) -> GatherOutcome:
    """Interpret ``SpeechResult``, persist when needed, return a spoken reply.

    ``gather_again`` is always True — the TwiML loop keeps listening until the
    callee hangs up.
    """
    intent = classify_spoken_reply(text)
    logger.info(
        "Gather intent=%s confidence=%s speech=%r",
        intent.name,
        speech_confidence,
        intent.speech,
    )

    if intent.name == "empty":
        return GatherOutcome("empty", _spoken(EMPTY_RETRY_SPEECH), True)

    if intent.name == "set_limit" and intent.category and intent.amount_cents is not None:
        set_limit(intent.category, int(intent.amount_cents))
        spoken = (
            f"Updated your {intent.category} weekly limit to "
            f"{cents_to_speech(int(intent.amount_cents))}."
        )
        return GatherOutcome("set_limit", _spoken(spoken), True)

    if intent.name == "log_expense" and intent.parsed_expense is not None:
        parsed = intent.parsed_expense
        insert_expense(
            original_text=parsed.original_text,
            source="voice",
            merchant=parsed.merchant,
            amount_cents=int(parsed.amount_cents),
            category=parsed.category,
            confidence=parsed.confidence,
            needs_review=parsed.needs_review,
        )
        spoken = (
            f"Logged {cents_to_speech(int(parsed.amount_cents))} on {parsed.category}."
            f"{_over_limit_clause(parsed.category)}"
        )
        return GatherOutcome("log_expense", _spoken(spoken), True)

    if intent.name == "ack":
        return GatherOutcome("ack", _spoken(ACK_SPEECH), True)

    return GatherOutcome("unknown", _spoken(RETRY_SPEECH), True)
