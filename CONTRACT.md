# CONTRACT

Money is always whole cents (integers). Exactly six categories: Food, Transport, Subscriptions, Shopping, Bills, Other. Over limit by any amount triggers a call. No login — user is `"demo"`. Keep original text forever.

## Endpoints

- `POST /log-expense` — voice or receipt → expense + limit check. Receipt **images** use `ai.receipt.categorize_receipt` (Nemotron vision); null `amount_cents` is HTTP 400 (no invented cents).
- `POST /parse-limit` — JSON `{ "text": "..." }` → `{ category, amount_cents, period: "weekly", confidence }`. Does **not** save. If confidence is high and both fields are present, the app should then `POST /limits`.
- `POST /limits` / `GET /limits` — `POST` body remains `{ category, limitCents }`
- `POST /settings` / `GET /settings`
- `GET /expenses`
- `POST /trigger-call`
- `GET`/`POST` `/twiml/play/{token}` — TwiML `<Play>` for Twilio outbound calls
- `GET /call-audio/{token}.ulaw` — cached ElevenLabs 8 kHz μ-law (`audio/x-mulaw`)
