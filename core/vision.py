import base64
import io
import re
from typing import Optional
from PIL import Image
import httpx

from .config import config


class ScreenVision:
    """Uses a local Ollama vision model to describe the current desktop.

    Vision is deliberately semantic: OCR owns exact text and coordinates.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or config.vision_model
        self.client = httpx.Client(timeout=60.0)

    def _prepare_image(self, image: Image.Image) -> str:
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
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    @staticmethod
    def _clean_description(content: str) -> str:
        """Reject coordinate/bounding-box style output from the vision model."""
        text = (content or "").strip()

        # Moondream can sometimes answer an otherwise semantic prompt with a
        # point/box such as [0.0, 0.61, 0.99, 0.83]. That is not useful here.
        if re.fullmatch(
            r"[[(]?s*-?d+(?:.d+)?(?:s*,s*-?d+(?:.d+)?){1,5}s*[])]?",
            text,
        ):
            return ""

        return text

    def describe(self, image: Image.Image) -> str:
        encoded = self._prepare_image(image)

        # /api/generate is intentionally used here instead of /api/chat.
        # It is the simpler Ollama image-prompt path for the local Moondream
        # model and avoids the model treating the request as a point/box query.
        prompt = """Look at this screenshot of a Windows computer and describe what is visibly happening.
Give a short natural-language description for another AI that needs to operate the computer.
Mention the active application/window, important visible controls, dialogs, pages, and obvious UI state.
If an application is open, name it.
If a browser is open, name the site/page when visible.
Do NOT return coordinates, bounding boxes, numbers-only answers, JSON, or coordinate arrays.
Do NOT guess. Only describe things that are actually visible."""

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "images": [encoded],
            "stream": False,
            "options": {
                "temperature": 0.0,
            },
        }

        try:
            response = self.client.post(
                f"{config.ollama_base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = self._clean_description(data.get("response", ""))
            if content:
                return content
            return "Vision returned no usable semantic description."
        except Exception as exc:
            return f"Vision unavailable: {exc}"
