# CONTRACT

Money is always whole cents (integers). Exactly six categories: Food, Transport, Subscriptions, Shopping, Bills, Other. Over limit by any amount triggers a call. No login — user is `"demo"`. Keep original text forever.

## Endpoints

- `POST /log-expense` — voice or receipt → expense + limit check
- `POST /limits` / `GET /limits`
- `POST /settings` / `GET /settings`
- `GET /expenses`
- `POST /trigger-call`
- `GET`/`POST` `/twiml/play/{token}` — TwiML `<Play>` for Twilio outbound calls
- `GET /call-audio/{token}.mp3` — cached ElevenLabs mp3
