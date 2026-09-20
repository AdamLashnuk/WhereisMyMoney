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
| `WHISPER_STUB` | no | `1` forces stub audio→text (`spent fourteen bucks on lunch`). **Live voice STT requires `WHISPER_STUB=0` (or unset) and `ELEVENLABS_API_KEY`.** |
| `ELEVENLABS_API_KEY` | no | Scribe STT (when `WHISPER_STUB` is unset/`0`) **and** Victoria TTS for outbound Twilio calls (`ai/elevenlabs_tts.py`, voice id `XoUkt2bf6DlvSzRmvA8X`) |
| `ELEVENLABS_STT_MODEL` | no | Scribe model id (default `scribe_v2`) |
| `PUBLIC_BASE_URL` | no | Public HTTPS origin of this backend (ngrok). Required for Twilio to `<Play>` ElevenLabs μ-law. Example: `https://xxxx.ngrok-free.app` (no trailing slash). Alias: `CALL_AUDIO_BASE_URL`. Localhost will not work. If unset, outbound calls stay one-way Twimlets `<Say>`. |
| `CALL_AUDIO_BASE_URL` | no | Alias for `PUBLIC_BASE_URL` |
| `CALL_AUDIO_DIR` | no | Directory for cached call μ-law files (default `backend/call_audio/`). Files are gitignored. |
| `OPENAI_API_KEY` | no | Used after ElevenLabs when `openai` is installed |
| `WHISPER_MODEL` | no | Local openai-whisper model name (default `base`) |
| `NVIDIA_API_KEY` | no | When set, `parse_expense` calls `ai.categorize.categorize_expense` (NVIDIA Nemotron) and receipt **images** call `ai.receipt.categorize_receipt` (vision). Missing/failed text → heuristic parser. Images never invent cents (HTTP 400 if `amount_cents` is null). Also used for `/parse-limit`, over-limit, and weekly-summary phrasing. |
| `TZ` | no | Timezone for the weekly call hour (default `America/New_York`) |
| `WHEREISMYMONEY_DB` | no | Alternate SQLite path |

Missing Twilio keys: `place_call` returns `{ "ok": false }` and the API keeps serving.

### Hear Victoria on `/trigger-call` (re-test after the μ-law change)

Do this on a laptop with Twilio + ngrok. Do **not** place a real call from a cloud VM.

1. Set `ELEVENLABS_API_KEY` and Twilio keys in `.env`.
2. From `backend/`: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`.
3. In another terminal: `ngrok http 8000`.
4. Set `PUBLIC_BASE_URL=https://….ngrok-free.app` (the ngrok HTTPS origin, no trailing slash) and restart uvicorn so it picks up the env.
5. `POST /trigger-call` with `{ "kind": "weekly_summary" }` (or `{ "kind": "over_limit", "category": "Food" }`):

```bash
curl -s -X POST http://127.0.0.1:8000/trigger-call \
  -H 'Content-Type: application/json' \
  -d '{"kind":"weekly_summary"}'
```

6. Confirm the JSON `call` object has `"voice": "elevenlabs"` and a `twimlUrl` under your ngrok origin (`/twiml/play/{token}`), not `twimlets.com`.
7. Twilio fetches that TwiML, `<Play>`s `/call-audio/{token}.ulaw` (Victoria, `eleven_multilingual_v2`, `ulaw_8000`), then **hangs up**. Weekly summary speech lists this week's expenses in spoken USD (top 6 by amount if there are more, plus "and X more").
8. If ElevenLabs fails **or** `PUBLIC_BASE_URL` is unset, `place_call` falls back to the trial-safe Twimlets `message` URL (Twilio `<Say>`).

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
| `GET` | `/health` | `{ status, whisperStub, twilioConfigured, nemotronConfigured, receiptOcrEnabled, capabilities: { receiptOCR, voiceStt, nemotron } }`. `receiptOcrEnabled` / `capabilities.receiptOCR` are true when `NVIDIA_API_KEY` is set. |
| `POST` | `/log-expense` | `multipart/form-data`: `source=voice\|receipt`, optional `file`, optional `text`. Receipt images → Nemotron vision (`parse.engine=nemotron-vision`, `textEngine=receipt`) |
| `POST` | `/parse-limit` | JSON `{ text }` → `{ category, amount_cents, period, confidence, readyToSave }`. Does **not** save. If `readyToSave`, the app should `POST /limits` |
| `GET`/`POST` | `/limits` | `POST` body `{ category, limitCents }` (unchanged) |
| `GET`/`POST` | `/settings` | `POST` body `{ callDay, callHour, phoneNumber }` |
| `GET` | `/expenses` | Current week only |
| `POST` | `/trigger-call` | `{ kind, category?, phoneNumber? }`. Optional `phoneNumber` is a one-time E.164-ish override (min 8 digits). If omitted, dials saved settings / `MY_PHONE_NUMBER`. Weekly summary speech lists this week's expenses (merchant + spoken USD). More than 6 expenses → top 6 by amount plus "and X more". |
| `GET`/`POST` | `/twiml/play/{token}` | TwiML `<Play>` the cached μ-law file, then `<Hangup/>` |
| `GET` | `/call-audio/{token}.ulaw` | Cached ElevenLabs 8 kHz μ-law (`audio/x-mulaw`) Twilio fetches after `<Play>` |

