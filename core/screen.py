import base64
import io
import time
from typing import Tuple, Optional, Dict, Any
from PIL import Image, ImageGrab, ImageDraw

# Try importing win32 modules for proper input desktop attachment
try:
    import win32service
    import win32con
    import win32gui
    import win32api
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


class ScreenManager:
    def __init__(self):
        self._ensure_desktop_attached()
        self.virtual_screen_bounds = self.get_virtual_screen_bounds()

    def _ensure_desktop_attached(self):
        """Attach current thread to the active user desktop for reliable grabbing."""
        if HAS_WIN32:
            try:
                hdesk = win32service.OpenInputDesktop(0, False, win32con.MAXIMUM_ALLOWED)
                hdesk.SetThreadDesktop()
            except Exception:
                pass

    def get_virtual_screen_bounds(self) -> Dict[str, int]:
        """Returns the bounding box of the virtual desktop across all monitors."""
        if HAS_WIN32:
            try:
                left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
                top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
                width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
                height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
                return {"left": left, "top": top, "width": width, "height": height}
            except Exception:
                pass
        return {"left": 0, "top": 0, "width": 1920, "height": 1080}

    def capture_screen(self, all_screens: bool = True) -> Image.Image:
        """Takes a full-resolution screenshot of the desktop."""
        self._ensure_desktop_attached()
        try:
            img = ImageGrab.grab(all_screens=all_screens)
            return img
        except Exception as e:
            # Fallback for some DPI configs
            time.sleep(0.1)
            self._ensure_desktop_attached()
            return ImageGrab.grab(all_screens=False)

    def prepare_for_model(
        self,
        image: Image.Image,
        max_width: int = 1280,
        max_height: int = 720,
    ) -> Tuple[Image.Image, float, float]:
        """
        Resizes the screenshot to fit within max dimensions while preserving aspect ratio.
        Returns: (resized_image, scale_x, scale_y)
        scale_x = original_width / resized_width
        So: original_coord = model_coord * scale
        """
        orig_w, orig_h = image.size
        ratio = min(max_width / orig_w, max_height / orig_h, 1.0)
        new_w = int(orig_w * ratio)
        new_h = int(orig_h * ratio)

        resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        scale_x = orig_w / new_w
        scale_y = orig_h / new_h
        return resized, scale_x, scale_y

    def image_to_base64(self, image: Image.Image, quality: int = 80) -> str:
        """Converts PIL Image to base64 JPEG string."""
        buf = io.BytesIO()
        rgb_img = image.convert("RGB")
        rgb_img.save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def annotate_target(self, image: Image.Image, x: int, y: int, label: str = "") -> Image.Image:
        """Draws a red target indicator where an action will occur."""
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)
        radius = 12
        # Target circle with outline
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline="red", width=3)
        draw.line((x - radius - 6, y, x + radius + 6, y), fill="red", width=2)
        draw.line((x, y - radius - 6, x, y + radius + 6), fill="red", width=2)
        if label:
            draw.rectangle((x + 15, y - 10, x + 15 + len(label) * 8, y + 12), fill="black")
            draw.text((x + 18, y - 8), label, fill="white")
        return annotated
