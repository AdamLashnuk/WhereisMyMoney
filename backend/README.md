# Backend (Person B)

FastAPI + SQLite for Where Is My Money. The server **starts with no Twilio keys** and does **not** require Person C (Nemotron). Money is always integer cents. The only user is `demo`.

## Run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# optional: copy env from the repo root
cp ../.env.example ../.env   # then edit

# recommended for a laptop demo without a Whisper model
export WHISPER_STUB=1

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open API docs: http://127.0.0.1:8000/docs  
Health: http://127.0.0.1:8000/health

SQLite file: `backend/whereismymoney.db` (gitignored via root `*.db`). Override with `WHEREISMYMONEY_DB`.

## `.env`

Copy the repo-root `.env.example`. Relevant keys:

| Variable | Required to boot? | Purpose |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | no | Twilio account |
| `TWILIO_AUTH_TOKEN` | no | Twilio token |
| `TWILIO_PHONE_NUMBER` | no | From-number for outbound calls |
| `MY_PHONE_NUMBER` | no | Default destination if settings are empty |
| `WHISPER_STUB` | no | `1` forces stub audio→text (`spent fourteen bucks on lunch`) |
| `OPENAI_API_KEY` | no | Used when `WHISPER_STUB` is unset/`0` and `openai` is installed |
| `WHISPER_MODEL` | no | Local openai-whisper model name (default `base`) |
| `NVIDIA_API_KEY` | no | Reserved for Person C / Nemotron — unused today |
| `ELEVENLABS_API_KEY` | no | Unused by this backend |
| `TZ` | no | Timezone for the weekly call hour (default `America/New_York`) |
| `WHEREISMYMONEY_DB` | no | Alternate SQLite path |

Missing Twilio keys: `place_call` returns `{ "ok": false }` and the API keeps serving.

## ngrok (phone app + Twilio)

The Expo app needs an HTTPS URL. From a second terminal:

```bash
ngrok http 8000
```

Give Person A the `https://…ngrok-free.app` origin for `app/config.js` (`API_BASE_URL`). Do **not** put Twilio/NVIDIA keys in the phone app.

Outbound Twilio calls use inline TwiML (`<Say>`), so ngrok is **not** required just to place a call. You only need a public URL if you later add inbound Twilio webhooks.

## Contract

- Six categories: `Food`, `Transport`, `Subscriptions`, `Shopping`, `Bills`, `Other`
- Over the weekly limit by **any cent** → place a call, **once per category per week** (Sunday–Saturday)
- Settings: `callDay` 0–6 (Sunday = 0), `callHour` 0–23, `phoneNumber`. Default **Sunday 18:00**
- An hourly scheduler (FastAPI lifespan) places the weekly summary call at that day/hour
- `POST /trigger-call` always attempts immediately (`kind`: `weekly_summary` or `over_limit`)
- Original spoken/receipt text is stored forever

### Endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | `{ status: "ok", mode: "live", whisperStub, twilioConfigured }` |
| `POST` | `/log-expense` | `multipart/form-data`: `source=voice\|receipt`, optional `file`, optional `text` |
| `GET`/`POST` | `/limits` | `POST` body `{ category, limitCents }` |
| `GET`/`POST` | `/settings` | `POST` body `{ callDay, callHour, phoneNumber }` |
| `GET` | `/expenses` | Current week only |
| `POST` | `/trigger-call` | `{ kind, category? }` |

Example without an audio file:

```bash
curl -s -X POST http://127.0.0.1:8000/log-expense \
  -F source=voice \
  -F 'text=spent fourteen bucks on lunch'
```

## Swap in Nemotron (Person C)

`categorizer.parse_expense(text) -> ParsedExpense` is the **only** parse interface.

1. Keep the `ParsedExpense` fields (`original_text`, `merchant`, `amount_cents`, `category`, `confidence`, `needs_review`).
2. Replace the heuristic **body** of `parse_expense` with an NVIDIA API call using `NVIDIA_API_KEY`.
3. Do not change `main.py` — it only calls `parse_expense`.
4. Receipt OCR can produce text and then call the same function. Audio still goes through `whisper_client.transcribe_audio`.

Until that swap, a keyword/amount heuristic handles phrases like:

- `spent fourteen bucks on lunch` → $14.00 Food
- `two fifty for the bus` → $2.50 Transport
- `thirty two forty five on groceries` → $32.45 Food
