"""Where Is My Money — FastAPI backend.

Real SQLite + heuristic categorizer with optional NVIDIA Nemotron (Person C).
Starts without Twilio or NVIDIA keys. Demo works offline.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import tempfile
import time
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from categorizer import UnknownAmountError, parse_expense, parse_receipt_image
from db import (
    CATEGORIES,
    USER_ID,
    get_limits,
    get_settings,
    has_successful_call,
    init_db,
    insert_expense,
    list_expenses,
    local_now,
    log_call,
    set_limit,
    set_settings,
    sunday_week_start,
    week_total_for_category,
    week_totals,
)
from twilio_client import (
    CALL_AUDIO_MEDIA_TYPE,
    call_audio_filename,
    call_audio_path,
    is_call_audio_token,
    place_call,
    public_base_url,
    render_play_twiml,
    twilio_configured,
)
from weekly_summary import expenses_spent_sentence
from whisper_client import transcribe_audio, whisper_stub_enabled

_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_BACKEND_DIR.parent / ".env")

from ai.money_speech import cents_to_speech, rewrite_money_for_speech  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("whereismymoney")

Category = Literal["Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other"]
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".webm", ".mpeg", ".mp4", ".flac", ".caf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".bmp"}
_E164ISH = re.compile(r"^\+[1-9]\d{7,14}$")
_CONTENT_TYPE_AUDIO_SUFFIX = {
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/flac": ".flac",
    "audio/x-caf": ".caf",
    "video/mp4": ".m4a",
}


def _nemotron_configured() -> bool:
    key = os.getenv("NVIDIA_API_KEY")
    return bool(key and str(key).strip())


def _elevenlabs_configured() -> bool:
    return bool(os.getenv("ELEVENLABS_API_KEY", "").strip())


def _voice_stt_available() -> bool:
    """Live STT is advertised only when the stub is off and a key is present."""
    if whisper_stub_enabled():
        return False
    return _elevenlabs_configured() or bool(os.getenv("OPENAI_API_KEY", "").strip())


def _normalize_trigger_phone(override: str | None) -> str | None:
    """Validate an optional E.164-ish override. None/blank → use saved settings."""
    if override is None:
        return None
    cleaned = str(override).strip()
    if not cleaned:
        return None
    if _E164ISH.fullmatch(cleaned):
        return cleaned
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) >= 8:
        return cleaned
    raise HTTPException(
        status_code=400,
        detail="phoneNumber must be E.164 (e.g. +14155550123) or at least 8 digits",
    )


def _call_destination(override: str | None) -> str | None:
    """Dial override if provided, else saved settings (place_call falls back to MY_PHONE_NUMBER)."""
    validated = _normalize_trigger_phone(override)
    if validated:
        return validated
    return get_settings().get("phoneNumber")


def over_limit_speech(category: str, week_total: int, limit: int, over_by: int) -> str:
    # Keep the phone script short (~15 words). Callers still pass week_total
    # for the function signature; Nemotron only needs category/limit/over_by.
    fallback = (
        f"This is Where Is My Money. You went over your {category} limit. "
        f"You are over by {cents_to_speech(over_by)}."
    )
    if not _nemotron_configured():
        return fallback
    try:
        from ai.overlimit_alert import overlimit_alert_sentence

        spoken = overlimit_alert_sentence(category, limit, over_by)
        if spoken and str(spoken).strip():
            return rewrite_money_for_speech(str(spoken).strip())
    except Exception:
        logger.exception("Nemotron over-limit sentence failed; using template")
    return fallback


def weekly_summary_speech(
    totals: dict[str, int],
    week_total: int,
    last_week_totals: dict[str, int] | None = None,
    expenses: list[dict[str, Any]] | None = None,
) -> str:
    """Spoken weekly call script. Lists this week's expenses when provided."""
    spent_list = expenses_spent_sentence(expenses)
    if spent_list:
        base = rewrite_money_for_speech(spent_list)
    elif week_total == 0:
        base = "No expenses logged this week."
    else:
        parts = [f"You spent {cents_to_speech(week_total)} this week."]
        top_category = max(CATEGORIES, key=lambda category: totals.get(category, 0))
        if totals.get(top_category, 0):
            parts.append(f"Mostly on {top_category}.")
        base = " ".join(parts)

    # Expense list is the demo script. Skip Nemotron so the call stays short.
    if spent_list or not _nemotron_configured():
        return base
    try:
        from ai.weekly_pattern import weekly_pattern_sentence

        previous = last_week_totals if last_week_totals is not None else {c: 0 for c in CATEGORIES}
        extra = weekly_pattern_sentence(totals, previous)
        if extra and str(extra).strip():
            return rewrite_money_for_speech(f"{base} {str(extra).strip()}")
    except Exception:
        logger.exception("Nemotron weekly pattern failed; using template")
    return base


