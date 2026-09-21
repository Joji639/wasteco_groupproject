import base64
import io
import json
import logging

from django.conf import settings
from PIL import Image
from openai import OpenAI

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = {"plastic", "e-waste", "neither"}

SYSTEM_PROMPT = (
    "You are a waste classifier for a waste-management app. Look at the photo and "
    "classify the main object into exactly one category:\n"
    "- plastic: plastic bottles, bags, containers, wrappers, packaging, other plastic items\n"
    "- e-waste: phones, batteries, chargers, cables, earphones, bulbs, electronic devices and parts\n"
    "- neither: anything else, or if the photo is unclear or shows no waste\n"
    'Return ONLY valid JSON, no extra text: {"category": "plastic|e-waste|neither", '
    '"percentage": <integer 0-100 showing how sure you are>, "item": "<short object name>"}'
)


def prepare_image(image_file):
    """Resize and encode image to base64 data URL."""
    img = Image.open(image_file)
    img = img.convert("RGB")

    w, h = img.size
    max_side = 1024
    if max(w, h) > max_side:
        ratio = max_side / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def call_groq(data_url):
    """Send image to Groq vision model and return raw response text."""

    api_key = getattr(settings, "GROQ_API_KEY", "")
    model = getattr(settings, "GROQ_MODEL", "qwen/qwen3.8-27b")
    if not model or "llama" in model or "meta-llama" in model or "preview" in model:
        model = "qwen/qwen3.8-27b"

    client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Classify this image."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    )
    return response.choices[0].message.content


def normalize_result(raw_text):
    """Parse model response into structured result dict."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[: -3].strip()

    result = json.loads(text)

    category = result.get("category", "neither")
    if category not in ALLOWED_CATEGORIES:
        category = "neither"

    try:
        percentage = int(result.get("percentage", 0))
    except (TypeError, ValueError):
        percentage = 0
    percentage = max(0, min(100, percentage))

    item = str(result.get("item", "unknown"))[:100]

    return {"category": category, "percentage": percentage, "item": item}
