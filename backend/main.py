"""Where Is My Money — FastAPI backend (fake data scaffold)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

CATEGORIES = ("Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other")
Category = Literal["Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other"]
USER_ID = "demo"

app = FastAPI(title="Where Is My Money", version="0.1.0-fake")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory fake store (replaced by SQLite later)
_limits: dict[str, int] = {c: 5000 for c in CATEGORIES}  # $50.00 default
_settings = {
    "callDay": 0,  # Sunday
    "callHour": 18,
    "phoneNumber": "+10000000000",
}
_expenses: list[dict[str, Any]] = [
    {
        "id": "exp_demo_1",
        "userId": USER_ID,
        "originalText": "spent fourteen bucks on lunch",
        "source": "voice",
        "merchant": "Campus Cafe",
        "amountCents": 1400,
        "category": "Food",
        "confidence": 0.92,
        "needsReview": False,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
]


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "fake"}


@app.post("/log-expense")
async def log_expense(
    source: Literal["voice", "receipt"] = Form("voice"),
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    """Accept an upload; return fake parsed expense + limit check."""
    try:
        _ = await file.read() if file is not None else b""
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"Could not read upload: {exc}") from exc

    expense = {
        "id": f"exp_{int(datetime.now(timezone.utc).timestamp())}",
        "userId": USER_ID,
        "originalText": "spent fourteen bucks on lunch"
        if source == "voice"
        else "RECEIPT TOTAL 14.00 LUNCH",
        "source": source,
        "merchant": "Campus Cafe",
        "amountCents": 1400,
        "category": "Food",
        "confidence": 0.88 if source == "voice" else 0.75,
        "needsReview": source == "receipt",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    _expenses.insert(0, expense)

    category = expense["category"]
    week_total = sum(e["amountCents"] for e in _expenses if e["category"] == category)
    limit = _limits.get(category, 0)
    over_by = max(0, week_total - limit)
    action = "placed_call" if over_by > 0 else "nothing"

    return {
        "expense": expense,
        "limitCheck": {
            "category": category,
            "weekTotalCents": week_total,
            "limitCents": limit,
            "overByCents": over_by,
            "action": action,
            "note": "FAKE: no real Twilio call yet",
        },
    }


@app.post("/limits")
def set_limit(body: LimitBody) -> dict[str, Any]:
    try:
        _limits[body.category] = body.limitCents
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "limits": dict(_limits)}


@app.get("/limits")
def get_limits() -> dict[str, Any]:
    return {"userId": USER_ID, "limits": dict(_limits)}


@app.post("/settings")
def set_settings(body: SettingsBody) -> dict[str, Any]:
    _settings["callDay"] = body.callDay
    _settings["callHour"] = body.callHour
    _settings["phoneNumber"] = body.phoneNumber
    return {"ok": True, "settings": dict(_settings)}


@app.get("/settings")
def get_settings() -> dict[str, Any]:
    return {"userId": USER_ID, "settings": dict(_settings)}


@app.get("/expenses")
def get_expenses() -> dict[str, Any]:
    totals = {c: 0 for c in CATEGORIES}
    for e in _expenses:
        totals[e["category"]] = totals.get(e["category"], 0) + e["amountCents"]
    return {
        "userId": USER_ID,
        "weekTotalCents": sum(totals.values()),
        "totalsByCategory": totals,
        "expenses": list(_expenses),
    }


@app.post("/trigger-call")
def trigger_call(body: TriggerCallBody) -> dict[str, Any]:
    return {
        "ok": True,
        "kind": body.kind,
        "category": body.category,
        "message": "FAKE: would place Twilio call now",
        "calledAt": datetime.now(timezone.utc).isoformat(),
    }
