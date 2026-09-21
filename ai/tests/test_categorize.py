from ai.categorize import categorize_expense

test_cases = [
    "spent fourteen bucks on lunch",
    "fourteen fifty at the cafe",
    "got gas, forty bucks",
    "paid rent",
    "spent some money on stuff",
    "twelve oh one at the store",
    "14 on lunch and 20 on parking",
]

for text in test_cases:
    result = categorize_expense(text)
    print(f"{text!r}\n  → {result}\n")