Example without an audio file:

```bash
curl -s -X POST http://127.0.0.1:8000/log-expense \
  -F source=voice \
  -F 'text=spent fourteen bucks on lunch'
```

Receipt **image** (multipart field `file`). Uses Person C's vision model; HTTP 400 if the total cannot be read (no invented cents):

```bash
curl -s -X POST http://127.0.0.1:8000/log-expense \
  -F source=receipt \
  -F file=@sample_receipt.jpg
```

Spoken weekly limit (does not persist — follow with `POST /limits` when `readyToSave` is true):

```bash
curl -s -X POST http://127.0.0.1:8000/parse-limit \
  -H 'Content-Type: application/json' \
  -d '{"text":"cap my food spending at a hundred a week"}'
```

Voice file (multipart field `file`). **Live STT requires `WHISPER_STUB=0` and `ELEVENLABS_API_KEY`.** Expo sends `expense.m4a` (`audio/mp4`); a real m4a/mp3 is needed for Scribe. Response `parse.textEngine` is `elevenlabs` and `parse.engine` is `nemotron` when those keys are set. Transcribed text is stored on `expense.originalText`.

```bash
curl -s -X POST http://127.0.0.1:8000/log-expense \
  -F source=voice \
  -F file=@sample.m4a
```

Developer-tools one-time dial override (does not persist settings):

```bash
curl -s -X POST http://127.0.0.1:8000/trigger-call \
  -H 'Content-Type: application/json' \
  -d '{"kind":"weekly_summary","phoneNumber":"+14155550123"}'
```

## Nemotron (Person C)

`categorizer.parse_expense(text) -> ParsedExpense` is the **only** parse interface `main.py` uses.

1. Keep the `ParsedExpense` fields (`original_text`, `merchant`, `amount_cents`, `category`, `confidence`, `needs_review`).
2. When `NVIDIA_API_KEY` is set, the parser calls `ai.categorize.categorize_expense` (Person C's prompt is unchanged) and maps the dict onto `ParsedExpense`.
3. If Nemotron is down or the key is missing, the keyword heuristic still handles demo phrases.
4. If Nemotron returns `amount_cents: null` (it understood the text but not the money), `/log-expense` returns **HTTP 400** and does **not** insert a guessed amount. Cents stay integers.
5. Receipt **images** (`source=receipt` + image `file`) call `ai.receipt.categorize_receipt` (vision model `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`). `parse.engine` is `nemotron-vision` and `textEngine` is `receipt`. Images do **not** fall back to the text heuristic — null cents → HTTP 400 + `needs_review`.
6. `POST /parse-limit` calls `ai.spoken_limit.understand_spoken_limit` and returns Person C's dict. It does not write limits. When `readyToSave` is true, the app should `POST /limits` with `{ category, limitCents }`.
7. Over-limit Twilio speech uses `ai.overlimit_alert.overlimit_alert_sentence`. Weekly summary lists this week's expenses in spoken USD (`backend/weekly_summary.py`, cap 6 + "and X more"); it appends `ai.weekly_pattern.weekly_pattern_sentence` only when there is no expense list. Both keep the existing template if Nemotron fails.

Until a key is set, a keyword/amount heuristic handles phrases like:

- `spent fourteen bucks on lunch` → $14.00 Food
- `two fifty for the bus` → $2.50 Transport
- `thirty two forty five on groceries` → $32.45 Food
