from dotenv import load_dotenv
import os
import json
import time

load_dotenv()

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/nemotron-3-super-120b-a12b"

_client = None


def nvidia_api_key():
    """Return NVIDIA_API_KEY or None. Never raises on a missing key."""
    key = os.getenv("NVIDIA_API_KEY")
    if key is None:
        return None
    key = str(key).strip()
    return key or None


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
    Retries once on ANY failure — parse error, API error, timeout — before giving up.
    Returns None if both attempts fail; caller is responsible for flagging that
    expense for human review, not crashing.
    """
    if not nvidia_api_key():
        print("[nemotron] NVIDIA_API_KEY is not set; skipping API call")
        return None

    last_error = None

    for attempt in range(2):
        raw = None
        try:
            response = _get_client().chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0,       # reproducible answers — judges run the demo twice
                max_tokens=max_tokens,
                extra_body={
                    "chat_template_kwargs": {
                        "enable_thinking": False,
                        "force_nonempty_content": True
                    }
                }
            )
            raw = response.choices[0].message.content
            cleaned = _clean_json_response(raw)
            return json.loads(cleaned)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            last_error = e
            print(f"[nemotron] attempt {attempt + 1} failed to parse: {e}")
            print(f"[nemotron] raw response was: {raw!r}")
        except Exception as e:
            last_error = e
            print(f"[nemotron] attempt {attempt + 1} API call failed: {e}")

        if attempt == 0:
            time.sleep(1)  # brief pause before retrying, helps with transient 503s

    print(f"[nemotron] both attempts failed, giving up. Last error: {last_error}")
    return None
