"""Spoken US-dollar English for outbound phone TTS.

The app stores every amount as integer cents in one ledger currency (USD).
Receipt history may still show printed codes like ``CHF 54.50`` — those are
UI-only. Call scripts must always say dollars and cents, never currency
symbols, ISO codes, or raw cent integers that TTS will read as the wrong unit.
"""

from __future__ import annotations

import re

_ONES = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)
_SCALES = (
    (1_000_000_000, "billion"),
    (1_000_000, "million"),
    (1_000, "thousand"),
)

# $185.50 / €36.33 / £10 / CHF 54.50 / 54.50 CHF / USD 185.50
_CURRENCY_CODES = "CHF|USD|EUR|GBP|CAD|AUD|NZD|JPY|SEK|NOK|DKK|PLN"
_AMOUNT = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONEY_RE = re.compile(
    rf"""
    (?:
        (?P<sym>[$€£])\s*(?P<sym_amount>{_AMOUNT})
        |
        \b(?P<code_first>{_CURRENCY_CODES})\s*(?P<code_amount>{_AMOUNT})
        |
        (?P<after_amount>{_AMOUNT})\s*(?P<code_after>{_CURRENCY_CODES})\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_BARE_CODE_RE = re.compile(rf"\b(?:{_CURRENCY_CODES})\b", re.IGNORECASE)
_SYMBOL_RE = re.compile(r"[$€£]")
_SPACE_RE = re.compile(r" {2,}")


def integer_to_words(value: int) -> str:
    """American English cardinal words. 185 → 'one hundred eighty-five'."""
    number = int(value)
    if number < 0:
        return f"negative {integer_to_words(-number)}"
    if number < 20:
        return _ONES[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        if ones == 0:
            return _TENS[tens]
        return f"{_TENS[tens]}-{_ONES[ones]}"
    if number < 1000:
        hundreds, rest = divmod(number, 100)
        if rest == 0:
            return f"{_ONES[hundreds]} hundred"
        return f"{_ONES[hundreds]} hundred {integer_to_words(rest)}"
    for scale, name in _SCALES:
        if number >= scale:
            count, rest = divmod(number, scale)
            head = f"{integer_to_words(count)} {name}"
            if rest == 0:
                return head
            return f"{head} {integer_to_words(rest)}"
    return str(number)


def cents_to_speech(cents: int) -> str:
    """Integer cents → spoken USD. 18550 → 'one hundred eighty-five dollars and fifty cents'."""
    total = abs(int(cents))
    dollars, remainder = divmod(total, 100)
    if dollars == 0:
        if remainder == 0:
            return "zero dollars"
        unit = "cent" if remainder == 1 else "cents"
        return f"{integer_to_words(remainder)} {unit}"
    dollar_unit = "dollar" if dollars == 1 else "dollars"
    if remainder == 0:
        return f"{integer_to_words(dollars)} {dollar_unit}"
    cent_unit = "cent" if remainder == 1 else "cents"
    return (
        f"{integer_to_words(dollars)} {dollar_unit} and "
        f"{integer_to_words(remainder)} {cent_unit}"
    )


def _parse_major_to_cents(raw: str) -> int | None:
    """Parse 185.50 / 1,855.00 / 54,50 into integer cents."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            normalized = cleaned.replace(".", "").replace(",", ".")
        else:
            normalized = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2 and parts[0].replace(" ", "").isdigit():
            normalized = f"{parts[0]}.{parts[1]}"
        else:
            normalized = cleaned.replace(",", "")
    else:
        normalized = cleaned
    try:
        major = float(normalized)
    except ValueError:
        return None
    if major < 0:
        return None
    return int(round(major * 100))


def rewrite_money_for_speech(text: str) -> str:
    """Replace ``$`` / ``CHF`` / ``€`` money fragments with spoken USD words.

    History lines like ``Berghotel Grosse Scheidegg · CHF 54.50`` become
    ``Berghotel Grosse Scheidegg · fifty-four dollars and fifty cents`` so TTS
    never spells C-H-F or mixes francs into a dollars script.
    """
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        amount = (
            match.group("sym_amount")
            or match.group("code_amount")
            or match.group("after_amount")
        )
        cents = _parse_major_to_cents(amount or "")
        if cents is None:
            return match.group(0)
        return cents_to_speech(cents)

    rewritten = _MONEY_RE.sub(_replace, text)
    rewritten = _BARE_CODE_RE.sub("", rewritten)
    rewritten = _SYMBOL_RE.sub("", rewritten)
    rewritten = _SPACE_RE.sub(" ", rewritten)
    return rewritten.replace(" · ", " ").replace("·", " ").strip()
