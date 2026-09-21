# Where Is My Money — Person A: wire Expo to Sebastian’s backend

Same Wi‑Fi. Sebastian’s API: `http://10.5.45.55:8000`

## 1. Run the app

```bash
git fetch origin
git switch feat/app   # or: git switch --track origin/feat/app
cd app
npm install
npx expo start
```

Open the QR in **Expo Go**. Phone + Sebastian’s Mac on the same Wi‑Fi.

## 2. Point at the backend

In `app/config.js`:

```js
export const API_BASE_URL = 'http://10.5.45.55:8000';
```

Phone sanity check (Safari): open `http://10.5.45.55:8000/health` — should show `"status":"ok"`.

## 3. Actually call the API (required — preview UI does nothing yet)

In `App.js` (or a small `api.js`), import the base URL and replace sample data.

### History tab — on mount

```js
import { API_BASE_URL } from './config';

const res = await fetch(`${API_BASE_URL}/expenses`);
const data = await res.json();
// use data.weekTotalCents, data.totalsByCategory, data.expenses
// expense fields: amount cents, category, original text, merchant, etc.
```

### Limits tab — load + save

```js
// load
const res = await fetch(`${API_BASE_URL}/limits`);
const { limits } = await res.json();

// save one category (cents = dollars * 100)
await fetch(`${API_BASE_URL}/limits`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ category: 'Food', limitCents: 5000 }),
});
```

### Settings (call day / hour / phone)

```js
await fetch(`${API_BASE_URL}/settings`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    callDay: 0,      // 0=Sun … 6=Sat
    callHour: 18,
    phoneNumber: '+1XXXXXXXXXX',
  }),
});
```

### Parse a spoken weekly limit (does not save)

```js
const res = await fetch(`${API_BASE_URL}/parse-limit`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ text: 'cap my food spending at a hundred a week' }),
});
const parsed = await res.json();
// parsed.category, parsed.amount_cents, parsed.period, parsed.confidence, parsed.readyToSave
// If parsed.readyToSave, then POST /limits with { category, limitCents: amount_cents }
```

### Trigger a weekly summary call (optional one-time number)

```js
await fetch(`${API_BASE_URL}/trigger-call`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ kind: 'weekly_summary', phoneNumber: '+1XXXXXXXXXX' }),
});
```

`phoneNumber` is optional. When set, the backend dials that number once and does not change saved Settings. Trial Twilio accounts can dial only verified numbers.

### Log a receipt photo

```js
const form = new FormData();
form.append('source', 'receipt');
form.append('file', { uri, name: 'receipt.jpg', type: 'image/jpeg' });

const res = await fetch(`${API_BASE_URL}/log-expense`, {
  method: 'POST',
  body: form,
});
// HTTP 400 if the vision model cannot read a total — do not invent cents
```

### Log expense (until mic works — text form field)

```js
const form = new FormData();
form.append('source', 'voice');
form.append('text', 'spent fourteen bucks on lunch');

const res = await fetch(`${API_BASE_URL}/log-expense`, {
  method: 'POST',
  body: form,
});
const data = await res.json();
// data.expense (first row, always present on success), data.expenses (all rows),
// data.limitCheck (one representative over-limit check for the batch)
```

## 4. Rules (don’t break these)

- Money = **integer cents** only (e.g. $14.00 → `1400`)
- Categories exactly: `Food`, `Transport`, `Subscriptions`, `Shopping`, `Bills`, `Other`
- No login — user is always `"demo"`
- Don’t put Twilio/API secrets in the app
- Only edit files under `app/`

## 5. Done when

1. History shows real data from `/expenses` (not the sample lunch/bus cards)
2. Setting a Food limit + logging an over-limit expense returns a `limitCheck` from the backend
3. Reload History and the new expense is there

If `/health` fails on the phone, you’re not on the same Wi‑Fi (or Sebastian’s uvicorn isn’t running).
