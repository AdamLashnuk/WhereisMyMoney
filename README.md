# Where Is My Money

A budgeting app that calls you on the phone.

Built at SteelHacks XIII · 24 hours · 3 people

---

## What it does

Say "spent fourteen bucks on lunch" into your phone, or snap a photo of a receipt. The app
figures out the amount and the category on its own and saves it. You never type anything.

Then two things happen on their own:

- **On the day you choose**, the app calls your phone and reads you a short summary of the
  week's spending.
- **The moment you go over a spending limit you set, it calls you.** Even one cent over the
  limit, and the phone rings.

Nobody's problem is a lack of budgeting apps. The problem is nobody opens them. A phone call
is the one notification you can't ignore.

---

## How it works

```
PHONE APP  →  BACKEND  →  AI SERVICES  →  📞 phone rings
```

| Piece | What it does |
|---|---|
| **Phone app** (React Native / Expo) | Record voice, snap receipts, set limits, pick call day, view history |
| **Backend** (FastAPI) | Receives uploads, saves to database, checks limits, places calls |
| **AI layer** | Turns messy input into structured data, and structured data into a natural-sounding phone call |

### AI services used

- **[NVIDIA Nemotron](https://build.nvidia.com)** — reads spoken or photographed expense
  text and returns structured data: amount, category, confidence. Also understands spoken
  spending limits and notices weekly spending patterns. A vision-capable Nemotron model
  (Nemotron 3 Nano Omni) reads receipt photos directly.
- **[ElevenLabs](https://elevenlabs.io)** — turns written summaries and alerts into natural
  spoken audio for the phone calls.
- **[Twilio](https://www.twilio.com)** — places the actual phone calls and plays the audio.

Nemotron never talks to the user directly. It reads messy input and returns tidy data —
every decision about whether to place a call is ordinary arithmetic in the backend, not a
model's judgment call.

---

## Project structure

```
WhereisMyMoney/
├── CONTRACT.md       ← the shared agreement all three parts build against
├── app/              ← the phone app
├── backend/          ← the server, database, call logic
├── ai/               ← Nemotron + ElevenLabs integration
│   ├── nemotron.py           reusable request wrapper (retries, JSON cleanup)
│   ├── categorize.py         job 1 — categorize a voice-logged expense
│   ├── receipt.py            job 1b — categorize a photographed receipt
│   ├── weekly_pattern.py     job 2 — one sentence about a weekly spending pattern
│   ├── overlimit_alert.py    the over-limit alert script
│   ├── spoken_limit.py       job 3 — understand a spoken spending limit
│   ├── elevenlabs_tts.py     job 4 — text-to-speech, with a fallback path
│   └── tests/                test scripts for each piece above
└── demo/             ← backup audio and demo setup, generated ahead of judging
```

---

## Setup

Each part of the app has its own setup — see the folder for details. In short:

1. Clone the repo and check out `main`.
2. Copy `.env.example` to `.env` and fill in your own API keys:
   - `NVIDIA_API_KEY` — from [build.nvidia.com](https://build.nvidia.com)
   - `ELEVENLABS_API_KEY` — from [elevenlabs.io](https://elevenlabs.io)
   - `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` — from your Twilio dashboard
   - `MY_PHONE_NUMBER` — your own verified number (Twilio trial accounts can only call verified numbers)
3. Install dependencies for whichever part you're running (see `ai/`, `backend/`, and `app/`
   for their own requirements).
4. Run the backend, then the app, pointing the app at the backend's address.

---

## Rules this app follows

- Money is always whole cents, as a whole number. Never a decimal.
- There are exactly six categories: Food, Transport, Subscriptions, Shopping, Bills, Other.
- Going over a limit by even one cent triggers a call — no grace zone, no warning tier.
- No login. There's one user.
- The original words behind every expense are kept forever, so every number traces back to
  something the user actually said or a receipt actually showed.

Full details are in [`CONTRACT.md`](./CONTRACT.md).
