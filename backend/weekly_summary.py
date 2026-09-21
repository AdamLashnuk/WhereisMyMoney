"""Spoken weekly-summary lines for outbound Twilio TTS.

Lists this week's expenses as natural US-dollar English, e.g.
``Spent one dollar on Celsius, thirteen dollars on Walmart, and five hundred
dollars on AWS credits.``

Caps the list at ``WEEKLY_SUMMARY_MAX_ITEMS`` so the call stays demo-length.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.money_speech import cents_to_speech, integer_to_words, rewrite_money_for_speech  # noqa: E402

# Keep the phone script short. List every expense when the week is small;
# otherwise the top N by amount plus "and X more".
WEEKLY_SUMMARY_MAX_ITEMS = 6

_ACRONYMS = {
    "AWS",
    "API",
    "IBM",
    "HBO",
    "NBC",
    "CVS",
    "ATM",
    "USB",
    "VPN",
    "AI",
    "TTS",
    "GPS",
    "TV",
    "NYC",
}
_SPACE_RE = re.compile(r"\s+")
_EDGE_PUNCT_RE = re.compile(r"^[\s.,;:!?\-–—]+|[\s.,;:!?\-–—]+$")


def _cents(expense: dict[str, Any]) -> int:
    raw = expense.get("amountCents", expense.get("amount_cents", 0))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def merchant_for_speech(
    raw: str | None,
    *,
    category: str | None = None,
) -> str:
    """Light cleanup so TTS says a recognizable shop name, not a dump of symbols."""
    name = _EDGE_PUNCT_RE.sub("", _SPACE_RE.sub(" ", (raw or "").strip()))
    name = name.replace("$", "").replace("€", "").replace("£", "")
    name = _SPACE_RE.sub(" ", name).strip()
    if not name:
        if category and category.strip() and category.strip().lower() != "other":
            return category.strip()
        return "other spending"

    words: list[str] = []
    for word in name.split():
        core = word.strip(".,")
        letters = re.sub(r"[^A-Za-z]", "", core)
        if letters.upper() in _ACRONYMS:
            rebuilt = re.sub(r"[A-Za-z]+", letters.upper(), core, count=1)
            words.append(rebuilt if rebuilt else letters.upper())
            continue
        if core.isupper() or core.islower():
            words.append(core[:1].upper() + core[1:].lower() if len(core) > 1 else core.upper())
        else:
            words.append(core)
    cleaned = " ".join(w for w in words if w) or "other spending"
    return rewrite_money_for_speech(cleaned) or cleaned


def join_spoken_list(parts: list[str]) -> str:
    """Oxford-comma list with ``and`` before the last item."""
    items = [p.strip() for p in parts if p and str(p).strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _expense_clause(expense: dict[str, Any]) -> str | None:
    cents = _cents(expense)
    if cents <= 0:
        return None
    merchant = merchant_for_speech(
        expense.get("merchant"),
        category=expense.get("category"),
    )
    return f"{cents_to_speech(cents)} on {merchant}"


def select_expenses_for_speech(
    expenses: list[dict[str, Any]] | None,
    *,
    limit: int = WEEKLY_SUMMARY_MAX_ITEMS,
) -> tuple[list[dict[str, Any]], int]:
    """Return ``(items_to_speak, omitted_count)``.

    Few expenses: keep caller order (typically this week's ledger).
    Many: top ``limit`` by amount, leftover becomes the ``and X more`` count.
    """
    cap = max(1, int(limit))
    usable = [e for e in (expenses or []) if _cents(e) > 0]
    if len(usable) <= cap:
        return usable, 0
    ranked = sorted(usable, key=_cents, reverse=True)
    return ranked[:cap], len(usable) - cap


def expenses_spent_sentence(
    expenses: list[dict[str, Any]] | None,
    *,
    limit: int = WEEKLY_SUMMARY_MAX_ITEMS,
) -> str:
    """``Spent … on …, …, and …`` plus optional ``and X more.``"""
    chosen, omitted = select_expenses_for_speech(expenses, limit=limit)
    clauses = [c for c in (_expense_clause(e) for e in chosen) if c]
    if not clauses:
        return ""
    body = join_spoken_list(clauses)
    sentence = f"Spent {body}."
    if omitted > 0:
        more = "one more" if omitted == 1 else f"{integer_to_words(omitted)} more"
        sentence = sentence[:-1] + f", and {more}."
    return rewrite_money_for_speech(sentence)
