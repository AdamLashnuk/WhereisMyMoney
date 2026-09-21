"""Person C — receipt photo categorization via NVIDIA vision.

Soft-loads ``NVIDIA_API_KEY`` so a missing key never crashes FastAPI boot.
Call ``categorize_receipt(image_path)``; on missing key / API failure it
returns a flagged review dict with ``amount_cents: null`` — never invents
cents and never raises.

Phone photos are downscaled to JPEG before the vision call so NVIDIA is not
sent multi-MB base64 payloads. HEIC/PNG/WebP become RGB JPEG when Pillow
(and pillow-heif, if installed) can open them.
"""

from __future__ import annotations

from dotenv import load_dotenv
import os
import json
import base64
import io
import logging
import re
import time

from ai.nemotron import _clean_json_response, nvidia_api_key

load_dotenv()

logger = logging.getLogger("whereismymoney.receipt")

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
VISION_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
DEFAULT_MAX_EDGE = 1280
DEFAULT_JPEG_QUALITY = 75
DEFAULT_VISION_RETRIES = 1
VISION_TIMEOUT_S = 40.0

_client = None
_heif_tried = False

_ISO_CURRENCY = (
    "CHF", "EUR", "USD", "GBP", "CAD", "AUD", "NZD", "JPY", "SEK", "NOK", "DKK", "PLN",
)

SYSTEM_PROMPT = """You are an expense categorizer for a budgeting app. You are shown a \
photo of a receipt and return structured data about the purchase. You never talk to the \
user — only return JSON.

Respond with ONLY a JSON object, no markdown fences, no commentary:

{
  "merchant": string or null,
  "amount_cents": integer or null,
  "currency": "CHF" or "USD" or "EUR" or "GBP" or other ISO code or null,
  "category": one of "Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other",
  "confidence": float from 0 to 1,
  "needs_review": boolean
}

Rules:
- Prefer the largest TOTAL / Summe / Grand Total / Amount Due / Balance Due near the \
bottom, AFTER the item lines. That line may be labeled TOTAL, Summe, Betrag, or show \
CHF / USD / $ / € next to the final figure (example: Total : CHF 54.50 → 5450).
- Never pick a single line-item price over the final total. Item rows like \
"1xSchweinschnitzel à 22.00 CHF 22.00" or "2xLatte 9.00" are NOT the amount.
- Ignore MwSt / VAT / tax-only lines (e.g. "Incl. 7.6% MwSt 54.50 CHF: 3.85") — the \
3.85 tax snippet is not the total. Tax is already included in TOTAL.
- Ignore FX conversions such as "Entspricht in Euro 36.33 EUR". Do not use 36.33.
- Ignore tip / Trinkgeld / gratuity unless that line is clearly the grand total.
- amount_cents is whole cents as an integer. Printed major.minor maps 1:1 onto cents \
regardless of currency: CHF 54.50 → 5450, $14.00 → 1400, 54,50 → 5450. European \
decimal comma is allowed. Never return a dollar/CHF string.
- Restaurant, cafe, hotel bar, and meal receipts are category Food.
- currency is the printed total's code (CHF, USD, EUR, …), not a converted currency.
- needs_review must be true whenever confidence is below 0.6, the image is blurry, \
or you cannot confidently locate the total.
- Never guess a plausible-sounding amount. If the total is unreadable, amount_cents \
must be null. Getting this wrong decides whether a phone call fires.
- Do not think out loud. Output the JSON object and nothing else, immediately.
"""


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(lo, min(hi, value))


def _vision_attempts() -> int:
    """API attempts. Default 1; set RECEIPT_VISION_RETRIES=2 for one parse retry."""
    return _int_env("RECEIPT_VISION_RETRIES", DEFAULT_VISION_RETRIES, 1, 3)


def _max_edge() -> int:
    return _int_env("RECEIPT_VISION_MAX_EDGE", DEFAULT_MAX_EDGE, 512, 2048)


def _jpeg_quality() -> int:
    return _int_env("RECEIPT_VISION_JPEG_QUALITY", DEFAULT_JPEG_QUALITY, 50, 90)


