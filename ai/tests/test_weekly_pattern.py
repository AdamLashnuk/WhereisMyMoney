from ai.weekly_pattern import weekly_pattern_sentence

test_cases = [
    # a clear spike in one category
    (
        {"Food": 8500, "Transport": 4000, "Subscriptions": 1200, "Shopping": 0, "Bills": 15000, "Other": 300},
        {"Food": 8500, "Transport": 4000, "Subscriptions": 1200, "Shopping": 12000, "Bills": 15000, "Other": 300}
    ),
    # roughly the same as last week
    (
        {"Food": 8000, "Transport": 4000, "Subscriptions": 1200, "Shopping": 0, "Bills": 15000, "Other": 300},
        {"Food": 8200, "Transport": 3900, "Subscriptions": 1200, "Shopping": 0, "Bills": 15000, "Other": 250}
    ),
    # a category that went from zero to something
    (
        {"Food": 8000, "Transport": 4000, "Subscriptions": 1200, "Shopping": 0, "Bills": 15000, "Other": 0},
        {"Food": 8000, "Transport": 4000, "Subscriptions": 1200, "Shopping": 0, "Bills": 15000, "Other": 5000}
    ),
]

for this_week, last_week in test_cases:
    sentence = weekly_pattern_sentence(this_week, last_week)
    print(f"{sentence!r}  ({len(sentence.split())} words)\n")