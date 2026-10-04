import base64
import io
from typing import Optional, Dict, Any
from PIL import Image
import httpx

from .config import config


class ScreenVision:
    """Uses a local Ollama vision model to describe the current desktop."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or config.vision_model
        self.client = httpx.Client(timeout=60.0)

    def describe(self, image: Image.Image) -> str:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=config.screenshot_quality, optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")

        prompt = """Describe this Windows desktop screenshot for a computer-use agent.
Identify the active app/window, important buttons, menus, text, forms, icons, dialogs, and anything that looks clickable.
Give approximate pixel coordinates for important targets using the screenshot's original coordinate system.
Do not invent UI elements that are not visible.
Be concise and factual. If the screen is a browser, identify the site and useful page controls."""

        payload = {
            "model": self.model_name,
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [encoded],
            }],
            "stream": False,
            "options": {"temperature": 0.1},
        }

        try:
            response = self.client.post(f"{config.ollama_base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "").strip()
            return content or "Vision model returned no description."
        except Exception as exc:
            return f"Vision unavailable: {exc}"
