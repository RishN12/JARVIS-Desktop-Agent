import os
from dataclasses import dataclass

@dataclass
class AgentConfig:
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    default_planner_model: str = os.getenv("OLLAMA_PLANNER_MODEL", "qwen2.5:3b")
    fallback_planner_model: str = os.getenv("OLLAMA_FALLBACK_MODEL", "phi3:mini")

    # OCR + Windows state are the fast default. Vision can be enabled when needed.
    vision_enabled: bool = os.getenv("AGENT_VISION_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
    vision_model: str = os.getenv("OLLAMA_VISION_MODEL", "qwen3-vl:2b-instruct")

    max_steps_per_task: int = 40
    step_delay_seconds: float = 0.25
    failsafe_corner_enabled: bool = False
    emergency_hotkey: str = "<ctrl>+<shift>+<esc>"
    pause_on_human_movement: bool = False
    human_movement_threshold_px: int = 150

    screenshot_quality: int = 80
    screenshot_max_width: int = 1280
    screenshot_max_height: int = 720

    history_file: str = "agent_history.json"
    state_file: str = "agent_state.json"

    jarvis_bridge_host: str = "127.0.0.1"
    jarvis_bridge_port: int = 5055

config = AgentConfig()
