# CONTRACT.md

The source of truth for how the three parts of this project talk to each other.
Changed ONLY in a 3-person sync — if something here needs to change, stop and talk to the other two first.

---

## Rules everyone follows

- **Money is always whole cents, as a number.** Fourteen dollars is `1400`, never `14.00`.
- **There are exactly six categories.** Food, Transport, Subscriptions, Shopping, Bills, Other. Nothing invents a seventh.
- **Over the limit means over the limit.** One cent over triggers a call. No grace zone, no warning tier, no text-instead-of-call.
- **No login.** Everyone is user `"demo"`.
- **Keep the original text forever.** Whatever Whisper heard, or whatever the receipt said, gets saved alongside the expense.

---

## What the backend offers

```
POST  /log-expense     send a voice recording or a receipt photo
                       → get back the expense it figured out,
                         plus whether it triggered a call

POST  /thresholds      set a spending limit for a category

GET   /thresholds      read back all six limits

POST  /settings        set which day and hour to receive the
                       weekly summary call

GET   /settings        read back the current call day and hour

GET   /expenses        get this week's expenses and totals

POST  /trigger-call    make a call happen right now
                       (for demoing — we don't wait for the real day)
```

---

## What an expense looks like

```
the original text        ("spent fourteen bucks on lunch")
where it came from       (voice or receipt)
the merchant             (may be blank)
the amount, in cents     (1400)
the category             (Food)
how confident we are     (0 to 1)
needs a human check?     (true if confidence is low)
when it happened
```

---

## What comes back when you go over a limit

```
which category
the week's total so far
the limit
how far over, in cents    (could be 1)
what we did about it      (placed a call / nothing, already called
                           for this category this week)
```

---

## What the settings look like

```
which day of the week     (0 = Sunday through 6 = Saturday)
what hour                 (0-23, local time)
the phone number to call
```

Default it to Sunday at 6pm so the app works before anyone touches settings.

---

## Who owns what

```
app/         ← Person A only
backend/     ← Person B only
ai/          ← Person C only
```

If a file isn't in your folder, you don't touch it. Need something from another folder? Import it, don't edit it — message the owner instead.

---

## Branches

```
main
 ├── feat/app        ← Person A
 ├── feat/backend    ← Person B
 └── feat/ai         ← Person C
```

Integrator: **[fill in who]** — merges everyone's working code into `main` every ~2 hours.