def infer_currency(*values) -> str | None:
    """Best-effort ISO code from model fields or amount strings. Never required."""
    for value in values:
        if not isinstance(value, str):
            continue
        raw = value.strip()
        if not raw:
            continue
        upper = raw.upper()
        if upper in _ISO_CURRENCY:
            return upper
        aliases = {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP"}
        if raw in aliases:
            return aliases[raw]
        if "€" in raw:
            return "EUR"
        if "£" in raw:
            return "GBP"
        if "$" in raw:
            return "USD"
        for code in _ISO_CURRENCY:
            if re.search(rf"\b{code}\b", upper):
                return code
    return None


def _parse_major_number(cleaned: str) -> float | None:
    """Parse 54.50 / 54,50 / 1,234.56 / 1.234,56 into major units."""
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
        return float(normalized)
    except ValueError:
        return None


def coerce_amount_cents(value) -> int | None:
    """Coerce model output to integer cents. Never invents an amount.

    Integers (and digit-only strings like ``"1400"`` / ``"5450"``) are already-cents.
    Major.minor strings (``"$14"``, ``"14.00"``, ``"CHF 54.50"``, ``"54,50"``) become
    cents. Fractional JSON numbers like ``54.50`` are major units. Booleans/garbage → None.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value < 0 or value != value:
            return None
        if abs(value - round(value)) > 1e-6:
            return int(round(value * 100))
        return int(round(value))
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    looks_like_major = bool(
        re.search(r"[$€£]", stripped)
        or re.search(r"\b(?:usd|eur|chf|gbp|cad|aud)\b", stripped, re.I)
        or re.search(r"\d[.,]\d", stripped)
    )
    cleaned = re.sub(r"[€£$]", "", stripped)
    for code in _ISO_CURRENCY:
        cleaned = re.sub(rf"\b{code}\b", "", cleaned, flags=re.I)
    cleaned = cleaned.replace(" ", "").strip()
    if not cleaned or re.search(r"[a-zA-Z]", cleaned):
        return None
    major = _parse_major_number(cleaned)
    if major is None or major < 0:
        return None
    if looks_like_major:
        return int(round(major * 100))
    if re.fullmatch(r"\d+", cleaned):
        return int(cleaned)
    return int(round(major * 100))


def format_original_text(
    image_path: str,
    merchant,
    amount_cents: int | None,
    currency: str | None = None,
) -> str:
    """History-readable line: merchant + CHF 54.50 / $14.50 when known."""
    label = os.path.basename(image_path) if image_path else "receipt"
    merchant_s = str(merchant).strip() if merchant not in (None, "") else ""
    amount_s = ""
    if isinstance(amount_cents, int) and amount_cents >= 0:
        major = amount_cents / 100
        code = (currency or "").strip().upper()
        if code and code not in {"USD", "$"}:
            amount_s = f"{code} {major:.2f}"
        else:
            amount_s = f"${major:.2f}"
    if merchant_s and amount_s:
        return f"{merchant_s} · {amount_s}"
    if merchant_s:
        return merchant_s
    if amount_s:
        return amount_s
    return f"[receipt photo: {label}]"


def _register_heif() -> None:
    global _heif_tried
    if _heif_tried:
        return
    _heif_tried = True
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception:
        pass


def _to_rgb(image):
    from PIL import Image

    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        background = Image.new("RGB", image.size, (255, 255, 255))
        converted = image.convert("RGBA")
        background.paste(converted, mask=converted.split()[-1])
        return background
    return image.convert("RGB")


def jpeg_bytes_for_vision(image_path: str) -> tuple[bytes, dict]:
    """Return JPEG bytes for the vision API plus timing/size metadata.

    Falls back to the original file bytes when Pillow cannot open the image.
    """
    original_size = os.path.getsize(image_path) if os.path.isfile(image_path) else 0
    meta = {
        "original_bytes": original_size,
        "jpeg_bytes": original_size,
        "resized": False,
        "fallback": False,
        "max_edge": 0,
        "width": 0,
        "height": 0,
    }
    try:
        from PIL import Image, ImageOps
    except ImportError:
        with open(image_path, "rb") as handle:
            data = handle.read()
        meta["fallback"] = True
        meta["jpeg_bytes"] = len(data)
        return data, meta

    _register_heif()
    try:
        with Image.open(image_path) as src:
            image = ImageOps.exif_transpose(src)
            image.load()
            image = _to_rgb(image)
            max_edge = _max_edge()
            width, height = image.size
            longest = max(width, height)
            if longest > max_edge:
                scale = max_edge / float(longest)
                new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
                image = image.resize(new_size, Image.Resampling.LANCZOS)
                meta["resized"] = True
            meta["width"], meta["height"] = image.size
            meta["max_edge"] = max(image.size)
            buffer = io.BytesIO()
            image.save(
                buffer,
                format="JPEG",
                quality=_jpeg_quality(),
                optimize=True,
                progressive=False,
            )
            data = buffer.getvalue()
        meta["jpeg_bytes"] = len(data)
        return data, meta
    except Exception as exc:
        logger.info("Pillow could not prepare %s (%s); sending original bytes", image_path, exc)
        with open(image_path, "rb") as handle:
            data = handle.read()
        meta["fallback"] = True
        meta["jpeg_bytes"] = len(data)
        return data, meta


def _encode_image(image_path: str) -> tuple[str, dict]:
    """Prepare a local photo and return a JPEG data URI plus encode metadata."""
    started = time.perf_counter()
    jpeg, meta = jpeg_bytes_for_vision(image_path)
    b64 = base64.b64encode(jpeg).decode("utf-8")
    meta["encode_ms"] = (time.perf_counter() - started) * 1000
    meta["b64_chars"] = len(b64)
    print(
        f"[receipt] encode {meta['encode_ms']:.0f}ms "
        f"original={meta['original_bytes']} jpeg={meta['jpeg_bytes']} "
        f"size={meta['width']}x{meta['height']} resized={meta['resized']} "
        f"fallback={meta['fallback']}"
    )
    return f"data:image/jpeg;base64,{b64}", meta


def _get_client():
    """Build the OpenAI-compatible NVIDIA client on first use."""
    global _client
    if _client is not None:
        return _client
    api_key = nvidia_api_key()
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set")
    from openai import OpenAI

    _client = OpenAI(
        base_url=NVIDIA_BASE_URL,
        api_key=api_key,
        timeout=VISION_TIMEOUT_S,
    )
    return _client


def _fallback(image_path, *, failed=True):
    label = os.path.basename(image_path) if image_path else "receipt"
    return {
        "original_text": f"[receipt photo: {label}]",
        "merchant": None,
        "amount_cents": None,
        "category": "Other",
        "confidence": 0.0,
        "needs_review": True,
        "nemotron_failed": bool(failed),
    }


def categorize_receipt(image_path):
    """
    Takes a path to a local receipt photo, returns a dict matching the expense shape
    from CONTRACT.md. One vision attempt by default (``RECEIPT_VISION_RETRIES``).
    A second attempt runs only on JSON parse errors when retries >= 2 — no sleep.
    Falls back to a flagged review state if the vision model fails — never crashes.
    """
    if not nvidia_api_key():
        print("[receipt] NVIDIA_API_KEY is not set; skipping vision call")
        return _fallback(image_path, failed=True)

    try:
        data_uri, encode_meta = _encode_image(image_path)
    except Exception as e:
        print(f"[receipt] could not read image {image_path!r}: {e}")
        return _fallback(image_path, failed=True)

    last_error = None
    result = None
    attempts = _vision_attempts()
    api_ms_total = 0.0

    for attempt in range(attempts):
        raw = None
        try:
            started = time.perf_counter()
            response = _get_client().chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "Read this receipt. Use TOTAL / Summe / CHF|USD|$|€ after "
                                    "the item lines. Ignore MwSt/VAT-only, tips unless grand "
                                    "total, FX lines (Entspricht in Euro), and line-item prices. "
                                    "54.50 or 54,50 → amount_cents 5450. Return JSON."
                                ),
                            },
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    },
                ],
                temperature=0,
                max_tokens=300,
                timeout=VISION_TIMEOUT_S,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            api_ms = (time.perf_counter() - started) * 1000
            api_ms_total += api_ms
            print(f"[receipt] vision api {api_ms:.0f}ms attempt={attempt + 1}/{attempts}")
            raw = response.choices[0].message.content
            cleaned = _clean_json_response(raw)
            result = json.loads(cleaned)
            break
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            last_error = e
            print(f"[receipt] attempt {attempt + 1} failed to parse: {e}")
            print(f"[receipt] raw response was: {raw!r}")
            result = None
            # Parse errors only — no 1s sleep. Further attempts require retries >= 2.
        except Exception as e:
            last_error = e
            print(f"[receipt] attempt {attempt + 1} API call failed: {e}")
            result = None
            break

    print(
        f"[receipt] done encode_ms={encode_meta.get('encode_ms', 0):.0f} "
        f"api_ms={api_ms_total:.0f} jpeg_bytes={encode_meta.get('jpeg_bytes')}"
    )

    if result is None:
        print(f"[receipt] giving up after {attempts} attempt(s). Last error: {last_error}")
        return _fallback(image_path, failed=True)

    category = result.get("category")
    valid_categories = {"Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other"}
    if category not in valid_categories:
        category = "Other"

    amount_cents = coerce_amount_cents(result.get("amount_cents"))
    merchant = result.get("merchant")
    if merchant is not None:
        merchant = str(merchant).strip() or None
    currency = infer_currency(result.get("currency"), result.get("amount_cents"), merchant)

    return {
        "original_text": format_original_text(image_path, merchant, amount_cents, currency),
        "merchant": merchant,
        "amount_cents": amount_cents,
        "category": category,
        "confidence": result.get("confidence", 0.0),
        "needs_review": result.get("needs_review", True) if amount_cents is not None else True,
        "nemotron_failed": False,
    }