def _maybe_over_limit_call(category: str) -> dict[str, Any]:
    """If this week's total exceeds the limit by any cent, call once per category per week."""
    week_start = sunday_week_start()
    limits = get_limits()
    limit = int(limits.get(category, 0))
    total = week_total_for_category(category, week_start=week_start)
    over_by = max(0, total - limit)
    result: dict[str, Any] = {
        "category": category,
        "weekTotalCents": total,
        "limitCents": limit,
        "overByCents": over_by,
        "action": "nothing",
        "note": None,
        "call": None,
    }
    if over_by <= 0:
        return result

    if has_successful_call("over_limit", category, week_start):
        result["action"] = "already_called"
        result["note"] = "Already placed an over-limit call for this category this week"
        return result

    settings = get_settings()
    spoken = over_limit_speech(category, total, limit, over_by)
    call = place_call(settings.get("phoneNumber"), spoken)
    logged = log_call(
        kind="over_limit",
        category=category,
        week_start=week_start,
        ok=bool(call.get("ok")),
        message=spoken,
        sid=call.get("sid"),
    )
    result["call"] = {**call, "calledAt": logged["calledAt"]}
    if call.get("ok"):
        result["action"] = "placed_call"
        result["note"] = "Placed over-limit call"
    else:
        result["action"] = "call_failed"
        result["note"] = call.get("error") or "Call was not placed"
    return result


def place_weekly_summary_call(*, force: bool = False, phone_number: str | None = None) -> dict[str, Any]:
    week_start = sunday_week_start()
    totals = week_totals(week_start=week_start)
    week_total = sum(totals.values())
    last_week_totals = week_totals(week_start=week_start - timedelta(days=7))
    expenses = list_expenses(week_start=week_start)
    spoken = weekly_summary_speech(totals, week_total, last_week_totals, expenses=expenses)

    if not force and has_successful_call("weekly_summary", None, week_start):
        return {
            "ok": True,
            "kind": "weekly_summary",
            "action": "already_called",
            "weekStart": week_start.isoformat(),
            "weekTotalCents": week_total,
            "totalsByCategory": totals,
            "message": spoken,
        }

    dest = _call_destination(phone_number)
    call = place_call(dest, spoken)
    logged = log_call(
        kind="weekly_summary",
        category=None,
        week_start=week_start,
        ok=bool(call.get("ok")),
        message=spoken,
        sid=call.get("sid"),
    )
    return {
        "ok": bool(call.get("ok")),
        "kind": "weekly_summary",
        "action": "placed_call" if call.get("ok") else "call_failed",
        "weekStart": week_start.isoformat(),
        "weekTotalCents": week_total,
        "totalsByCategory": totals,
        "message": spoken,
        "call": {**call, "calledAt": logged["calledAt"]},
        "error": call.get("error"),
    }


def maybe_run_scheduled_weekly_call() -> dict[str, Any] | None:
    settings = get_settings()
    now = local_now()
    js_weekday = (now.weekday() + 1) % 7
    if js_weekday != int(settings["callDay"]) or now.hour != int(settings["callHour"]):
        return None
    return place_weekly_summary_call(force=False)


