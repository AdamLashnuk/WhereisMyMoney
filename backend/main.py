"""Where Is My Money — FastAPI backend.

Real SQLite + heuristic categorizer with optional NVIDIA Nemotron (Person C).
Starts without Twilio or NVIDIA keys. Demo works offline.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
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

from categorizer import UnknownAmountError, parse_expense
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
    call_audio_path,
    is_call_audio_token,
    place_call,
    public_base_url,
    render_play_twiml,
    twilio_configured,
)
from whisper_client import transcribe_audio, whisper_stub_enabled

_BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_BACKEND_DIR.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("whereismymoney")

Category = Literal["Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other"]
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".webm", ".mpeg", ".mp4", ".flac"}


def cents_to_speech(cents: int) -> str:
    dollars, rem = divmod(abs(int(cents)), 100)
    if rem == 0:
        unit = "dollar" if dollars == 1 else "dollars"
        return f"{dollars} {unit}"
    return f"{dollars} dollars and {rem} cents"


def _nemotron_configured() -> bool:
    key = os.getenv("NVIDIA_API_KEY")
    return bool(key and str(key).strip())


def over_limit_speech(category: str, week_total: int, limit: int, over_by: int) -> str:
    fallback = (
        f"This is Where Is My Money. You went over your {category} limit. "
        f"You spent {cents_to_speech(week_total)}. "
        f"Your limit is {cents_to_speech(limit)}. "
        f"You are over by {cents_to_speech(over_by)}."
    )
    if not _nemotron_configured():
        return fallback
    try:
        from ai.overlimit_alert import overlimit_alert_sentence

        spoken = overlimit_alert_sentence(category, limit, over_by)
        if spoken and str(spoken).strip():
            return str(spoken).strip()
    except Exception:
        logger.exception("Nemotron over-limit sentence failed; using template")
    return fallback


def weekly_summary_speech(
    totals: dict[str, int],
    week_total: int,
    last_week_totals: dict[str, int] | None = None,
) -> str:
    parts = [
        "This is Where Is My Money with your weekly summary.",
        f"You spent {cents_to_speech(week_total)} this week.",
    ]
    for category in CATEGORIES:
        amount = totals.get(category, 0)
        if amount:
            parts.append(f"{category}: {cents_to_speech(amount)}.")
    if week_total == 0:
        parts.append("No expenses logged this week.")
    base = " ".join(parts)
    if not _nemotron_configured():
        return base
    try:
        from ai.weekly_pattern import weekly_pattern_sentence

        previous = last_week_totals if last_week_totals is not None else {c: 0 for c in CATEGORIES}
        extra = weekly_pattern_sentence(totals, previous)
        if extra and str(extra).strip():
            return f"{base} {str(extra).strip()}"
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


def place_weekly_summary_call(*, force: bool = False) -> dict[str, Any]:
    week_start = sunday_week_start()
    totals = week_totals(week_start=week_start)
    week_total = sum(totals.values())
    last_week_totals = week_totals(week_start=week_start - timedelta(days=7))
    spoken = weekly_summary_speech(totals, week_total, last_week_totals)

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

    settings = get_settings()
    call = place_call(settings.get("phoneNumber"), spoken)
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
    return {
        "status": "ok",
        "mode": "live",
        "userId": USER_ID,
        "whisperStub": whisper_stub_enabled(),
        "twilioConfigured": twilio_configured(),
        "nemotronConfigured": _nemotron_configured(),
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
    """First-party TwiML for Twilio: <Play> the cached ElevenLabs mp3."""
    return _play_twiml_response(token, request)


@app.get("/call-audio/{token}.mp3")
def serve_call_audio(token: str) -> FileResponse:
    """Public mp3 Twilio fetches after our TwiML <Play>."""
    if not is_call_audio_token(token):
        raise HTTPException(status_code=404, detail="Unknown call audio")
    path = call_audio_path(token)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown call audio")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{token}.mp3")


async def _read_upload(file: UploadFile | None) -> tuple[bytes, str]:
    if file is None:
        return b"", ""
    try:
        data = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read upload: {exc}") from exc
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds 20 MB")
    filename = file.filename or ""
    return data, filename


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


def _original_text(*, source: str, text: str | None, upload: bytes, filename: str) -> tuple[str, str]:
    """Return (original_text, text_engine)."""
    if text and text.strip():
        return text.strip(), "form"

    if source == "voice":
        suffix = Path(filename).suffix.lower() if filename else ".wav"
        if suffix not in AUDIO_SUFFIXES:
            suffix = ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(upload)
            tmp_path = tmp.name
        try:
            spoken, engine = transcribe_audio(tmp_path, source="voice")
            return spoken, engine
        finally:
            with suppress(OSError):
                os.unlink(tmp_path)

    decoded = _decode_text_bytes(upload)
    if decoded:
        return decoded, "receipt-text"

    # Receipt images have no OCR until Person C. Stub keeps /log-expense usable.
    if whisper_stub_enabled() or not upload:
        return "RECEIPT TOTAL 14.00 LUNCH", "stub"
    raise HTTPException(
        status_code=400,
        detail="Could not extract text from receipt. Send a text file, a `text` form field, or wait for Person C OCR/Nemotron.",
    )


@app.post("/log-expense")
async def log_expense(
    source: Literal["voice", "receipt"] = Form("voice"),
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
) -> dict[str, Any]:
    """Voice or receipt → persist expense → run the weekly limit check."""
    upload, filename = await _read_upload(file)
    try:
        original, engine = _original_text(source=source, text=text, upload=upload, filename=filename)
        parsed = parse_expense(original)
        expense = insert_expense(
            original_text=parsed.original_text,
            source=source,
            merchant=parsed.merchant,
            amount_cents=int(parsed.amount_cents),
            category=parsed.category,
            confidence=parsed.confidence,
            needs_review=parsed.needs_review,
        )
        limit_check = _maybe_over_limit_call(parsed.category)
        return {
            "expense": expense,
            "limitCheck": limit_check,
            "parse": {
                "engine": parsed.engine,
                "textEngine": engine,
                "swap": "ai.categorize.categorize_expense when NVIDIA_API_KEY is set; heuristic fallback otherwise.",
            },
        }
    except UnknownAmountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("log-expense failed")
        raise HTTPException(status_code=500, detail=f"Could not log expense: {exc}") from exc


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
        settings = get_settings()
        call = place_call(settings.get("phoneNumber"), spoken)
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
            "calledAt": logged["calledAt"],
            "error": call.get("error"),
        }

    result = place_weekly_summary_call(force=True)
    return {
        "ok": bool(result.get("ok")),
        "kind": "weekly_summary",
        "category": None,
        "message": result.get("message"),
        "weekTotalCents": result.get("weekTotalCents"),
        "totalsByCategory": result.get("totalsByCategory"),
        "calledAt": (result.get("call") or {}).get("calledAt"),
        "error": result.get("error"),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
