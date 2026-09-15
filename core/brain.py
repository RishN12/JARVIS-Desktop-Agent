import json
import re
import time
from typing import Dict, Any, List, Optional
import httpx

from .config import config

try:
    import win32service
    import win32con
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


SYSTEM_PROMPT = """You are an Autonomous Windows Desktop Agent. Your ONLY job is to accomplish the user's goal by deciding the NEXT single action.

CRITICAL RULES:
1. NEVER repeat an action that already succeeded. If a step says "Typed text", "Launched", "Clicked" etc. in history - that step is DONE. Do NOT do it again.
2. Once ALL parts of the goal are complete, you MUST output action "done". Do NOT continue acting after a goal is satisfied.
3. Think carefully about what has already happened from the history. Only decide on the very NEXT thing that hasn't been done yet.
4. If you just launched an app and it shows in "Open Windows", it is open. Proceed to interact with it.
5. If typing text was already completed (shown in history), do NOT type again. Call "done" if the overall goal is met.

Always output ONLY strictly valid JSON with this structure - no markdown, no extra text:
{
  "thought": "<what has been done so far and what specifically needs to happen next>",
  "action": "<action_name>",
  "params": { ... }
}

AVAILABLE ACTIONS:
1. open_url
   params: {"url": "https://example.com"}
2. launch_app - Use Win+R to open any app by name
   params: {"app": "notepad"} or {"app": "chrome"} or {"app": "calc"} or {"app": "spotify"}
3. click_text - Uses OCR to find and click any visible text/button/link on screen. PREFER this over blind coordinates.
   params: {"text": "Sign In"} or {"text": "Compose"} or {"text": "OK"}
4. click - Click at exact coordinates
   params: {"x": 500, "y": 300, "button": "left"}
5. double_click
   params: {"x": 500, "y": 300}
6. right_click
   params: {"x": 500, "y": 300}
7. type - Types text using clipboard paste. Fast and unicode-safe.
   params: {"text": "hello world"}
8. press_key
   params: {"key": "enter"} or {"key": "tab"} or {"key": "esc"} or {"key": "backspace"}
9. hotkey
   params: {"keys": ["ctrl", "s"]} or {"keys": ["ctrl", "a"]} or {"keys": ["alt", "tab"]}
10. scroll
    params: {"amount": -300} (negative=down, positive=up)
11. wait - Wait for UI to settle
    params: {"seconds": 1.5}
12. shell - Run a PowerShell command
    params: {"command": "Get-Process"}
13. done - CALL THIS when the goal is fully complete. Required - do not loop forever.
    params: {"summary": "what was accomplished"}
14. fail - Call if you are completely stuck and cannot proceed.
    params: {"reason": "why you cannot proceed"}

DECISION GUIDELINES:
- Step 1 of any task: open the app or URL needed.
- Step 2 after launching: wait 1-2 seconds for it to load.
- Step 3+: interact (click, type, press keys etc).
- Final step: once everything in the goal is done, call "done".
- Typing already done? Don't retype. App already open? Don't relaunch.
"""


class AgentBrain:
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or config.default_planner_model
        self.client = httpx.Client(timeout=50.0)

    def get_open_windows(self) -> List[str]:
        """Returns titles of visible top-level windows on the active desktop."""
        windows = []
        if HAS_WIN32:
            try:
                hdesk = win32service.OpenInputDesktop(0, False, win32con.MAXIMUM_ALLOWED)
                hdesk.SetThreadDesktop()

                def _enum_cb(hwnd, _):
                    if win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd).strip()
                        if title and len(title) > 1:
                            rect = win32gui.GetWindowRect(hwnd)
                            w = rect[2] - rect[0]
                            h = rect[3] - rect[1]
                            if w > 50 and h > 50:
                                windows.append(title)

                win32gui.EnumWindows(_enum_cb, None)
            except Exception:
                pass
        return windows[:12]

    def _build_history_summary(self, history: List[Dict[str, Any]]) -> str:
        """Builds a clean, readable summary of completed actions."""
        if not history:
            return "No actions taken yet — this is Step 1."
        lines = []
        for h in history[-10:]:
            action = h.get("action", "?")
            params = h.get("params", {})
            result = h.get("result", "")
            # Create a concise one-liner
            if action == "launch_app":
                lines.append(f"[DONE] Launched app: {params.get('app', '?')} → {result}")
            elif action == "open_url":
                lines.append(f"[DONE] Opened URL: {params.get('url', '?')}")
            elif action == "type":
                text_preview = str(params.get("text", ""))[:40]
                lines.append(f"[DONE] Typed text: '{text_preview}' → {result}")
            elif action == "click_text":
                lines.append(f"[DONE] Clicked text on screen: '{params.get('text', '?')}' → {result}")
            elif action == "click":
                lines.append(f"[DONE] Clicked at ({params.get('x')}, {params.get('y')}) → {result}")
            elif action == "wait":
                lines.append(f"[DONE] Waited {params.get('seconds', '?')}s")
            elif action == "press_key":
                lines.append(f"[DONE] Pressed key: {params.get('key', '?')}")
            elif action == "hotkey":
                lines.append(f"[DONE] Hotkey: {params.get('keys', '?')}")
            elif action == "scroll":
                lines.append(f"[DONE] Scrolled: {params.get('amount', '?')}")
            elif action == "error":
                lines.append(f"[ERROR] Step failed: {result}")
            else:
                lines.append(f"[DONE] {action}: {params} → {result}")
        return "\n".join(lines)

    def decide_next_action(
        self,
        goal: str,
        history: List[Dict[str, Any]],
        screen_summary: str = "",
    ) -> Dict[str, Any]:
        """Queries Ollama to decide the next step."""
        open_windows = self.get_open_windows()
        history_text = self._build_history_summary(history)

        user_prompt = f"""USER GOAL: "{goal}"

ALREADY COMPLETED STEPS ({len(history)} total):
{history_text}

CURRENTLY OPEN WINDOWS ON SCREEN:
{json.dumps(open_windows) if open_windows else "Only desktop/taskbar visible."}

INSTRUCTIONS:
- Review the completed steps above carefully.
- Only choose an action that has NOT been done yet.
- If all parts of the goal are already done, output action "done".
- Output ONLY a single JSON object.

What is the NEXT action to take?"""

        payload = {
            "model": self.model_name,
            "system": SYSTEM_PROMPT,
            "prompt": user_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,  # Low temp = more deterministic, less hallucination
                "top_p": 0.85,
                "repeat_penalty": 1.1,
            },
        }

        try:
            resp = self.client.post(f"{config.ollama_base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_text = data.get("response", "").strip()
            return self._parse_json(raw_text)
        except httpx.ReadTimeout:
            if "3b" not in self.model_name:
                print("[BRAIN] Timeout → falling back to qwen2.5:3b...")
                self.model_name = "qwen2.5:3b"
                payload["model"] = "qwen2.5:3b"
                resp = self.client.post(f"{config.ollama_base_url}/api/generate", json=payload)
                data = resp.json()
                return self._parse_json(data.get("response", "").strip())
            raise

    def _parse_json(self, raw_text: str) -> Dict[str, Any]:
        """Extracts and parses JSON object from model response."""
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except Exception:
                    pass
            raise ValueError(f"Model did not return valid JSON: {raw_text[:300]}")
