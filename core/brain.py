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

Choose the SINGLE BEST NEXT ACTION needed to accomplish the user's goal.

Use the user's goal, previous actions/results, active window, open windows, OCR text/coordinates,
and optional visual description.

Rules:
1. Treat current screen evidence as truth.
2. Never repeat a successful action unless evidence says it is needed.
3. Adapt after failures.
4. Prefer click_text when visible text identifies the target.
5. Use coordinates only when useful coordinates are provided by OCR/observation.
6. After launching/opening something, verify it before repeating the action.
7. Break complex goals into one action at a time.
8. For coding tasks, prefer developer actions (list_files, read_file, write_file, run_command, test_python) over GUI typing.
9. If a command fails, inspect its output, modify the relevant file, and test again.
10. For Windows apps use launch_app, not a web URL.
11. Only say done when the goal is actually supported by evidence.
12. If the tools cannot complete the goal, say fail.

Common app mappings:
Calculator -> calc
Notepad -> notepad
Paint -> mspaint
Command Prompt -> cmd
PowerShell -> powershell
File Explorer -> explorer

Always output ONLY valid JSON:
{"thought":"brief rationale","action":"action_name","params":{}}
"""


class AgentBrain:
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or config.default_planner_model
        self.client = httpx.Client(timeout=httpx.Timeout(25.0, connect=5.0))

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
                            if rect[2] - rect[0] > 50 and rect[3] - rect[1] > 50 and title != "Program Manager":
                                windows.append(title)

                win32gui.EnumWindows(_enum_cb, None)
            except Exception:
                pass
        return windows[:20]

    def _fast_path(self, goal: str, active_window: str) -> Optional[Dict[str, Any]]:
        text = goal.strip().lower()
        app_map = {
            "calculator": "calc",
            "notepad": "notepad",
            "paint": "mspaint",
            "file explorer": "explorer",
            "command prompt": "cmd",
            "cmd": "cmd",
            "powershell": "powershell",
        }

        for name, app in app_map.items():
            if any(re.fullmatch(p, text) for p in (
                rf"open {re.escape(name)}",
                rf"launch {re.escape(name)}",
                rf"start {re.escape(name)}",
            )):
                if name in active_window.lower() or (name == "file explorer" and "explorer" in active_window.lower()):
                    return {"thought": f"{name.title()} is already the active window.", "action": "done",
                            "params": {"summary": f"{name.title()} is already open."}}
                return {"thought": "Fast path: launch the requested Windows app directly.",
                        "action": "launch_app", "params": {"app": app}}
        return None

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
                lines.append(f"[{h.get('step','?')}] {action} {json.dumps(params, ensure_ascii=False)} | result: {result}")
            post = h.get("post_action_observation")
            if post:
                lines.append(f"    post-action verification: windows={json.dumps(post.get('windows', []), ensure_ascii=False)}")
                post_vision = str(post.get("vision", ""))
                if post_vision and not post_vision.startswith("Vision disabled"):
                    lines.append(f"    post-action vision: {post_vision[:500]}")
            if thought:
                lines.append(f"    previous thought: {thought}")
        return "\n".join(lines)

    def _build_screen_observation(self, screen_elements: Optional[List[Dict[str, Any]]]) -> str:
        if not screen_elements:
            return "No OCR text was detected on the current screen."
        lines, seen = [], set()
        for el in screen_elements[:120]:
            text_value = str(el.get("text", "")).strip()
            if not text_value:
                continue
            key = (el.get("type"), text_value.lower(), el.get("center_x"), el.get("center_y"))
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f'- {el.get("type","element")}: "{text_value}" '
                f'at ({el.get("center_x","?")}, {el.get("center_y","?")})'
            )
        return "\n".join(lines) if lines else "No useful OCR text was detected."

    def decide_next_action(self, goal: str, history: List[Dict[str, Any]],
                           screen_summary: str = "",
                           screen_elements: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        active_window = self.get_active_window()

        fast = self._fast_path(goal, active_window)
        if fast:
            return fast

        open_windows = self.get_open_windows()
        history_text = self._build_history_summary(history)
        # Coding tasks do not need hundreds of OCR entries. Keeping the prompt small
        # makes local models respond much faster.
        developer_goal = bool(re.search(
            r"\b(create|build|write|make|edit|modify|fix|debug|test|code|python|file|app|project|script|program)\b",
            goal, re.IGNORECASE
        ))
        if developer_goal:
            observation = "Developer task: prioritize filesystem and terminal tools. Screen details are secondary."
        else:
            compact_elements = (screen_elements or [])[:50]
            observation = screen_summary or self._build_screen_observation(compact_elements)

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
            "keep_alive": "10m",
            "options": {"temperature": 0.1, "top_p": 0.85, "repeat_penalty": 1.1, "num_predict": 160},
        }

        try:
            resp = self.client.post(f"{config.ollama_base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return self._validate_decision(self._parse_json(data.get("response", "").strip()))
        except httpx.ReadTimeout:
            if self.model_name not in {"phi3:mini"}:
                print("[BRAIN] Timeout -> falling back to qwen2.5:3b...")
                self.model_name = "phi3:mini"
                payload["model"] = self.model_name
                resp = self.client.post(f"{config.ollama_base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return self._validate_decision(self._parse_json(data.get("response", "").strip()))
            raise

    def _validate_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"open_url","launch_app","click_text","click","double_click","right_click","drag",
                   "type","press_key","hotkey","scroll","wait","shell","list_files","read_file","write_file","append_file",
                   "make_directory","copy_file","move_file","run_command","test_python","done","fail"}
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
            raise ValueError(f"Model did not return valid JSON: {raw_text[:300]}")
