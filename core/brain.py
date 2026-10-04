import json
import re
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


SYSTEM_PROMPT = """You are the planning brain of a Windows Desktop Agent.

Your job is NOT to chat. Your job is to choose the SINGLE BEST NEXT ACTION needed to accomplish the user's goal.

You receive:
- the user's high-level goal
- actions already attempted and their results
- currently open Windows
- text currently visible on the screen, including approximate coordinates

IMPORTANT:
1. Treat the screen observation as the current truth. Do not assume an action succeeded just because it was attempted.
2. NEVER repeat an action that succeeded unless the screen evidence shows it needs to be repeated.
3. If an action failed, adapt. Do not blindly repeat it.
4. Use click_text when visible text identifies the target. It is safer than guessing coordinates.
5. Use exact click coordinates only when the screen observation gives a useful coordinate or when there is no text target.
6. After opening an app or URL, normally wait briefly, then inspect the new screen before acting.
7. Break complex goals into small steps. Do not try to perform multiple actions in one response.
8. For a Windows desktop application, use launch_app rather than open_url. Examples:
   - Calculator -> launch_app {"app":"calc"}
   - Notepad -> launch_app {"app":"notepad"}
   - Paint -> launch_app {"app":"mspaint"}
   - Command Prompt -> launch_app {"app":"cmd"}
   - PowerShell -> launch_app {"app":"powershell"}
   - File Explorer -> launch_app {"app":"explorer"}
   Never open a Microsoft Store or other web URL just because an app has a webpage.
9. After an action, use the post-action observation in history to decide whether it worked. If the expected UI/window is visible, do not repeat the action.
10. When the goal is genuinely complete, output "done".
11. If the goal cannot be completed with the available actions, output "fail" and explain why.
12. Never claim that something happened unless the observation/history supports it.

Always output ONLY valid JSON:
{
  "thought": "brief explanation of what the screen/history shows and why the next action is needed",
  "action": "action_name",
  "params": {}
}

AVAILABLE ACTIONS:
- open_url: {"url":"https://example.com"}
- launch_app: {"app":"chrome"}
- click_text: {"text":"Compose"}
- click: {"x":500,"y":300,"button":"left"}
- double_click: {"x":500,"y":300}
- right_click: {"x":500,"y":300}
- drag: {"start_x":100,"start_y":100,"end_x":500,"end_y":500}
- type: {"text":"hello"}
- press_key: {"key":"enter"}
- hotkey: {"keys":["ctrl","l"]}
- scroll: {"amount":-500}
- wait: {"seconds":2}
- shell: {"command":"Get-Process"}
- done: {"summary":"what was completed"}
- fail: {"reason":"why it cannot be completed"}

For computer-use tasks, prefer this pattern:
OPEN/LAUNCH -> WAIT -> OBSERVE -> INTERACT -> OBSERVE -> VERIFY -> DONE.
"""


class AgentBrain:
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or config.default_planner_model
        self.client = httpx.Client(timeout=50.0)

    def get_active_window(self) -> str:
        if not HAS_WIN32:
            return ""
        try:
            hwnd = win32gui.GetForegroundWindow()
            return win32gui.GetWindowText(hwnd).strip()
        except Exception:
            return ""

    def get_open_windows(self) -> List[str]:
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
                            if w > 50 and h > 50 and title != "Program Manager":
                                windows.append(title)

                win32gui.EnumWindows(_enum_cb, None)
            except Exception:
                pass
        return windows[:20]

    def _build_history_summary(self, history: List[Dict[str, Any]]) -> str:
        if not history:
            return "No actions attempted yet."

        lines = []
        for h in history[-12:]:
            action = h.get("action", "?")
            params = h.get("params", {})
            result = str(h.get("result", ""))
            thought = str(h.get("thought", ""))[:120]

            if action == "type":
                p = str(params.get("text", ""))
                if len(p) > 80:
                    p = p[:80] + "..."
                lines.append(f"[{h.get('step','?')}] type -> '{p}' | result: {result}")
            else:
                lines.append(
                    f"[{h.get('step','?')}] {action} {json.dumps(params, ensure_ascii=False)} | result: {result}"
                )
            post = h.get("post_action_observation")
            if post:
                vision = str(post.get("vision", ""))[:500]
                windows_after = post.get("windows", [])
                lines.append(f"    post-action verification: windows={json.dumps(windows_after, ensure_ascii=False)}")
                lines.append(f"    post-action vision: {vision}")
            if thought:
                lines.append(f"    previous thought: {thought}")

        return "\n".join(lines)

    def _build_screen_observation(
        self,
        screen_elements: Optional[List[Dict[str, Any]]],
    ) -> str:
        if not screen_elements:
            return "No OCR text was detected on the current screen."

        lines = []
        seen = set()

        for el in screen_elements[:120]:
            text_value = str(el.get("text", "")).strip()
            if not text_value:
                continue

            key = (
                el.get("type"),
                text_value.lower(),
                el.get("center_x"),
                el.get("center_y"),
            )
            if key in seen:
                continue
            seen.add(key)

            lines.append(
                f'- {el.get("type","element")}: "{text_value}" '
                f'at ({el.get("center_x","?")}, {el.get("center_y","?")})'
            )

        return "\n".join(lines) if lines else "No useful OCR text was detected."

    def decide_next_action(
        self,
        goal: str,
        history: List[Dict[str, Any]],
        screen_summary: str = "",
        screen_elements: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        open_windows = self.get_open_windows()
        active_window = self.get_active_window()
        history_text = self._build_history_summary(history)
        observation = screen_summary or self._build_screen_observation(screen_elements)

        user_prompt = f"""USER GOAL:
{goal}

ACTION HISTORY:
{history_text}

ACTIVE WINDOW:
{active_window or "Unknown"}

OPEN WINDOWS:
{json.dumps(open_windows, ensure_ascii=False)}

CURRENT SCREEN OBSERVATION:
{observation}

Choose ONLY the next single action. Base the decision on the current observation and history.
"""

        payload = {
            "model": self.model_name,
            "system": SYSTEM_PROMPT,
            "prompt": user_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "top_p": 0.85,
                "repeat_penalty": 1.1,
            },
        }

        try:
            resp = self.client.post(
                f"{config.ollama_base_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_text = data.get("response", "").strip()
            decision = self._parse_json(raw_text)
            return self._validate_decision(decision)
        except httpx.ReadTimeout:
            if "3b" not in self.model_name:
                print("[BRAIN] Timeout -> falling back to qwen2.5:3b...")
                self.model_name = "qwen2.5:3b"
                payload["model"] = self.model_name
                resp = self.client.post(
                    f"{config.ollama_base_url}/api/generate",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._validate_decision(
                    self._parse_json(data.get("response", "").strip())
                )
            raise

    def _validate_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {
            "open_url", "launch_app", "click_text", "click", "double_click",
            "right_click", "drag", "type", "press_key", "hotkey", "scroll",
            "wait", "shell", "done", "fail"
        }

        action = decision.get("action")
        if action not in allowed:
            raise ValueError(f"Brain returned unsupported action: {action!r}")

        if not isinstance(decision.get("params", {}), dict):
            raise ValueError("Brain returned non-object params.")

        decision.setdefault("thought", "")
        return decision

    def _parse_json(self, raw_text: str) -> Dict[str, Any]:
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except Exception:
                    pass
            raise ValueError(
                f"Model did not return valid JSON: {raw_text[:300]}"
            )