async def _scheduler_loop(stop: asyncio.Event) -> None:
    """Hourly tick: place the weekly summary call on callDay at callHour."""
    while not stop.is_set():
        try:
            result = maybe_run_scheduled_weekly_call()
            if result is not None:
                logger.info("Scheduler weekly call: %s", result.get("action"))
        except Exception:
            logger.exception("Scheduler tick failed")
        now = local_now()
        next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        delay = max(1.0, (next_hour - now).total_seconds())
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    logger.info("SQLite ready at %s", _BACKEND_DIR / "whereismymoney.db")
    stop = asyncio.Event()
    task = asyncio.create_task(_scheduler_loop(stop), name="weekly-call-scheduler")
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Where Is My Money",
    version="1.0.0",
    description="SteelHacks backend — SQLite, heuristic or Nemotron categorizer, optional Whisper + Twilio.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LimitBody(BaseModel):
    category: Category
    limitCents: int = Field(..., ge=0)


class SettingsBody(BaseModel):
    callDay: int = Field(..., ge=0, le=6)
    callHour: int = Field(..., ge=0, le=23)
    phoneNumber: str = Field(..., min_length=8)


class TriggerCallBody(BaseModel):
    kind: Literal["over_limit", "weekly_summary"] = "weekly_summary"
    category: Category | None = None
    phoneNumber: str | None = None


class ParseLimitBody(BaseModel):
    text: str = Field(..., min_length=1)


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"ok": False, "error": "Validation error", "detail": exc.errors()})


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": exc.detail})


@app.exception_handler(Exception)
async def unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@app.get("/health")
def health() -> dict[str, Any]:
    nemotron = _nemotron_configured()
    return {
        "status": "ok",
        "mode": "live",
        "userId": USER_ID,
        "whisperStub": whisper_stub_enabled(),
        "twilioConfigured": twilio_configured(),
        "nemotronConfigured": nemotron,
        "receiptOcrEnabled": nemotron,
        "capabilities": {
            "receiptOCR": nemotron,
            "voiceStt": _voice_stt_available(),
            "nemotron": nemotron,
        },
    }


def _play_twiml_response(token: str, request: Request) -> Response:
    if not is_call_audio_token(token):
        raise HTTPException(status_code=404, detail="Unknown call audio")
    path = call_audio_path(token)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown call audio")
    base = public_base_url() or str(request.base_url).rstrip("/")
    xml = render_play_twiml(token, base=base)
    if not xml:
        raise HTTPException(status_code=404, detail="Unknown call audio")
    return Response(content=xml, media_type="application/xml")


@app.api_route("/twiml/play/{token}", methods=["GET", "POST"])
def twiml_play(token: str, request: Request) -> Response:
    """First-party TwiML for Twilio: <Play> the alert, then hang up."""
    return _play_twiml_response(token, request)


@app.get("/call-audio/{token}.ulaw")
def serve_call_audio(token: str) -> FileResponse:
    """Public 8 kHz μ-law file Twilio fetches after our TwiML <Play>."""
    if not is_call_audio_token(token):
        raise HTTPException(status_code=404, detail="Unknown call audio")
    path = call_audio_path(token)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown call audio")
    return FileResponse(
        path,
        media_type=CALL_AUDIO_MEDIA_TYPE,
        filename=call_audio_filename(token),
    )


async def _read_upload(file: UploadFile | None) -> tuple[bytes, str, str]:
    if file is None:
        return b"", "", ""
    try:
        data = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read upload: {exc}") from exc
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds 20 MB")
    filename = file.filename or ""
    content_type = file.content_type or ""
    return data, filename, content_type


def _looks_like_image(filename: str, data: bytes, content_type: str = "") -> bool:
    suffix = Path(filename).suffix.lower() if filename else ""
    if suffix in IMAGE_SUFFIXES:
        return True
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype.startswith("image/"):
        return True
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return True
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return True
    return False


def _decode_text_bytes(data: bytes) -> str | None:
    if not data:
        return None
    if b"\x00" in data[:1024]:
        return None
    for encoding in ("utf-8", "latin-1"):
        try:
            text = data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
        if text and text.isprintable() or (text and all(ch.isprintable() or ch.isspace() for ch in text)):
            return text
    return None


