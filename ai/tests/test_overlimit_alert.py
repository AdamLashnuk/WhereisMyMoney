from ai.overlimit_alert import overlimit_alert_sentence

test_cases = [
    ("Food", 10000, 5),        # the famous 5-cent overage from the demo script
    ("Transport", 20000, 150), # $1.50 over
    ("Bills", 50000, 1),       # the 1-cent edge case
]

for category, limit_cents, over_by_cents in test_cases:
    sentence = overlimit_alert_sentence(category, limit_cents, over_by_cents)
    word_count = len(sentence.split())
    print(f"{sentence!r}  ({word_count} words)\n")