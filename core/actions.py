import os
import subprocess
import time
import webbrowser
from typing import List, Optional
import pyautogui
import pyperclip

from .failsafe import FailsafeController

class ActionExecutor:
    def __init__(self, failsafe: FailsafeController):
        self.failsafe = failsafe
        
    def _verify_safe(self):
        """Ensure no emergency stop has been triggered before executing an action."""
        self.failsafe.check_failsafe()

    # ---------- MOUSE ACTIONS ----------

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> str:
        self._verify_safe()
        self.failsafe.notify_agent_moved_mouse(x, y)
        pyautogui.moveTo(x, y, duration=0.25)
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        return f"Clicked ({button}) at ({x}, {y}) [x{clicks}]"

    def double_click(self, x: int, y: int) -> str:
        return self.click(x, y, button="left", clicks=2)

    def right_click(self, x: int, y: int) -> str:
        return self.click(x, y, button="right", clicks=1)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> str:
        self._verify_safe()
        self.failsafe.notify_agent_moved_mouse(start_x, start_y)
        pyautogui.moveTo(start_x, start_y, duration=0.2)
        self.failsafe.notify_agent_moved_mouse(end_x, end_y)
        pyautogui.dragTo(end_x, end_y, duration=duration, button="left")
        return f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"

    def scroll(self, amount: int) -> str:
        """Scrolls up (positive) or down (negative)."""
        self._verify_safe()
        pyautogui.scroll(amount)
        return f"Scrolled {'up' if amount > 0 else 'down'} by {abs(amount)}"

    # ---------- KEYBOARD ACTIONS ----------

    def type_text(self, text: str, use_clipboard: bool = True) -> str:
        """
        Types text safely. Using clipboard paste (ctrl+v) prevents keystroke drops,
        supports multi-line strings, and handles special symbols/emojis.
        """
        self._verify_safe()
        if use_clipboard:
            old_clipboard = ""
            try:
                old_clipboard = pyperclip.paste()
            except Exception:
                pass
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.1)
        else:
            pyautogui.write(text, interval=0.02)
        return f"Typed text: {repr(text)[:50]}"

    def press_key(self, key: str) -> str:
        self._verify_safe()
        pyautogui.press(key.lower())
        return f"Pressed key: {key}"

    def press_hotkey(self, keys: List[str]) -> str:
        self._verify_safe()
        normalized_keys = [k.lower().strip() for k in keys]
        pyautogui.hotkey(*normalized_keys)
        return f"Pressed hotkey: {'+'.join(normalized_keys)}"

    # ---------- OS FAST-PATH SHORTCUTS ----------

    def launch_app(self, app_name: str) -> str:
        """Launches an application and ensures it receives foreground focus."""
        self._verify_safe()
        clean_app = app_name.strip()
        try:
            # Win+R provides the most reliable Windows foreground focus for apps
            pyautogui.hotkey("win", "r")
            time.sleep(0.35)
            # Type app name safely
            pyperclip.copy(clean_app)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.1)
            pyautogui.press("enter")
            # Wait for app window to launch and take focus
            time.sleep(1.2)
            return f"Launched application: {clean_app}"
        except Exception as e:
            # Fallback to subprocess
            subprocess.Popen(clean_app, shell=True)
            time.sleep(1.2)
            return f"Launched {clean_app} via subprocess"

    def open_url(self, url: str) -> str:
        """Opens a web page directly in default browser."""
        self._verify_safe()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        webbrowser.open(url)
        return f"Opened URL in browser: {url}"

    def run_shell(self, command: str) -> str:
        """Executes a quick powershell command for system tasks."""
        self._verify_safe()
        res = subprocess.run(["powershell", "-Command", command], capture_output=True, text=True, timeout=10)
        output = (res.stdout or res.stderr).strip()
        return f"Executed command: {command} -> {output[:100]}"

    def wait(self, seconds: float) -> str:
        """Waits for specified duration, checking failsafe every 100ms."""
        start = time.time()
        while time.time() - start < seconds:
            self._verify_safe()
            time.sleep(0.1)
        return f"Waited {seconds}s"
