# Where Is My Money

SteelHacks XIII — budgeting app that calls you on the phone.

- `app/` — Person A (Expo)
- `backend/` — Person B (FastAPI)
- `ai/` — Person C

Outbound Twilio calls play Person C's ElevenLabs **Victoria** voice when `ELEVENLABS_API_KEY` and `PUBLIC_BASE_URL` (your ngrok HTTPS origin) are set. See `backend/README.md`.
