from dotenv import load_dotenv
import os
import json
import time
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ["NVIDIA_API_KEY"]
)

MODEL = "nvidia/nemotron-3-super-120b-a12b"


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
    last_error = None

    for attempt in range(2):
        raw = None
        try:
            response = client.chat.completions.create(
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
