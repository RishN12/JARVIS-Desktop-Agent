import threading
import time
import uuid
from enum import Enum
from typing import Callable, Dict, Any, List, Optional
from PIL import Image

from .config import config
from .screen import ScreenManager
from .failsafe import FailsafeController
from .actions import ActionExecutor
from .brain import AgentBrain
from .ocr import WindowsOCR
from routines.seneca import SenecaRoutine


class AgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "emergency_stopped"


class DesktopAgent:
    def __init__(
        self,
        on_status_change: Optional[Callable[[str], None]] = None,
        on_step_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        self.on_status_change = on_status_change
        self.on_step_event = on_step_event
        self.on_log = on_log

        self.screen_manager = ScreenManager()
        self.failsafe = FailsafeController(on_emergency_stop=self._handle_failsafe_stop)
        self.actions = ActionExecutor(self.failsafe)
        self.brain = AgentBrain()
        self.ocr = WindowsOCR()

        self.current_state = AgentState.IDLE
        self.current_goal = ""
        self.current_task_id = ""
        self.history: List[Dict[str, Any]] = []
        self.latest_screenshot: Optional[Image.Image] = None

        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        # Start emergency stop listeners
        self.failsafe.start_listeners()

    def _log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        print(formatted)
        if self.on_log:
            try:
                self.on_log(formatted)
            except Exception:
                pass

    def _set_state(self, new_state: AgentState):
        with self._lock:
            self.current_state = new_state
        self._log(f"Agent state changed to: {new_state.value.upper()}")
        if self.on_status_change:
            try:
                self.on_status_change(new_state.value)
            except Exception:
                pass

    def _handle_failsafe_stop(self):
        self._set_state(AgentState.STOPPED)
        self._log("[ALERT] Emergency stop triggered! Agent halted.")

    def start_task(self, goal: str, model_name: Optional[str] = None):
        """Starts executing a user goal in the background."""
        with self._lock:
            if self.current_state == AgentState.RUNNING:
                raise RuntimeError("An agent task is already running.")

            self.current_goal = goal.strip()
            self.current_task_id = f"task-{uuid.uuid4().hex[:8]}"
            self.history = []
            self.failsafe.reset()
            if model_name:
                self.brain.model_name = model_name

            self._set_state(AgentState.RUNNING)
            self._log(f"Starting Task [{self.current_task_id}]: {self.current_goal}")

            import re
            if re.search(r"\bseneca\b", self.current_goal, re.IGNORECASE):
                self._worker_thread = threading.Thread(target=self._run_seneca_workflow, daemon=True)
            else:
                self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
            self._worker_thread.start()

    def _run_seneca_workflow(self):
        """Executes the specialized Seneca homework solver routine."""
        try:
            routine = SenecaRoutine(
                actions=self.actions,
                failsafe=self.failsafe,
                screen=self.screen_manager,
                ocr=self.ocr,
                log_cb=self._log,
            )
            result = routine.run(self.current_goal)
            self._log(f"Seneca Routine Finished: {result}")
            self._set_state(AgentState.COMPLETED)
        except InterruptedError:
            self._set_state(AgentState.STOPPED)
        except Exception as e:
            self._log(f"[ERROR in Seneca Routine] {e}")
            self._set_state(AgentState.FAILED)

    def pause(self):
        """Pauses the current task."""
        with self._lock:
            if self.current_state == AgentState.RUNNING:
                self.failsafe.set_paused(True)
                self._set_state(AgentState.PAUSED)

    def resume(self):
        """Resumes a paused task."""
        with self._lock:
            if self.current_state == AgentState.PAUSED:
                self.failsafe.set_paused(False)
                self._set_state(AgentState.RUNNING)

    def stop(self):
        """Aborts the task immediately."""
        self.failsafe.set_stopped(True)
        self._set_state(AgentState.STOPPED)

    def _run_loop(self):
        """Main agent loop with repetition guard."""
        import json as _json
        step_count = 0
        consecutive_repeats = 0
        last_action_key = None

        while step_count < config.max_steps_per_task:
            # Check for stop or pause
            if self.failsafe.is_stopped:
                self._set_state(AgentState.STOPPED)
                return

            while self.failsafe.is_paused or self.current_state == AgentState.PAUSED:
                time.sleep(0.3)
                if self.failsafe.is_stopped:
                    self._set_state(AgentState.STOPPED)
                    return

            step_count += 1
            self._log(f"\n--- Step {step_count}/{config.max_steps_per_task} ---")

            try:
                # 1. Capture current desktop state
                screenshot = self.screen_manager.capture_screen()
                self.latest_screenshot = screenshot

                # 2. Query brain for next action
                self._log("Analyzing environment and deciding next step...")
                decision = self.brain.decide_next_action(
                    goal=self.current_goal,
                    history=self.history,
                )

                thought = decision.get("thought", "")
                action = decision.get("action", "")
                params = decision.get("params", {})

                self._log(f"Thought: {thought}")
                self._log(f"Action: {action} with params: {params}")

                # 3. Check for terminal actions
                if action == "done":
                    summary = params.get("summary", "Task successfully completed.")
                    self._log(f"Goal Completed: {summary}")
                    self._set_state(AgentState.COMPLETED)
                    self._emit_step(step_count, decision, summary, screenshot)
                    return

                if action == "fail":
                    reason = params.get("reason", "Task could not be completed.")
                    self._log(f"Goal Failed: {reason}")
                    self._set_state(AgentState.FAILED)
                    self._emit_step(step_count, decision, reason, screenshot)
                    return

                # 4. Repetition guard — catch the same action+params looping 3x
                action_key = f"{action}::{_json.dumps(params, sort_keys=True)}"
                if action_key == last_action_key:
                    consecutive_repeats += 1
                    if consecutive_repeats >= 2:
                        self._log(f"[GUARD] Same action repeated {consecutive_repeats+1}x in a row — task looks done. Auto-completing.")
                        self._set_state(AgentState.COMPLETED)
                        self._emit_step(step_count, {"action": "done", "params": {"summary": "Auto-completed: repetition guard detected task was finished."}}, "Auto-completed", screenshot)
                        return
                else:
                    consecutive_repeats = 0
                last_action_key = action_key

                # 5. Execute the chosen action
                result = self._dispatch_action(action, params)
                self._log(f"Result: {result}")

                # 6. Record step in history
                step_record = {
                    "step": step_count,
                    "thought": thought,
                    "action": action,
                    "params": params,
                    "result": result,
                    "timestamp": time.time(),
                }
                self.history.append(step_record)
                self._emit_step(step_count, decision, result, screenshot)

                # Delay before next step to allow UI changes to stabilize
                time.sleep(config.step_delay_seconds)

            except InterruptedError:
                self._set_state(AgentState.STOPPED)
                return
            except Exception as e:
                self._log(f"[ERROR] Step {step_count} encountered error: {e}")
                self.history.append({
                    "step": step_count,
                    "action": "error",
                    "params": {},
                    "result": str(e),
                    "timestamp": time.time(),
                })
                time.sleep(1.0)

        if step_count >= config.max_steps_per_task:
            self._log("[WARNING] Reached maximum allowed steps without completion.")
            self._set_state(AgentState.FAILED)

    def _dispatch_action(self, action: str, params: Dict[str, Any]) -> str:
        """Routes the decided action to the appropriate physical/OS executor."""
        if action == "open_url":
            return self.actions.open_url(params["url"])
        elif action in {"launch_app", "open_application"}:
            app = params.get("app") or params.get("name") or "notepad"
            return self.actions.launch_app(app)
        elif action == "click":
            x = int(params.get("x", 100))
            y = int(params.get("y", 100))
            button = params.get("button", "left")
            return self.actions.click(x, y, button=button)
        elif action == "double_click":
            x = int(params.get("x", 100))
            y = int(params.get("y", 100))
            return self.actions.double_click(x, y)
        elif action == "right_click":
            x = int(params.get("x", 100))
            y = int(params.get("y", 100))
            return self.actions.right_click(x, y)
        elif action == "type":
            text = str(params.get("text", ""))
            return self.actions.type_text(text)
        elif action == "press_key":
            key = str(params.get("key", "enter"))
            return self.actions.press_key(key)
        elif action == "hotkey":
            keys = params.get("keys", ["ctrl", "c"])
            if isinstance(keys, str):
                keys = [keys]
            return self.actions.press_hotkey(keys)
        elif action == "scroll":
            amount = int(params.get("amount", -300))
            return self.actions.scroll(amount)
        elif action == "wait":
            seconds = float(params.get("seconds", 2.0))
            return self.actions.wait(seconds)
        elif action == "click_text":
            target = str(params.get("text", "")).strip()
            screenshot = self.screen_manager.capture_screen(all_screens=False)
            elements = self.ocr.read_screen_sync(screenshot)
            coords = self.ocr.find_text_coords(elements, target)
            if coords:
                return self.actions.click(coords[0], coords[1])
            return f"Could not locate text '{target}' on active screen."
        elif action == "shell":
            cmd = str(params.get("command", ""))
            return self.actions.run_shell(cmd)
        else:
            return f"Unrecognized action '{action}', skipping."

    def _emit_step(self, step_num: int, decision: Dict[str, Any], result: str, screenshot: Optional[Image.Image]):
        if self.on_step_event:
            try:
                self.on_step_event({
                    "task_id": self.current_task_id,
                    "step": step_num,
                    "decision": decision,
                    "result": result,
                    "screenshot": screenshot,
                })
            except Exception:
                pass

    def get_status(self) -> Dict[str, Any]:
        """Returns JSON status snapshot identical to the JARVIS desktop agent specification."""
        return {
            "task_id": self.current_task_id,
            "goal": self.current_goal,
            "status": self.current_state.value,
            "current_step": len(self.history),
            "emergency_stop": self.failsafe.is_stopped,
            "history": self.history[-10:],
        }