def _audio_suffix(filename: str, content_type: str = "") -> str:
    suffix = Path(filename).suffix.lower() if filename else ""
    if suffix in AUDIO_SUFFIXES:
        return suffix
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_AUDIO_SUFFIX.get(ctype, ".m4a")


def _transcribe_upload(upload: bytes, filename: str, content_type: str = "") -> tuple[str, str]:
    suffix = _audio_suffix(filename, content_type)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(upload)
        tmp_path = tmp.name
    try:
        return transcribe_audio(
            tmp_path,
            source="voice",
            content_type=content_type,
            filename=filename,
        )
    finally:
        with suppress(OSError):
            os.unlink(tmp_path)


def _original_text(
    *,
    source: str,
    text: str | None,
    upload: bytes,
    filename: str,
    content_type: str = "",
) -> tuple[str, str]:
    """Return (original_text, text_engine)."""
    # Voice audio bytes always go through STT — do not prefer a leftover form field.
    if source == "voice" and upload:
        return _transcribe_upload(upload, filename, content_type)

    if text and text.strip():
        return text.strip(), "form"

    if source == "voice":
        return _transcribe_upload(upload, filename, content_type)

    decoded = _decode_text_bytes(upload)
    if decoded:
        return decoded, "receipt-text"

    # Non-image receipt uploads: stub text keeps the demo usable without a photo.
    # Image files never reach here — they go through categorize_receipt instead.
    if whisper_stub_enabled() or not upload:
        return "RECEIPT TOTAL 14.00 LUNCH", "stub"
    raise HTTPException(
        status_code=400,
        detail="Could not extract text from receipt. Send an image file, a text file, or a `text` form field.",
    )


def _expense_payload(parsed, source: str, text_engine: str, swap: str) -> dict[str, Any]:
    expense = insert_expense(
        original_text=parsed.original_text,
        source=source,
        merchant=parsed.merchant,
        amount_cents=int(parsed.amount_cents),
        category=parsed.category,
        confidence=parsed.confidence,
        needs_review=parsed.needs_review,
    )
    return {
        "expense": expense,
        "limitCheck": _maybe_over_limit_call(parsed.category),
        "parse": {
            "engine": parsed.engine,
            "textEngine": text_engine,
            "swap": swap,
        },
    }


@app.post("/log-expense")
async def log_expense(
    source: Literal["voice", "receipt"] = Form("voice"),
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
) -> dict[str, Any]:
    """Voice or receipt → persist expense → run the weekly limit check."""
    upload, filename, content_type = await _read_upload(file)
    started = time.perf_counter()
    try:
        if source == "receipt" and upload and _looks_like_image(filename, upload, content_type):
            suffix = Path(filename).suffix.lower() if filename else ""
            if suffix not in IMAGE_SUFFIXES:
                suffix = ".jpg"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(upload)
                tmp_path = tmp.name
            try:
                parsed = parse_receipt_image(tmp_path)
            finally:
                with suppress(OSError):
                    os.unlink(tmp_path)
            logger.info(
                "log-expense source=receipt vision_ms=%.0f amount_cents=%s",
                (time.perf_counter() - started) * 1000,
                parsed.amount_cents,
            )
            return _expense_payload(
                parsed,
                source,
                "receipt",
                "ai.receipt.categorize_receipt (nvidia/nemotron-3-nano-omni vision).",
            )

        stt_started = time.perf_counter()
        original, engine = _original_text(
            source=source,
            text=text,
            upload=upload,
            filename=filename,
            content_type=content_type,
        )
        stt_ms = (time.perf_counter() - stt_started) * 1000
        parse_started = time.perf_counter()
        parsed = parse_expense(original)
        parse_ms = (time.perf_counter() - parse_started) * 1000
        logger.info(
            "log-expense source=%s stt_ms=%.0f nemotron_ms=%.0f textEngine=%s parseEngine=%s",
            source,
            stt_ms,
            parse_ms,
            engine,
            parsed.engine,
        )
        return _expense_payload(
            parsed,
            source,
            engine,
            "ai.categorize.categorize_expense when NVIDIA_API_KEY is set; heuristic fallback otherwise.",
        )
    except UnknownAmountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("log-expense failed")
        raise HTTPException(status_code=500, detail=f"Could not log expense: {exc}") from exc


