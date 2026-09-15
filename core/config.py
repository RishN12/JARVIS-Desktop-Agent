import os
from dataclasses import dataclass

@dataclass
class AgentConfig:
    # Ollama settings
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    default_planner_model: str = os.getenv("OLLAMA_PLANNER_MODEL", "qwen2.5:7b")
    fallback_planner_model: str = os.getenv("OLLAMA_FALLBACK_MODEL", "dolphin3:latest")
    vision_model: str = os.getenv("OLLAMA_VISION_MODEL", "moondream:latest")
    
    # Safety and limits
    max_steps_per_task: int = 40
    step_delay_seconds: float = 1.0
    failsafe_corner_enabled: bool = False  # Disabled because multi-monitors have (0,0) between screens
    emergency_hotkey: str = "<ctrl>+<shift>+<esc>"
    pause_on_human_movement: bool = False  # Disabled by default so normal mouse moves don't pause agent
    human_movement_threshold_px: int = 150
    
    # Execution
    screenshot_quality: int = 80
    screenshot_max_width: int = 1280
    screenshot_max_height: int = 720
    
    # Storage and logs
    history_file: str = "agent_history.json"
    state_file: str = "agent_state.json"
    
    # Future JARVIS integration
    jarvis_bridge_host: str = "127.0.0.1"
    jarvis_bridge_port: int = 5055

config = AgentConfig()
