# Where Is My Money

**SteelHacks XIII** — a budgeting app that logs spend by **voice or receipt photo**, then **calls your phone** when you blow a weekly category limit or for a spoken weekly summary.

> Nobody’s problem is a lack of budgeting apps. The problem is nobody opens them. A phone call is hard to ignore.

**Repo:** [github.com/AdamLashnuk/WhereisMyMoney](https://github.com/AdamLashnuk/WhereisMyMoney)

---

## What it does

1. **Log** — speak expenses (“twelve dollars on drinks and five hundred on groceries”) or snap a receipt.
2. **Understand** — ElevenLabs Scribe turns speech into text; NVIDIA Nemotron pulls amount, merchant, and category (and reads receipt photos with vision). One voice clip can become **multiple** ledger rows.
3. **Track** — FastAPI + SQLite stores integer **cents** across six categories: Food, Transport, Subscriptions, Shopping, Bills, Other. No login — everyone is user `"demo"`.
4. **Interrupt** — go one cent over a weekly category limit → **Twilio** places a call with ElevenLabs **Victoria** TTS. End of week → call reads back top purchases in spoken USD, then hangs up.

---

## Architecture

```
Expo app (mic · camera · limits · history)
        │
        ▼
FastAPI backend (ledger · limits · calls · /health)
        │
        ├── ElevenLabs Scribe     voice → text
        ├── NVIDIA Nemotron       text/receipt → amount + category
        ├── ElevenLabs Victoria   text → telephony μ-law audio
        └── Twilio                dials the phone · plays audio
```

| Folder | Owner (hackathon) | Role |
|--------|-------------------|------|
| `app/` | Person A | Expo Go frontend |
| `backend/` | Person B | FastAPI API, SQLite, Twilio orchestration |
| `ai/` | Person C | Nemotron, ElevenLabs TTS helpers, spoken money |
| `CONTRACT.md` | shared | API + money rules — source of truth |

Shared rules (see `CONTRACT.md`): money is always whole cents; exactly six categories; over limit by any amount triggers a call; keep original transcript/receipt text forever.

---

## Quick start

### 1. Clone and env

```bash
git clone https://github.com/AdamLashnuk/WhereisMyMoney.git
cd WhereisMyMoney
cp .env.example backend/.env   # or repo-root .env — fill in keys below
```

Never commit real keys. Useful variables:

| Variable | Purpose |
|----------|---------|
| `NVIDIA_API_KEY` | Nemotron categorize + receipt vision + spoken limits |
| `ELEVENLABS_API_KEY` | Scribe STT + Victoria TTS on calls |
| `WHISPER_STUB` | `0` for live STT; `1` forces a demo stub phrase |
| `TWILIO_*` / `MY_PHONE_NUMBER` | Outbound calls |
| `PUBLIC_BASE_URL` | ngrok HTTPS origin so Twilio can fetch TwiML/audio |

Full notes: `backend/README.md`.

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r ../ai/requirements.txt   # Pillow, etc. for receipt vision
WHISPER_STUB=0 uvicorn main:app --host 0.0.0.0 --port 8000
```

- Docs: http://127.0.0.1:8000/docs  
- Health: http://127.0.0.1:8000/health  

### 3. Public URL for Twilio (optional but needed for Victoria audio)

```bash
ngrok http 8000
# set PUBLIC_BASE_URL=https://….ngrok-free.app  (no trailing slash)
# restart uvicorn so it picks up the env
```

Without `PUBLIC_BASE_URL`, calls fall back to trial-safe Twimlets `<Say>`.

### 4. Expo app

```bash
cd app
npm install
# edit config.js → API_BASE_URL = 'http://<your-lan-ip>:8000'
# or your ngrok HTTPS origin if the phone is off your LAN
npx expo start -c
```

Open in **Expo Go** on a phone on the same Wi‑Fi (or use the tunnel). Person A integration notes: `PERSON_A_INTEGRATION.md`.

---

## Demo checklist

1. Set a low **Food** weekly limit in the app (`POST /limits` or UI).
2. Log a voice expense or receipt that pushes Food over the limit → phone rings.
3. Log several spends (or a multi-item voice list) → `POST /trigger-call` with `{ "kind": "weekly_summary" }` → call lists top purchases in spoken dollars, then hangs up.
4. Optional one-time override: `{ "kind": "over_limit", "category": "Food", "phoneNumber": "+1…" }`.

Twilio **trial** accounts can only call/text **verified** numbers until you upgrade.

---

## API (short)

| Method | Path | Notes |
|--------|------|--------|
| `POST` | `/log-expense` | Voice or receipt → `expense` + `expenses[]` (multi-item voice) + limit checks |
| `GET` | `/expenses` | This week’s ledger + totals |
| `GET`/`POST` | `/limits` | Per-category weekly limits (cents) |
| `GET`/`POST` | `/settings` | Call day/hour + phone number |
| `POST` | `/parse-limit` | Spoken limit → category + cents (does not save) |
| `POST` | `/trigger-call` | `weekly_summary` or `over_limit` |
| `GET` | `/health` | Capabilities: receipt OCR, voice STT, Nemotron, Twilio |
| `GET`/`POST` | `/twiml/play/{token}` | TwiML `<Play>` then hang up |
| `GET` | `/call-audio/{token}.ulaw` | Cached Victoria μ-law for Twilio |

---

## Tech stack

- **Mobile:** Expo / React Native  
- **API:** FastAPI, SQLite  
- **STT:** ElevenLabs Scribe (`scribe_v2`)  
- **LLM / vision:** NVIDIA Nemotron (categorize + receipt OCR)  
- **TTS:** ElevenLabs Victoria → `ulaw_8000` for telephony  
- **Calls:** Twilio Programmable Voice  

---

## Team

Built at SteelHacks XIII by a three-person team (frontend / backend / AI) against a shared `CONTRACT.md`.

---

## License

Hackathon project — see repository owners for reuse.
