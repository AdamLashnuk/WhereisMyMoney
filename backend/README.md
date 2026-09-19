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
| `ELEVENLABS_API_KEY` | no | Scribe STT (when `WHISPER_STUB` is unset/`0`) **and** Victoria TTS for outbound Twilio calls (`ai/elevenlabs_tts.py`, voice id `XoUkt2bf6DlvSzRmvA8X`) |
| `ELEVENLABS_STT_MODEL` | no | Scribe model id (default `scribe_v2`) |
| `PUBLIC_BASE_URL` | no | Public HTTPS origin of this backend (ngrok). Required for Twilio to `<Play>` ElevenLabs mp3. Example: `https://xxxx.ngrok-free.app` (no trailing slash). Alias: `CALL_AUDIO_BASE_URL`. Localhost will not work. |
| `CALL_AUDIO_BASE_URL` | no | Alias for `PUBLIC_BASE_URL` |
| `CALL_AUDIO_DIR` | no | Directory for cached call mp3s (default `backend/call_audio/`). Files are gitignored. |
| `OPENAI_API_KEY` | no | Used after ElevenLabs when `openai` is installed |
| `WHISPER_MODEL` | no | Local openai-whisper model name (default `base`) |
| `NVIDIA_API_KEY` | no | When set, `parse_expense` calls `ai.categorize.categorize_expense` (NVIDIA Nemotron). Missing/failed → heuristic parser. Also used for over-limit and weekly-summary call phrasing. |
| `TZ` | no | Timezone for the weekly call hour (default `America/New_York`) |
| `WHEREISMYMONEY_DB` | no | Alternate SQLite path |

Missing Twilio keys: `place_call` returns `{ "ok": false }` and the API keeps serving.

### Hear Victoria on `/trigger-call`

1. Set `ELEVENLABS_API_KEY` and Twilio keys in `.env`.
2. Run uvicorn on port 8000, then in another terminal: `ngrok http 8000`.
3. Set `PUBLIC_BASE_URL=https://….ngrok-free.app` (the ngrok HTTPS origin, no trailing slash) and restart uvicorn so it picks up the env.
4. `POST /trigger-call` with `{ "kind": "weekly_summary" }` (or an over-limit kind). Twilio fetches `/twiml/play/{token}` from that public origin and `<Play>`s `/call-audio/{token}.mp3` — Victoria (`eleven_multilingual_v2`).
5. If ElevenLabs fails **or** `PUBLIC_BASE_URL` is unset, `place_call` falls back to the trial-safe Twimlets `message` URL (Twilio `<Say>`).

## ngrok (phone app + Twilio)

The Expo app needs an HTTPS URL. From a second terminal:

```bash
ngrok http 8000
```

Give Person A the `https://…ngrok-free.app` origin for `app/config.js` (`API_BASE_URL`). Do **not** put Twilio/NVIDIA keys in the phone app.

Outbound calls that play **ElevenLabs Victoria** need ngrok (or another public HTTPS tunnel). Twilio cannot fetch `localhost`. Set `PUBLIC_BASE_URL` to the ngrok HTTPS origin so `place_call` can pass `url=` to `GET/POST /twiml/play/{token}`. Without that origin (or if TTS fails), calls fall back to Twimlets `<Say>` and ngrok is not required.

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
| `GET`/`POST` | `/twiml/play/{token}` | TwiML `<Play>` for Twilio (needs a cached mp3) |
| `GET` | `/call-audio/{token}.mp3` | Cached ElevenLabs mp3 Twilio fetches after `<Play>` |

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
