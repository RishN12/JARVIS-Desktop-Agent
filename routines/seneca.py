"""Autonomous Seneca Learning Solver.

Navigates Seneca Learning, reads questions with native OCR, queries
local AI for the correct answer, clicks it, and advances the session.
"""

import json
import time
from typing import Dict, Any, List, Optional, Tuple
import httpx

from core.screen import ScreenManager
from core.ocr import WindowsOCR
from core.actions import ActionExecutor
from core.failsafe import FailsafeController
from core.config import config


# Phrases that indicate a slide needs to be advanced without answering
ADVANCE_TRIGGERS = [
    "click to continue", "tap to continue", "click anywhere",
    "press space", "press enter", "next", "continue", "got it",
    "start learning", "start", "begin", "let's go", "let's start",
]

# Phrases that indicate the session is finished
COMPLETION_MARKERS = [
    "session complete", "assignment complete", "you're done",
    "100%", "congratulations", "well done", "finished",
    "summary", "score", "results",
]

# Phrases that indicate an active quiz question
QUESTION_MARKERS = [
    "?", "which", "what", "select", "choose", "true or false",
    "fill in", "complete the", "identify", "match", "drag",
]


class SenecaRoutine:
    def __init__(
        self,
        actions: ActionExecutor,
        failsafe: FailsafeController,
        screen: ScreenManager,
        ocr: WindowsOCR,
        log_cb=None,
    ):
        self.actions = actions
        self.failsafe = failsafe
        self.screen = screen
        self.ocr = ocr
        self.log = log_cb or print
        self.client = httpx.Client(timeout=25.0)
        self._prev_screen_text = ""
        self._stuck_count = 0

    def run(self, topic: str = "") -> str:
        self.log("[SENECA] Starting autonomous Seneca Learning session...")

        # Step 1: Open Seneca in browser
        self.log("[SENECA] Opening Seneca Learning...")
        self.actions.open_url("https://app.senecalearning.com/dashboard")
        self.actions.wait(3.5)

        solved = 0
        max_slides = 80

        for i in range(max_slides):
            self.failsafe.check_failsafe()

            # Capture and read the current slide
            img = self.screen.capture_screen(all_screens=False)
            elements = self.ocr.read_screen_sync(img)
            lines = [el["text"] for el in elements if el["type"] == "line"]
            screen_text = "\n".join(lines).lower()

            # Detect completion
            if any(marker in screen_text for marker in COMPLETION_MARKERS):
                self.log(f"[SENECA] Session complete! Solved {solved} questions.")
                return f"Seneca session finished. Solved {solved} questions."

            # Detect stuck (screen hasn't changed in 3 tries)
            if screen_text == self._prev_screen_text:
                self._stuck_count += 1
                if self._stuck_count >= 3:
                    self.log("[SENECA] Screen stuck — trying Enter/Space to advance...")
                    self.actions.press_key("enter")
                    self.actions.wait(1.0)
                    self.actions.press_key("space")
                    self.actions.wait(1.5)
                    self._stuck_count = 0
                    continue
            else:
                self._stuck_count = 0
            self._prev_screen_text = screen_text

            # Try to answer a question if one is visible
            if self._has_question(screen_text):
                self.log(f"[SENECA] Slide {i+1}: Question detected. Querying AI for answer...")
                answered = self._answer_question(elements, lines)
                if answered:
                    solved += 1
                    self.log(f"[SENECA] Answer selected! Total solved: {solved}")
                    self.actions.wait(1.2)
                    # Try to click a check/submit button after answering
                    img2 = self.screen.capture_screen(all_screens=False)
                    els2 = self.ocr.read_screen_sync(img2)
                    self._click_progression_button(els2)
                    self.actions.wait(1.5)
                    continue

            # Try to click a progression button (Continue, Next, Check, etc.)
            if self._click_progression_button(elements):
                self.log(f"[SENECA] Slide {i+1}: Progressed to next slide.")
                self.actions.wait(1.8)
                continue

            # Fallback: press Enter to advance flashcard-style slides
            self.log(f"[SENECA] Slide {i+1}: Advancing with Enter...")
            self.actions.press_key("enter")
            self.actions.wait(1.5)

        return f"Completed Seneca run after {max_slides} slides. Solved {solved} questions."

    def _has_question(self, screen_text: str) -> bool:
        """Check if the current slide appears to contain a question."""
        return any(marker in screen_text for marker in QUESTION_MARKERS)

    def _click_progression_button(self, elements: List[Dict]) -> bool:
        """Tries to find and click a progression button. Returns True if clicked."""
        # Ordered by priority
        targets = [
            "Check answer", "Check", "Submit", "Confirm",
            "Continue", "Next", "Got it", "Next question",
            "Start learning", "Start", "Begin",
        ]
        for target in targets:
            coords = self.ocr.find_text_coords(elements, target, case_sensitive=False)
            if coords:
                self.log(f"[SENECA] Clicking '{target}' at {coords}")
                self.actions.click(coords[0], coords[1])
                return True
        return False

    def _answer_question(self, elements: List[Dict], lines: List[str]) -> bool:
        """Uses local AI to identify and click the correct answer."""
        text_block = "\n".join(lines[:20])
        prompt = f"""You are a student answering a Seneca Learning quiz question.
Here is what is visible on screen:
---
{text_block}
---
Identify the question and its answer options. Output ONLY valid JSON:
{{"question": "...", "correct_answer": "exact text of the correct choice"}}
If there is no clear question or answer choices, output:
{{"question": "", "correct_answer": ""}}
"""
        try:
            resp = self.client.post(
                f"{config.ollama_base_url}/api/generate",
                json={
                    "model": "qwen2.5:3b",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                },
            )
            data = resp.json()
            parsed = json.loads(data.get("response", "{}"))
            correct = parsed.get("correct_answer", "").strip()

            if not correct:
                return False

            self.log(f"[SENECA] AI answer: '{correct}'")

            # Try to click the answer text on screen
            coords = self.ocr.find_text_coords(elements, correct, case_sensitive=False)
            if coords:
                self.log(f"[SENECA] Clicking answer at {coords}")
                self.actions.click(coords[0], coords[1])
                return True

            # Partial match fallback — try each word of the answer
            for word in correct.split():
                if len(word) > 3:
                    coords = self.ocr.find_text_coords(elements, word, case_sensitive=False)
                    if coords:
                        self.log(f"[SENECA] Partial match '{word}' clicked at {coords}")
                        self.actions.click(coords[0], coords[1])
                        return True

            self.log(f"[SENECA] Could not locate answer text on screen: '{correct}'")
            return False

        except Exception as e:
            self.log(f"[SENECA] AI error: {e}")
            return False
