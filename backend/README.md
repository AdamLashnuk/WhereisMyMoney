# Backend (Person B)

FastAPI + SQLite for Where Is My Money. The server **starts with no Twilio or NVIDIA keys**. Money is always integer cents. The only user is `demo`.

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
| `ELEVENLABS_API_KEY` | no | When `WHISPER_STUB` is unset/`0`, voice files go to ElevenLabs Scribe first |
| `ELEVENLABS_STT_MODEL` | no | Scribe model id (default `scribe_v2`) |
| `OPENAI_API_KEY` | no | Used after ElevenLabs when `openai` is installed |
| `WHISPER_MODEL` | no | Local openai-whisper model name (default `base`) |
| `NVIDIA_API_KEY` | no | When set, `parse_expense` calls `ai.categorize.categorize_expense` (NVIDIA Nemotron). Missing/failed → heuristic parser. Also used for over-limit and weekly-summary call phrasing. |
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
| `GET` | `/health` | `{ status: "ok", mode: "live", whisperStub, twilioConfigured, nemotronConfigured }` |
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

Voice file (multipart field `file`). With `WHISPER_STUB=0` and `ELEVENLABS_API_KEY` set, this hits ElevenLabs Scribe:

```bash
curl -s -X POST http://127.0.0.1:8000/log-expense \
  -F source=voice \
  -F file=@sample.mp3
```

## Nemotron (Person C)

`categorizer.parse_expense(text) -> ParsedExpense` is the **only** parse interface `main.py` uses.

1. Keep the `ParsedExpense` fields (`original_text`, `merchant`, `amount_cents`, `category`, `confidence`, `needs_review`).
2. When `NVIDIA_API_KEY` is set, the parser calls `ai.categorize.categorize_expense` (Person C's prompt is unchanged) and maps the dict onto `ParsedExpense`.
3. If Nemotron is down or the key is missing, the keyword heuristic still handles demo phrases.
4. If Nemotron returns `amount_cents: null` (it understood the text but not the money), `/log-expense` returns **HTTP 400** and does **not** insert a guessed amount. Cents stay integers.
5. Over-limit Twilio speech uses `ai.overlimit_alert.overlimit_alert_sentence`; weekly summary appends `ai.weekly_pattern.weekly_pattern_sentence`. Both keep the existing template if Nemotron fails.

Until a key is set, a keyword/amount heuristic handles phrases like:

- `spent fourteen bucks on lunch` → $14.00 Food
- `two fifty for the bus` → $2.50 Transport
- `thirty two forty five on groceries` → $32.45 Food
