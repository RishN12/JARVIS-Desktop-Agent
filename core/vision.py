import base64
import io
import re
from typing import Optional
from PIL import Image
import httpx

from .config import config


class ScreenVision:
    """Optional semantic screen vision using a local Ollama vision model."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or config.vision_model
        self.client = httpx.Client(timeout=45.0)

    def _prepare_image(self, image: Image.Image) -> str:
        prepared = image.convert("RGB")
        prepared.thumbnail(
            (config.screenshot_max_width, config.screenshot_max_height),
            Image.Resampling.LANCZOS,
        )
        buf = io.BytesIO()
        prepared.save(buf, format="JPEG", quality=config.screenshot_quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    @staticmethod
    def _clean_description(content: str) -> str:
        text = (content or "").strip()
        coordinate_pattern = (
            r"(?:\[\s*|\(\s*)?"
            r"-?\d+(?:\.\d+)?"
            r"(?:\s*,\s*-?\d+(?:\.\d+)?){1,5}"
            r"(?:\s*\]|\s*\))?"
        )
        if re.fullmatch(coordinate_pattern, text):
            return ""
        return text

    def describe(self, image: Image.Image) -> str:
        if not config.vision_enabled:
            return "Vision disabled: using OCR and Windows window information."

        encoded = self._prepare_image(image)
        prompt = """Describe this Windows desktop screenshot for a computer-use agent.
Identify the active app/window and important visible UI elements, dialogs, buttons,
menus, pages, and obvious state changes. Use short natural language.
Do not return coordinates, bounding boxes, JSON, coordinate arrays, or numbers-only output.
Do not guess. Only describe what is visibly supported by the screenshot."""

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "images": [encoded],
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0.0},
        }

        try:
            response = self.client.post(
                f"{config.ollama_base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = self._clean_description(data.get("response", ""))
            return content or "Vision returned no usable semantic description."
        except Exception as exc:
            return f"Vision unavailable: {exc}"
