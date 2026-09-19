import sys
import os

# allow importing from ai/ when running this script directly
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from ai.weekly_pattern import weekly_pattern_sentence
from ai.overlimit_alert import overlimit_alert_sentence
from ai.elevenlabs_tts import get_call_audio

# realistic demo numbers, matching §9's setup: Food at $99.95, limit $100
this_week = {"Food": 9995, "Transport": 4000, "Subscriptions": 1200, "Shopping": 0, "Bills": 15000, "Other": 300}
last_week = {"Food": 8500, "Transport": 4000, "Subscriptions": 1200, "Shopping": 0, "Bills": 15000, "Other": 300}

print("Generating weekly summary audio...")
weekly_sentence = weekly_pattern_sentence(this_week, last_week)
print(f"  sentence: {weekly_sentence!r}")
weekly_result = get_call_audio(weekly_sentence, "demo/weekly_summary_backup.mp3")
print(f"  result: {weekly_result}\n")

print("Generating over-limit alert audio...")
alert_sentence = overlimit_alert_sentence("Food", limit_cents=10000, over_by_cents=5)
print(f"  sentence: {alert_sentence!r}")
alert_result = get_call_audio(alert_sentence, "demo/overlimit_alert_backup.mp3")
print(f"  result: {alert_result}")