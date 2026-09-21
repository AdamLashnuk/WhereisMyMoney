# CONTRACT

Money is always whole cents (integers). Exactly six categories: Food, Transport, Subscriptions, Shopping, Bills, Other. Over limit by any amount triggers a call. No login — user is `"demo"`. Keep original text forever.

## Endpoints

- `POST /log-expense` — voice or receipt → expense(s) + limit check. Voice transcripts may contain **multiple** spends in one take; the backend splits into N ≥ 1 ledger rows. Response always includes the first row as `expense` (backward compatible) plus `expenses` (all rows) and `results` (`{ expense, limitCheck }` per row). Receipt **images** use `ai.receipt.categorize_receipt` (Nemotron vision); null `amount_cents` is HTTP 400 (no invented cents). Empty/garbage voice text is HTTP 400.
- `POST /parse-limit` — JSON `{ "text": "..." }` → `{ category, amount_cents, period: "weekly", confidence }`. Does **not** save. If confidence is high and both fields are present, the app should then `POST /limits`.
- `POST /limits` / `GET /limits` — `POST` body remains `{ category, limitCents }`
- `POST /settings` / `GET /settings`
- `GET /expenses`
- `GET /health` — `{ status, whisperStub, twilioConfigured, nemotronConfigured, receiptOcrEnabled, capabilities: { receiptOCR, voiceStt, nemotron } }`. Receipt vision is advertised when `NVIDIA_API_KEY` is set.
- `POST /trigger-call` — `{ kind, category?, phoneNumber? }`. Optional `phoneNumber` is a one-time E.164-ish override (does not persist settings).
- `GET`/`POST` `/twiml/play/{token}` — TwiML `<Play>` for Twilio outbound calls, then hang up
- `GET /call-audio/{token}.ulaw` — cached ElevenLabs 8 kHz μ-law (`audio/x-mulaw`)
