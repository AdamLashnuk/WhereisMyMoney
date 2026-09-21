"""Expense parser.

Temporary heuristic implementation of ``parse_expense(text)``. Person C will
swap the body for NVIDIA Nemotron later — see the swap interface below.
``main.py`` only depends on ``ParsedExpense`` and ``parse_expense``.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from db import CATEGORIES

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

Category = str

# ---------------------------------------------------------------------------
# SWAP INTERFACE (Person C / NVIDIA Nemotron)
# ---------------------------------------------------------------------------
# ``parse_expense(text) -> ParsedExpense`` is the single-item text parse.
# ``parse_expenses(text) -> list[ParsedExpense]`` splits a spoken list into
# N ≥ 1 items (voice /log-expense). When NVIDIA_API_KEY is set, that path
# prefers ai.categorize.categorize_expenses; otherwise a heuristic splits on
# "and" / commas / repeated money patterns. parse_expense still uses
# categorize_expense for one fragment. On missing key / Nemotron failure it
# uses the heuristic below so the demo still works offline.
# Receipt **images** use ``parse_receipt_image`` → ai.receipt.categorize_receipt
# and never invent cents via the heuristic.
#
# Required fields on ParsedExpense:
#   original_text  str        unmodified input; persist forever (CONTRACT)
#   merchant       str | None
#   amount_cents   int        whole cents, never a float
#   category       one of Food, Transport, Subscriptions, Shopping, Bills, Other
#   confidence     float      0.0–1.0
#   needs_review   bool       True when the model is unsure
# ---------------------------------------------------------------------------

_ONES = {
    "zero": 0,
    "oh": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_NUMBER_WORDS = set(_ONES) | set(_TENS) | {"hundred"}

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Food": (
        "lunch",
        "dinner",
        "breakfast",
        "brunch",
        "grocery",
        "groceries",
        "coffee",
        "food",
        "pizza",
        "burger",
        "restaurant",
        "cafe",
        "snack",
        "drink",
        "drinks",
        "meal",
        "takeout",
        "doordash",
        "uber eats",
        "chipotle",
        "starbucks",
    ),
    "Transport": (
        "bus",
        "uber",
        "lyft",
        "gas",
        "fuel",
        "taxi",
        "train",
        "metro",
        "subway",
        "parking",
        "fare",
        "flight",
        "lyft",
        "transit",
    ),
    "Subscriptions": (
        "netflix",
        "spotify",
        "hulu",
        "disney",
        "subscription",
        "prime",
        "youtube",
        "apple music",
        "icloud",
        "membership",
    ),
    "Shopping": (
        "amazon",
        "clothes",
        "clothing",
        "shopping",
        "store",
        "mall",
        "target",
        "walmart",
        "shoes",
        "shirt",
    ),
    "Bills": (
        "rent",
        "bill",
        "electric",
        "electricity",
        "utility",
        "utilities",
        "internet",
        "insurance",
        "water",
        "phone bill",
    ),
}

_CURRENCY_RE = re.compile(
    r"(?:\$\s*)(\d{1,6}(?:\.\d{1,2})?)"
    r"|(\d{1,6}\.\d{2})"
    r"|(?:total|amount|tender|balance)\s*:?\s*\$?\s*(\d{1,6}(?:\.\d{1,2})?)"
    r"|(\d{1,6})\s*(?:dollars?|bucks|usd)",
    re.IGNORECASE,
)

_PREPOSITION_RE = re.compile(
    r"\b(?:at|from|for(?:\s+the)?|on)\s+([a-z0-9][a-z0-9'&.\- ]{1,40})$",
    re.IGNORECASE,
)


class UnknownAmountError(ValueError):
    """Nemotron parsed the text but did not produce an amount in cents.

    ``log-expense`` maps this to HTTP 400 so we never persist a guessed amount.
    """


@dataclass
class ParsedExpense:
    original_text: str
    merchant: str | None
    amount_cents: int
    category: str
    confidence: float
    needs_review: bool
    engine: str = "heuristic"

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_tokens(text: str) -> list[str]:
    cleaned = text.lower().replace("-", " ").replace("$", " ")
    cleaned = re.sub(r"[^a-z0-9.\s]", " ", cleaned)
    return [t for t in cleaned.split() if t]


def _combine_number_words(tokens: list[str]) -> list[int]:
    """Turn spoken number tokens into integer groups (14, 32, 45, …)."""
    groups: list[int] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok not in _NUMBER_WORDS and not tok.isdigit():
            i += 1
            continue
        if tok.isdigit():
            groups.append(int(tok))
            i += 1
            continue
        value = 0
        if tok in _TENS:
            value = _TENS[tok]
            if i + 1 < len(tokens) and tokens[i + 1] in _ONES and _ONES[tokens[i + 1]] < 10:
                value += _ONES[tokens[i + 1]]
                i += 1
        elif tok in _ONES:
            value = _ONES[tok]
        elif tok == "hundred":
            i += 1
            continue
        if i + 1 < len(tokens) and tokens[i + 1] == "hundred":
            value *= 100
            i += 1
            extra = 0
            if i + 1 < len(tokens) and tokens[i + 1] in _TENS:
                extra = _TENS[tokens[i + 1]]
                i += 1
                if i + 1 < len(tokens) and tokens[i + 1] in _ONES and _ONES[tokens[i + 1]] < 10:
                    extra += _ONES[tokens[i + 1]]
                    i += 1
            elif i + 1 < len(tokens) and tokens[i + 1] in _ONES:
                extra = _ONES[tokens[i + 1]]
                i += 1
            value += extra
        groups.append(value)
        i += 1
    return groups


def _amount_from_words(text: str) -> int | None:
    tokens = _normalize_tokens(text)
    groups = _combine_number_words(tokens)
    if not groups:
        return None
    joined = " ".join(tokens)
    has_money_word = bool(re.search(r"\b(dollars?|bucks|usd|cents?)\b", joined))
    # "fourteen bucks" / single spoken dollar amount
    if len(groups) == 1:
        if has_money_word or any(k in joined for k in ("spent", "paid", "cost", "total")):
            return groups[0] * 100
        # still accept a lone number word as dollars — mark review later
        return groups[0] * 100
    # "two fifty" → $2.50 ; "thirty two forty five" → $32.45
    dollars, cents = groups[0], groups[1]
    if 0 <= cents <= 99:
        return dollars * 100 + cents
    return dollars * 100


def extract_amount_cents(text: str) -> int | None:
    match = _CURRENCY_RE.search(text)
    if match:
        raw = next(g for g in match.groups() if g is not None)
        try:
            dollars = float(raw)
        except ValueError:
            dollars = None
        if dollars is not None:
            return int(round(dollars * 100))
    return _amount_from_words(text)


def guess_category(text: str) -> tuple[str, float]:
    lowered = text.lower()
    hits: list[tuple[str, str]] = []
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                hits.append((category, keyword))
                break
    if len(hits) == 1:
        return hits[0][0], 0.86
    if len(hits) > 1:
        return hits[0][0], 0.55
    return "Other", 0.4


def guess_merchant(text: str) -> str | None:
    match = _PREPOSITION_RE.search(text.strip())
    if not match:
        return None
    raw = match.group(1).strip(" .,!?;:")
    # Drop trailing category-only words that aren't a store name
    raw = re.sub(r"\b(today|yesterday|this week)\b", "", raw, flags=re.I).strip()
    if not raw or len(raw) > 40:
        return None
    return raw.title()


def _nemotron_available() -> bool:
    key = os.getenv("NVIDIA_API_KEY")
    return bool(key and str(key).strip())


def _coerce_cents(value) -> int | None:
    """Integer cents only. Dollar strings like ``"$14"`` / ``"14.00"`` become cents."""
    try:
        from ai.receipt import coerce_amount_cents
    except Exception:
        coerce_amount_cents = None
    if coerce_amount_cents is not None:
        return coerce_amount_cents(value)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    return None


def _from_nemotron_dict(original: str, data: dict, *, engine: str = "nemotron") -> ParsedExpense:
    amount_cents = _coerce_cents(data.get("amount_cents"))
    if amount_cents is None:
        kind = "receipt" if engine == "nemotron-vision" else "text"
        raise UnknownAmountError(
            f"Could not determine an amount in cents from the {kind}. "
            "Please include a dollar amount and try again."
        )

    category = data.get("category")
    if category not in CATEGORIES:
        category = "Other"

    merchant = data.get("merchant")
    if merchant is not None:
        merchant = str(merchant).strip() or None

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    needs_review = bool(data.get("needs_review", True))
    if amount_cents < 0:
        raise UnknownAmountError("Amount in cents must be zero or greater.")

    return ParsedExpense(
        original_text=original,
        merchant=merchant,
        amount_cents=int(amount_cents),
        category=category,
        confidence=confidence,
        needs_review=needs_review,
        engine=engine,
    )


def parse_receipt_image(image_path: str, *, original_text: str | None = None) -> ParsedExpense:
    """Map Person C's vision dict onto ParsedExpense.

    Images never fall back to the text heuristic — a null ``amount_cents``
    becomes ``UnknownAmountError`` (HTTP 400) so we do not invent cents.
    """
    try:
        from ai.receipt import categorize_receipt
    except Exception as exc:
        raise UnknownAmountError(
            "Could not determine an amount in cents from the receipt. "
            "Please include a dollar amount and try again."
        ) from exc

    try:
        data = categorize_receipt(image_path)
    except Exception as exc:
        raise UnknownAmountError(
            "Could not determine an amount in cents from the receipt. "
            "Please include a dollar amount and try again."
        ) from exc

    if not isinstance(data, dict):
        raise UnknownAmountError(
            "Could not determine an amount in cents from the receipt. "
            "Please include a dollar amount and try again."
        )

    label = Path(image_path).name if image_path else "receipt"
    original = original_text if original_text is not None else data.get("original_text")
    if not original:
        original = f"[receipt photo: {label}]"

    return _from_nemotron_dict(str(original), data, engine="nemotron-vision")


def _try_nemotron_parse(original: str) -> ParsedExpense | None:
    """Return a ParsedExpense from Nemotron, or None to use the heuristic.

    Raises UnknownAmountError when Nemotron succeeded but amount_cents is null
    so we never invent cents.
    """
    try:
        from ai.categorize import categorize_expense
    except Exception:
        return None

    try:
        data = categorize_expense(original)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    if data.get("nemotron_failed"):
        return None

    return _from_nemotron_dict(original, data)


def parse_expense(text: str) -> ParsedExpense:
    """Parse spoken/receipt text into a ParsedExpense.

    Uses Person C's Nemotron categorizer when ``NVIDIA_API_KEY`` is set.
    Falls back to the heuristic below if the key is missing or Nemotron fails.
    """
    original = text if text is not None else ""
    if _nemotron_available():
        nemotron = _try_nemotron_parse(original)
        if nemotron is not None:
            return nemotron
    return _heuristic_parse_expense(original)


_NUMBER_WORD_ALT = (
    "zero|oh|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    "thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand"
)
_MONEY_START_RE = re.compile(
    r"(?:\$\s*\d{1,6}(?:\.\d{1,2})?)"
    r"|(?:\d{1,6}(?:\.\d{1,2})?\s*(?:dollars?|bucks|usd|cents?))"
    rf"|(?:\b(?:{_NUMBER_WORD_ALT})(?:\s+(?:{_NUMBER_WORD_ALT}))*\s*(?:dollars?|bucks|usd|cents?))"
    rf"|(?:\b(?:{_NUMBER_WORD_ALT})(?:\s+(?:{_NUMBER_WORD_ALT}))*(?=\s+(?:on|for|at|from)\b))"
    r"|(?:\b\d{1,6}(?:\.\d{1,2})?(?=\s+(?:on|for|at|from)\b))",
    re.IGNORECASE,
)


def _protect_number_and(text: str) -> str:
    """Keep 'hundred and fifty' / 'dollars and fifty cents' as one amount."""
    out = re.sub(r"\b(hundred|thousand)\s+and\s+", r"\1 ", text, flags=re.I)
    out = re.sub(
        r"\b(dollars?|bucks|usd)\s+and\s+"
        rf"((?:\d{{1,2}}|{_NUMBER_WORD_ALT})(?:\s+{_NUMBER_WORD_ALT})*)\s+cents?\b",
        r"\1 \2 cents",
        out,
        flags=re.I,
    )
    return out


def _has_positive_amount(text: str) -> bool:
    amount = extract_amount_cents(text)
    return amount is not None and amount > 0


def _merge_amount_parts(parts: list[str]) -> list[str]:
    """Keep parts with amounts; glue amount-less fragments onto neighbors."""
    merged: list[str] = []
    pending: list[str] = []
    for part in parts:
        if _has_positive_amount(part):
            prefix = " ".join(pending)
            merged.append(f"{prefix} {part}".strip() if prefix else part)
            pending = []
        else:
            pending.append(part)
    if pending and merged:
        merged[-1] = f"{merged[-1]} {' '.join(pending)}".strip()
    elif pending:
        merged.append(" ".join(pending))
    return merged


def _split_on_money_spans(text: str) -> list[str]:
    """Split when two or more money patterns appear in one take."""
    matches = [m for m in _MONEY_START_RE.finditer(text) if m.group().strip()]
    filtered: list[re.Match[str]] = []
    for match in matches:
        if filtered and re.search(r"cents?$", match.group(), re.I):
            continue
        filtered.append(match)
    if len(filtered) < 2:
        return [text.strip()] if text.strip() else []

    chunks: list[str] = []
    for i, match in enumerate(filtered):
        end = filtered[i + 1].start() if i + 1 < len(filtered) else len(text)
        chunk = text[match.start() : end].strip(" .,;:")
        if chunk:
            chunks.append(chunk)
    preamble = text[: filtered[0].start()].strip()
    if preamble and chunks:
        chunks[0] = f"{preamble} {chunks[0]}".strip()
    usable = [c for c in chunks if _has_positive_amount(c)]
    return usable if len(usable) >= 2 else [text.strip()]


def split_expense_utterance(text: str) -> list[str]:
    """Split spoken text into fragments that each look like one expense.

    Prefers ``and`` / commas; falls back to repeated money patterns. Number
    constructions like ``a hundred and fifty`` are not split.
    """
    original = (text or "").strip()
    if not original:
        return []

    protected = _protect_number_and(original)
    parts = [
        re.sub(r"^(?:and\s+)", "", p.strip(" .,;:"), flags=re.I).strip(" .,;:")
        for p in re.split(r"\s+and\s+|,\s*", protected, flags=re.I)
        if p.strip(" .,;:")
    ]
    parts = [p for p in parts if p]
    if len(parts) >= 2:
        merged = _merge_amount_parts(parts)
        if sum(1 for part in merged if _has_positive_amount(part)) >= 2:
            return merged

    spanned = _split_on_money_spans(protected)
    if len(spanned) >= 2:
        return spanned
    return [original]


def _try_nemotron_parse_list(original: str) -> list[ParsedExpense] | None:
    """Return a list from Nemotron, or None to use the heuristic splitter.

    An empty list means the model ran but found no amounts — caller may still
    try the heuristic. ``None`` means the API/import failed.
    """
    try:
        from ai.categorize import categorize_expenses
    except Exception:
        return None

    try:
        data = categorize_expenses(original)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    if data.get("nemotron_failed"):
        return None

    items = data.get("expenses")
    if not isinstance(items, list):
        return None

    parsed: list[ParsedExpense] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        fragment = (
            item.get("original_text")
            or item.get("original")
            or item.get("fragment")
            or original
        )
        try:
            parsed.append(_from_nemotron_dict(str(fragment), item, engine="nemotron"))
        except UnknownAmountError:
            continue
    return parsed


def parse_expenses(text: str) -> list[ParsedExpense]:
    """Parse spoken text into N ≥ 1 expenses.

    Prefers Nemotron list extraction when ``NVIDIA_API_KEY`` is set. Falls back
    to splitting on ``and`` / commas / repeated money, then ``parse_expense``
    per fragment (which may still use single-item Nemotron). Raises
    ``UnknownAmountError`` when nothing with a positive amount can be parsed.
    """
    original = text if text is not None else ""
    if not str(original).strip():
        raise UnknownAmountError(
            "Could not determine an amount in cents from the text. "
            "Please include a dollar amount and try again."
        )

    if _nemotron_available():
        items = _try_nemotron_parse_list(original)
        if items:
            return items

    fragments = split_expense_utterance(original)
    parsed: list[ParsedExpense] = []
    for fragment in fragments or [original]:
        item = parse_expense(fragment)
        if item.amount_cents > 0:
            parsed.append(item)
    if not parsed:
        raise UnknownAmountError(
            "Could not determine an amount in cents from the text. "
            "Please include a dollar amount and try again."
        )
    return parsed


def _heuristic_parse_expense(text: str) -> ParsedExpense:
    """Keyword / spoken-number heuristic used when Nemotron is unavailable."""
    original = text if text is not None else ""
    cleaned = original.strip()
    if not cleaned:
        return ParsedExpense(
            original_text=original,
            merchant=None,
            amount_cents=0,
            category="Other",
            confidence=0.1,
            needs_review=True,
        )

    amount = extract_amount_cents(cleaned)
    category, cat_conf = guess_category(cleaned)
    merchant = guess_merchant(cleaned)

    if amount is None:
        amount_cents = 0
        amount_conf = 0.2
        needs_review = True
    else:
        amount_cents = int(amount)
        amount_conf = 0.9
        needs_review = amount_cents <= 0

    confidence = round(min(amount_conf, cat_conf), 2)
    if category == "Other":
        needs_review = True
        confidence = min(confidence, 0.5)
    if os.getenv("NVIDIA_API_KEY") and confidence < 0.7:
        # Hint that a Nemotron swap would help; still return the heuristic result.
        needs_review = True

    return ParsedExpense(
        original_text=original,
        merchant=merchant,
        amount_cents=amount_cents,
        category=category if category in CATEGORIES else "Other",
        confidence=confidence,
        needs_review=needs_review,
        engine="heuristic",
    )
