from ai.spoken_limit import understand_spoken_limit

test_cases = [
    "cap my food spending at a hundred a week",
    "limit transport to fifty bucks",
    "I want to spend less this month",  # vague, no clear category or amount
    "no more than twenty five dollars on subscriptions",
]

for text in test_cases:
    result = understand_spoken_limit(text)
    print(f"{text!r}\n  → {result}\n")