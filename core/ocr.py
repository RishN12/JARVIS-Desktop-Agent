import asyncio
import io
import re
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image
from .screen import ScreenManager

try:
    import winrt.windows.media.ocr as ocr
    import winrt.windows.graphics.imaging as imaging
    import winrt.windows.storage.streams as streams
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


class WindowsOCR:
    def __init__(self):
        self.engine = None
        if HAS_OCR:
            try:
                self.engine = ocr.OcrEngine.try_create_from_user_profile_languages()
            except Exception:
                pass

    def is_available(self) -> bool:
        return self.engine is not None

    def read_screen_sync(self, image: Image.Image) -> List[Dict[str, Any]]:
        """Synchronously reads all text elements and their bounding boxes from an image."""
        if not self.is_available():
            return []
        return asyncio.run(self._recognize_async(image))

    async def _recognize_async(self, image: Image.Image) -> List[Dict[str, Any]]:
        buf = io.BytesIO()
        rgb_img = image.convert("RGB")
        rgb_img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        writer = streams.DataWriter()
        writer.write_bytes(raw_bytes)
        buffer = writer.detach_buffer()

        mem_stream = streams.InMemoryRandomAccessStream()
        await mem_stream.write_async(buffer)
        mem_stream.seek(0)

        decoder = await imaging.BitmapDecoder.create_async(mem_stream)
        soft_bmp = await decoder.get_software_bitmap_async()

        result = await self.engine.recognize_async(soft_bmp)
        
        elements = []
        for line in list(result.lines):
            line_text = line.text.strip()
            # Calculate line bounds
            words = list(line.words)
            if not words:
                continue
            first_rect = words[0].bounding_rect
            last_rect = words[-1].bounding_rect
            
            min_x = min(w.bounding_rect.x for w in words)
            min_y = min(w.bounding_rect.y for w in words)
            max_x = max(w.bounding_rect.x + w.bounding_rect.width for w in words)
            max_y = max(w.bounding_rect.y + w.bounding_rect.height for w in words)
            
            elements.append({
                "type": "line",
                "text": line_text,
                "x": int(min_x),
                "y": int(min_y),
                "width": int(max_x - min_x),
                "height": int(max_y - min_y),
                "center_x": int((min_x + max_x) / 2),
                "center_y": int((min_y + max_y) / 2),
            })
            
            for word in words:
                r = word.bounding_rect
                elements.append({
                    "type": "word",
                    "text": word.text.strip(),
                    "x": int(r.x),
                    "y": int(r.y),
                    "width": int(r.width),
                    "height": int(r.height),
                    "center_x": int(r.x + r.width / 2),
                    "center_y": int(r.y + r.height / 2),
                })

        return elements

    def find_text_coords(
        self,
        elements: List[Dict[str, Any]],
        search_query: str,
        case_sensitive: bool = False,
        exact: bool = False,
    ) -> Optional[Tuple[int, int]]:
        """
        Searches the extracted OCR elements for a matching phrase or button label.
        Returns the (x, y) center coordinates to click.
        """
        target = search_query.strip()
        if not case_sensitive:
            target = target.lower()

        # 1. First search full lines
        for el in elements:
            if el["type"] != "line":
                continue
            txt = el["text"] if case_sensitive else el["text"].lower()
            if exact and txt == target:
                return (el["center_x"], el["center_y"])
            elif not exact and target in txt:
                return (el["center_x"], el["center_y"])

        # 2. Then search words
        for el in elements:
            if el["type"] != "word":
                continue
            txt = el["text"] if case_sensitive else el["text"].lower()
            if exact and txt == target:
                return (el["center_x"], el["center_y"])
            elif not exact and target in txt:
                return (el["center_x"], el["center_y"])

        return None
