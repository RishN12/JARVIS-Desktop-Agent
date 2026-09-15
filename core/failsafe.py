import threading
import time
from typing import Callable, Optional, List
import pyautogui
from pynput import keyboard, mouse
from .config import config

class FailsafeController:
    def __init__(self, on_emergency_stop: Optional[Callable[[], None]] = None):
        self.on_emergency_stop = on_emergency_stop
        self._stopped = False
        self._paused = False
        self._keyboard_listener: Optional[keyboard.GlobalHotKeys] = None
        self._mouse_listener: Optional[mouse.Listener] = None
        self._last_agent_mouse_pos = (0, 0)
        self._ignore_mouse_event = False
        self._lock = threading.Lock()
        
        # Disable PyAutoGUI's hardcoded (0,0) failsafe (causes false crashes on multi-monitor setups)
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.03

    @property
    def is_stopped(self) -> bool:
        with self._lock:
            return self._stopped

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_stopped(self, val: bool = True):
        with self._lock:
            self._stopped = val
        if val and self.on_emergency_stop:
            try:
                self.on_emergency_stop()
            except Exception:
                pass

    def set_paused(self, val: bool = True):
        with self._lock:
            self._paused = val

    def reset(self):
        with self._lock:
            self._stopped = False
            self._paused = False

    def notify_agent_moved_mouse(self, x: int, y: int):
        """Called by the agent action executor before moving the mouse."""
        self._last_agent_mouse_pos = (x, y)
        self._ignore_mouse_event = True

    def _on_hotkey_stop(self):
        print("\n[EMERGENCY STOP] Failsafe hotkey triggered!")
        self.set_stopped(True)

    def _on_mouse_move(self, x: int, y: int):
        if self._ignore_mouse_event:
            self._ignore_mouse_event = False
            return
        if not config.pause_on_human_movement:
            return
            
        last_x, last_y = self._last_agent_mouse_pos
        dist_sq = (x - last_x) ** 2 + (y - last_y) ** 2
        threshold_sq = config.human_movement_threshold_px ** 2
        
        # If user physically moved mouse significantly while agent wasn't commanding it
        if dist_sq > threshold_sq and not self.is_paused and not self.is_stopped:
            # We only pause, giving user control back
            print(f"[FAILSAFE] Human movement detected ({x}, {y}). Pausing agent for safety.")
            self.set_paused(True)

    def start_listeners(self):
        """Starts the background keyboard hotkey and mouse movement listeners."""
        if self._keyboard_listener is None:
            try:
                hotkey_map = {
                    config.emergency_hotkey: self._on_hotkey_stop,
                    "<ctrl>+<alt>+s": self._on_hotkey_stop,
                }
                self._keyboard_listener = keyboard.GlobalHotKeys(hotkey_map)
                self._keyboard_listener.daemon = True
                self._keyboard_listener.start()
            except Exception as e:
                print(f"[FAILSAFE WARNING] Failed to register global hotkey: {e}")

        if self._mouse_listener is None and config.pause_on_human_movement:
            try:
                self._mouse_listener = mouse.Listener(on_move=self._on_mouse_move)
                self._mouse_listener.daemon = True
                self._mouse_listener.start()
            except Exception as e:
                print(f"[FAILSAFE WARNING] Failed to register mouse listener: {e}")

    def stop_listeners(self):
        """Stops background listeners."""
        if self._keyboard_listener:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
            self._keyboard_listener = None
        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

    def check_failsafe(self):
        """Raises an exception if the agent has been stopped or emergency triggered."""
        if self.is_stopped:
            raise InterruptedError("Agent execution halted by Emergency Stop.")