PARSE_LIMIT_SAVE_CONFIDENCE = 0.6


def parse_limit_text(text: str) -> dict[str, Any]:
    """Same result as ``POST /parse-limit``. Does not persist."""
    from ai.spoken_limit import understand_spoken_limit

    try:
        parsed = understand_spoken_limit(text)
    except Exception:
        logger.exception("spoken limit parse failed")
        parsed = {
            "category": None,
            "amount_cents": None,
            "period": "weekly",
            "confidence": 0.0,
        }

    if not isinstance(parsed, dict):
        parsed = {
            "category": None,
            "amount_cents": None,
            "period": "weekly",
            "confidence": 0.0,
        }

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


@app.post("/parse-limit")
def parse_limit(body: ParseLimitBody) -> dict[str, Any]:
    """Parse spoken limit text. Does not save. High-confidence results can POST /limits."""
    return parse_limit_text(body.text)


@app.post("/limits")
def post_limits(body: LimitBody) -> dict[str, Any]:
    if body.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category: {body.category}")
    try:
        limits = set_limit(body.category, body.limitCents)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "userId": USER_ID, "limits": limits}


@app.get("/limits")
def read_limits() -> dict[str, Any]:
    return {"userId": USER_ID, "limits": get_limits()}


@app.post("/settings")
def post_settings(body: SettingsBody) -> dict[str, Any]:
    settings = set_settings(body.callDay, body.callHour, body.phoneNumber)
    return {"ok": True, "userId": USER_ID, "settings": settings}


@app.get("/settings")
def read_settings() -> dict[str, Any]:
    return {"userId": USER_ID, "settings": get_settings()}


@app.get("/expenses")
def read_expenses() -> dict[str, Any]:
    week_start = sunday_week_start()
    totals = week_totals(week_start=week_start)
    expenses = list_expenses(week_start=week_start)
    return {
        "userId": USER_ID,
        "weekStart": week_start.isoformat(),
        "weekTotalCents": sum(totals.values()),
        "totalsByCategory": totals,
        "expenses": expenses,
    }


@app.post("/trigger-call")
def trigger_call(body: TriggerCallBody) -> dict[str, Any]:
    """Manual trigger. Always attempts a call (does not wait for callDay/callHour)."""
    if body.kind == "over_limit":
        if body.category is None:
            raise HTTPException(status_code=400, detail="category is required for kind=over_limit")
        week_start = sunday_week_start()
        limits = get_limits()
        limit = int(limits.get(body.category, 0))
        total = week_total_for_category(body.category, week_start=week_start)
        over_by = max(0, total - limit)
        spoken = over_limit_speech(body.category, total, limit, over_by)
        dest = _call_destination(body.phoneNumber)
        call = place_call(dest, spoken)
        logged = log_call(
            kind="over_limit",
            category=body.category,
            week_start=week_start,
            ok=bool(call.get("ok")),
            message=spoken,
            sid=call.get("sid"),
        )
        return {
            "ok": bool(call.get("ok")),
            "kind": "over_limit",
            "category": body.category,
            "weekTotalCents": total,
            "limitCents": limit,
            "overByCents": over_by,
            "message": spoken,
            "to": dest,
            "calledAt": logged["calledAt"],
            "error": call.get("error"),
        }

    result = place_weekly_summary_call(force=True, phone_number=body.phoneNumber)
    call = result.get("call") or {}
    return {
        "ok": bool(result.get("ok")),
        "kind": "weekly_summary",
        "category": None,
        "message": result.get("message"),
        "weekTotalCents": result.get("weekTotalCents"),
        "totalsByCategory": result.get("totalsByCategory"),
        "to": call.get("to"),
        "calledAt": call.get("calledAt"),
        "error": result.get("error"),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
