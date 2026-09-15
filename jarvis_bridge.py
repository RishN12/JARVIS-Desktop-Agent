import threading
import time
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify

from core.agent import DesktopAgent, AgentState
from core.config import config

class JarvisDesktopBridge:
    """
    Connects the Desktop Agent to the JARVIS ecosystem.
    Provides an IPC REST interface matching JARVIS's desktop agent schema.
    """
    def __init__(self, agent: DesktopAgent):
        self.agent = agent
        self.app = Flask("JarvisDesktopBridge")
        self._setup_routes()
        self._server_thread: Optional[threading.Thread] = None

    def _setup_routes(self):
        @self.app.route("/status", methods=["GET"])
        def status():
            agent_data = self.agent.get_status()
            return jsonify({
                "connected": True,
                "platform": "Windows",
                "emergency_stop": agent_data["emergency_stop"],
                "status": agent_data["status"],
                "current_task": agent_data["task_id"],
                "current_step": agent_data["current_step"],
                "goal": agent_data["goal"],
            })

        @self.app.route("/task", methods=["POST"])
        def create_task():
            data = request.get_json(force=True) or {}
            goal = data.get("goal") or data.get("label") or data.get("routine_id")
            if not goal:
                return jsonify({"error": "No goal provided"}), 400
            
            try:
                self.agent.start_task(goal)
                return jsonify({
                    "task_id": self.agent.current_task_id,
                    "status": "queued",
                    "goal": goal,
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 409

        @self.app.route("/control", methods=["POST"])
        def control():
            data = request.get_json(force=True) or {}
            action = data.get("action")
            
            if action == "emergency_stop":
                self.agent.stop()
                return jsonify({"emergency_stop": True, "status": "emergency_stopped"})
            elif action == "pause":
                self.agent.pause()
                return jsonify({"status": "paused"})
            elif action == "resume":
                self.agent.resume()
                return jsonify({"status": "running"})
            elif action == "cancel":
                self.agent.stop()
                return jsonify({"status": "cancelled"})
            else:
                return jsonify({"error": f"Unknown action: {action}"}), 400

    def start_background(self, host: str = "127.0.0.1", port: int = 5055):
        """Runs the bridge in a background daemon thread."""
        def _run():
            self.app.run(host=host, port=port, debug=False, use_reloader=False)
        self._server_thread = threading.Thread(target=_run, daemon=True)
        self._server_thread.start()
        print(f"[JARVIS BRIDGE] Listening on http://{host}:{port} for JARVIS commands.")
