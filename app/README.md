# Where Is My Money — Phone app

Expo SDK 57 frontend. Log (receipt photo / voice / text), History, Limits, and Settings talk to Person B’s backend via `config.js`. Developer tools can place a one-time summary call to the number you type (`triggerWeeklyCall(phoneNumber)`). Receipt photos upload even if `/health` has not advertised OCR yet. Voice recordings upload as `audio/mp4` m4a.

## Run it on your iPhone

1. Install Node.js LTS and Expo Go.
2. From the repository root, run:

   ```bash
   git fetch origin
   git switch feat/app
   cd app
   npm install
   npx expo start
   ```

3. Connect iPhone and laptop to the same Wi-Fi. Scan the QR code with the iPhone Camera and open it in Expo Go.
4. If the connection fails on the venue network, stop Expo with Ctrl+C and run `npx expo start --tunnel` instead.

If `git switch feat/app` says the local branch does not exist, run `git switch --track origin/feat/app`.

Only edit files inside `app/`. Do not place backend or AI credentials in this app. Person B's HTTPS backend address goes in `config.js` when provided.
