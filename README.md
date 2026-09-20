# Where Is My Money

SteelHacks XIII — budgeting app that calls you on the phone.

- `app/` — Person A (Expo)
- `backend/` — Person B (FastAPI)
- `ai/` — Person C

Outbound Twilio calls play Person C's ElevenLabs **Victoria** voice when `ELEVENLABS_API_KEY` and `PUBLIC_BASE_URL` (your ngrok HTTPS origin) are set, then hang up. Weekly summary lists this week's expenses in spoken USD. `PUBLIC_BASE_URL` must be reachable by Twilio; without it, calls stay one-way Twimlets `<Say>`. Receipt photos use `ai.receipt.categorize_receipt` when `NVIDIA_API_KEY` is set (`/health` advertises `receiptOcrEnabled`). Voice uploads use ElevenLabs Scribe when `WHISPER_STUB=0` and `ELEVENLABS_API_KEY` are set. `POST /trigger-call` accepts an optional one-time `phoneNumber`. See `backend/README.md`.
