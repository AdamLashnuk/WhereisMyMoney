"""Outbound phone calls via Twilio.

Missing credentials must never crash the process: ``place_call`` returns
``{"ok": False, ...}`` so FastAPI can still boot and serve the app.

Trial accounts often reject inline ``twiml=`` on Calls.create — we use a
Twimlets message URL instead, which works on free/trial.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("whereismymoney.twilio")


def twilio_configured() -> bool:
    return bool(
        os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        and os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        and os.getenv("TWILIO_PHONE_NUMBER", "").strip()
    )


def destination_phone(explicit: str | None = None) -> str:
    return (explicit or os.getenv("MY_PHONE_NUMBER") or "").strip()


def place_call(to: str | None, spoken_text: str) -> dict[str, Any]:
    """Place a TTS phone call. Returns ``ok: false`` instead of raising."""
    dest = destination_phone(to)
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_PHONE_NUMBER", "").strip()

    if not (sid and token and from_number):
        logger.info("Twilio keys missing — not placing a call")
        return {
            "ok": False,
            "error": "Twilio is not configured (set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER)",
        }
    if not dest:
        return {"ok": False, "error": "No destination phone number in settings or MY_PHONE_NUMBER"}

    try:
        from twilio.rest import Client
    except ImportError:
        logger.warning("twilio package is not installed")
        return {"ok": False, "error": "twilio package is not installed"}

    try:
        # Trial-safe: Twimlets serves TwiML for Say. Avoids inline twiml= which
        # trial accounts often reject with "disallowed parameters".
        message = (spoken_text or "Where Is My Money.").strip()[:900]
        twiml_url = "https://twimlets.com/message?Message%5B0%5D=" + quote(message)

        client = Client(sid, token)
        call = client.calls.create(to=dest, from_=from_number, url=twiml_url)
        return {"ok": True, "sid": call.sid, "to": dest}
    except Exception as exc:
        logger.warning("Twilio call failed: %s", exc)
        return {"ok": False, "error": str(exc), "to": dest}
