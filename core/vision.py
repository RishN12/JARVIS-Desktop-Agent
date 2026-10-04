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
        # Keep vision input within a predictable size. OCR separately receives
        # the original screenshot for accurate text coordinates.
        prepared = image.convert("RGB")
        prepared.thumbnail(
            (config.screenshot_max_width, config.screenshot_max_height),
            Image.Resampling.LANCZOS,
        )
        buf = io.BytesIO()
        prepared.save(
            buf,
            format="JPEG",
            quality=config.screenshot_quality,
            optimize=True,
        )
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")

        prompt = """Describe this Windows desktop screenshot for a computer-use agent.
Identify the active app/window, important buttons, menus, text, forms, icons, dialogs, and anything that looks clickable.
Do not output bounding boxes, coordinate arrays, or raw coordinate lists.
Focus on semantic visual information: active app/window, visible controls, layout,
dialogs, icons, forms, and what appears clickable.
Do not invent UI elements that are not visible.
Be concise and factual. If the screen is a browser, identify the site and useful page controls.
Text coordinates are supplied separately by OCR, so do not guess coordinates."""

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
