from dotenv import load_dotenv
import os
import json
import time

load_dotenv()

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_RETRIES = 1
TEXT_TIMEOUT_S = 25.0

_client = None


def nvidia_api_key():
    """Return NVIDIA_API_KEY or None. Never raises on a missing key."""
    key = os.getenv("NVIDIA_API_KEY")
    if key is None:
        return None
    key = str(key).strip()
    return key or None


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(lo, min(hi, value))


def _nemotron_attempts() -> int:
    """API attempts. Default 1; set NEMOTRON_RETRIES=2 for one parse retry."""
    return _int_env("NEMOTRON_RETRIES", DEFAULT_RETRIES, 1, 3)


def _get_client():
    """Build the OpenAI-compatible NVIDIA client on first use."""
    global _client
    if _client is not None:
        return _client
    api_key = nvidia_api_key()
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set")
    from openai import OpenAI

    _client = OpenAI(
        base_url=NVIDIA_BASE_URL,
        api_key=api_key,
        timeout=TEXT_TIMEOUT_S,
    )
    return _client


def _clean_json_response(text):
    """Strip markdown code fences and whitespace the model sometimes adds around JSON."""
    text = text.strip()
    if text.startswith("```"):
        # remove the opening fence (```json or ```)
        text = text.split("\n", 1)[1] if "\n" in text else text
        # remove the closing fence
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def ask_nemotron_json(system_prompt, user_message, max_tokens=600):
    """
    Send one request to Nemotron and get back parsed JSON.

    Default is a single attempt (``NEMOTRON_RETRIES=1``). A second attempt runs
    only on JSON parse errors when retries >= 2 — no 1s sleep. Returns None if
    attempts fail; caller flags the expense for review instead of crashing.
    """
    if not nvidia_api_key():
        print("[nemotron] NVIDIA_API_KEY is not set; skipping API call")
        return None

    last_error = None
    attempts = _nemotron_attempts()
    api_ms_total = 0.0

    for attempt in range(attempts):
        raw = None
        try:
            started = time.perf_counter()
            response = _get_client().chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0,       # reproducible answers — judges run the demo twice
                max_tokens=max_tokens,
                timeout=TEXT_TIMEOUT_S,
                extra_body={
                    "chat_template_kwargs": {
                        "enable_thinking": False,
                        "force_nonempty_content": True
                    }
                }
            )
            api_ms = (time.perf_counter() - started) * 1000
            api_ms_total += api_ms
            print(f"[nemotron] api {api_ms:.0f}ms attempt={attempt + 1}/{attempts}")
            raw = response.choices[0].message.content
            cleaned = _clean_json_response(raw)
            parsed = json.loads(cleaned)
            print(f"[nemotron] done api_ms={api_ms_total:.0f}")
            return parsed
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            last_error = e
            print(f"[nemotron] attempt {attempt + 1} failed to parse: {e}")
            print(f"[nemotron] raw response was: {raw!r}")
        except Exception as e:
            last_error = e
            print(f"[nemotron] attempt {attempt + 1} API call failed: {e}")
            break

    print(f"[nemotron] giving up after {attempts} attempt(s) api_ms={api_ms_total:.0f}. Last error: {last_error}")
    return None
