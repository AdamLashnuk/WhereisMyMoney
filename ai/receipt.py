from dotenv import load_dotenv
import os
import json
import base64
import time
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ["NVIDIA_API_KEY"]
)

VISION_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

SYSTEM_PROMPT = """You are an expense categorizer for a budgeting app. You are shown a \
photo of a receipt and return structured data about the purchase. You never talk to the \
user — only return JSON.

Respond with ONLY a JSON object, no markdown fences, no commentary:

{
  "merchant": string or null,
  "amount_cents": integer or null,
  "category": one of "Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other",
  "confidence": float from 0 to 1,
  "needs_review": boolean
}

Rules:
- IMPORTANT: grab the receipt's TOTAL amount, never a single line item. Receipts often \
list several items before the total — always use the final total, including tax and tip \
if shown.
- Amount is always whole cents as an integer. $14.00 is 1400.
- category must be exactly one of the six listed. Never invent a new one.
- needs_review must be true whenever confidence is below 0.6, the image is blurry/unclear, \
or you can't confidently locate a total.
- Never guess a plausible-sounding amount you're not confident about — getting this wrong \
decides whether a phone call fires.
- Do not think out loud, do not explain your reasoning, do not show your work. Output the \
JSON object and nothing else, immediately.
"""


def _encode_image(image_path):
    """Read a local image file and return it as a base64 data URI."""
    ext = image_path.rsplit(".", 1)[-1].lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _clean_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def categorize_receipt(image_path):
    """
    Takes a path to a local receipt photo, returns a dict matching the expense shape
    from CONTRACT.md. Retries once, falls back to a flagged review state if the
    vision model fails or the image can't be parsed — never crashes the server.
    """
    data_uri = _encode_image(image_path)
    last_error = None

    for attempt in range(2):
        raw = None
        try:
            response = client.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Read this receipt and return the JSON."},
                            {"type": "image_url", "image_url": {"url": data_uri}}
                        ]
                    }
                ],
                temperature=0,
                max_tokens=500,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}}
            )
            raw = response.choices[0].message.content
            cleaned = _clean_json_response(raw)
            result = json.loads(cleaned)
            break
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            last_error = e
            print(f"[receipt] attempt {attempt + 1} failed to parse: {e}")
            print(f"[receipt] raw response was: {raw!r}")
            result = None
        except Exception as e:
            last_error = e
            print(f"[receipt] attempt {attempt + 1} API call failed: {e}")
            result = None

        if attempt == 0:
            time.sleep(1)

    if result is None:
        return {
            "original_text": f"[receipt photo: {image_path}]",
            "merchant": None,
            "amount_cents": None,
            "category": "Other",
            "confidence": 0.0,
            "needs_review": True
        }

    category = result.get("category")
    valid_categories = {"Food", "Transport", "Subscriptions", "Shopping", "Bills", "Other"}
    if category not in valid_categories:
        category = "Other"

    return {
        "original_text": f"[receipt photo: {image_path}]",
        "merchant": result.get("merchant"),
        "amount_cents": result.get("amount_cents"),
        "category": category,
        "confidence": result.get("confidence", 0.0),
        "needs_review": result.get("needs_review", True)
    }