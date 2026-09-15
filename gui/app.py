import os
import sys
import threading
import time
from typing import Optional
from PIL import Image, ImageTk
import customtkinter as ctk

from core.agent import DesktopAgent, AgentState
from core.config import config
from jarvis_bridge import JarvisDesktopBridge


class DesktopAgentApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Autonomous Desktop Agent - AFK Assistant")
        self.geometry("1100x720")
        self.minsize(900, 600)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Initialize Agent
        self.agent = DesktopAgent(
            on_status_change=self._on_agent_status_change,
            on_step_event=self._on_agent_step_event,
            on_log=self._on_agent_log,
        )

        # Start JARVIS bridge in background
        self.bridge = JarvisDesktopBridge(self.agent)
        self.bridge.start_background(config.jarvis_bridge_host, config.jarvis_bridge_port)

        self.preview_image_ref = None

        self._build_ui()
        self._poll_status()

    def _build_ui(self):
        # Configure grid layout (1x2 columns)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ================= TOP HEADER =================
        header_frame = ctk.CTkFrame(self, corner_radius=10)
        header_frame.grid(row=0, column=0, columnspan=2, padx=15, pady=(15, 10), sticky="ew")

        title_label = ctk.CTkLabel(
            header_frame,
            text="⚡ Autonomous Desktop Agent",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        title_label.pack(side="left", padx=15, pady=10)

        self.status_badge = ctk.CTkLabel(
            header_frame,
            text="IDLE",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#334155",
            text_color="#94a3b8",
            corner_radius=8,
            padx=12,
            pady=4,
        )
        self.status_badge.pack(side="left", padx=10)

        failsafe_info = ctk.CTkLabel(
            header_frame,
            text="Failsafe: Ctrl+Shift+Esc or Corner Slam",
            font=ctk.CTkFont(size=12),
            text_color="#64748b",
        )
        failsafe_info.pack(side="right", padx=15)

        # ================= LEFT COLUMN: CONTROLS & LOG =================
        left_frame = ctk.CTkFrame(self, corner_radius=10)
        left_frame.grid(row=1, column=0, padx=(15, 10), pady=(0, 15), sticky="nsew")
        left_frame.grid_rowconfigure(3, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        # 1. Goal Input Box
        input_label = ctk.CTkLabel(
            left_frame,
            text="What should I do for you while AFK?",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        input_label.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")

        self.goal_entry = ctk.CTkTextbox(left_frame, height=75, font=ctk.CTkFont(size=13))
        self.goal_entry.grid(row=1, column=0, padx=15, pady=(0, 10), sticky="ew")
        self.goal_entry.insert("1.0", "Open Chrome, go to https://mail.google.com, and check my inbox.")

        # Quick Preset Chips
        presets_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        presets_frame.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="ew")

        def set_preset(text):
            self.goal_entry.delete("1.0", "end")
            self.goal_entry.insert("1.0", text)

        seneca_btn = ctk.CTkButton(
            presets_frame,
            text="🎓 Do Seneca",
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: set_preset("Do my Seneca homework assignments and solve the questions"),
        )
        seneca_btn.pack(side="left", padx=(0, 6))

        notepad_btn = ctk.CTkButton(
            presets_frame,
            text="📝 Open Notepad & Write",
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: set_preset("Open Notepad and type: Desktop Agent is working automatically!"),
        )
        notepad_btn.pack(side="left", padx=6)

        gmail_btn = ctk.CTkButton(
            presets_frame,
            text="✉️ Check Gmail",
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: set_preset("Open Chrome, go to https://mail.google.com, and check my inbox"),
        )
        gmail_btn.pack(side="left", padx=6)

        # 2. Controls & Model Selector
        control_bar = ctk.CTkFrame(left_frame, fg_color="transparent")
        control_bar.grid(row=3, column=0, padx=15, pady=(0, 10), sticky="ew")

        self.model_var = ctk.StringVar(value="qwen2.5:3b")
        model_menu = ctk.CTkOptionMenu(
            control_bar,
            values=["qwen2.5:3b", "qwen2.5:7b", "dolphin3:latest"],
            variable=self.model_var,
            width=130,
        )
        model_menu.pack(side="left", padx=(0, 10))

        self.start_btn = ctk.CTkButton(
            control_bar,
            text="▶ Start Task",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._on_start_clicked,
            width=110,
        )
        self.start_btn.pack(side="left", padx=5)

        self.pause_btn = ctk.CTkButton(
            control_bar,
            text="⏸ Pause",
            command=self._on_pause_clicked,
            state="disabled",
            width=80,
        )
        self.pause_btn.pack(side="left", padx=5)

        self.stop_btn = ctk.CTkButton(
            control_bar,
            text="⏹ Emergency Stop",
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=self._on_stop_clicked,
            width=130,
        )
        self.stop_btn.pack(side="right")

        # 3. Activity Feed / Terminal Log
        log_label = ctk.CTkLabel(
            left_frame,
            text="Live Activity & Reasoning Feed",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        log_label.grid(row=4, column=0, padx=15, pady=(10, 0), sticky="nw")

        self.log_textbox = ctk.CTkTextbox(
            left_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0f172a",
            text_color="#38bdf8",
        )
        self.log_textbox.grid(row=5, column=0, padx=15, pady=(5, 15), sticky="nsew")
        left_frame.grid_rowconfigure(5, weight=1)

        # ================= RIGHT COLUMN: SCREEN PREVIEW & STATUS =================
        right_frame = ctk.CTkFrame(self, corner_radius=10)
        right_frame.grid(row=1, column=1, padx=(10, 15), pady=(0, 15), sticky="nsew")
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        preview_label = ctk.CTkLabel(
            right_frame,
            text="Desktop Screen Sight (What the Agent Sees)",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        preview_label.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")

        self.preview_canvas = ctk.CTkLabel(
            right_frame,
            text="Screenshot preview will appear when task starts.",
            fg_color="#0f172a",
            corner_radius=8,
        )
        self.preview_canvas.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="nsew")

    def _on_start_clicked(self):
        goal = self.goal_entry.get("1.0", "end").strip()
        if not goal:
            return
        model = self.model_var.get()
        try:
            self.agent.start_task(goal, model_name=model)
            self.start_btn.configure(state="disabled")
            self.pause_btn.configure(state="normal", text="⏸ Pause")
        except Exception as e:
            self._log_gui(f"[ERROR] Could not start task: {e}")

    def _on_pause_clicked(self):
        if self.agent.current_state == AgentState.RUNNING:
            self.agent.pause()
            self.pause_btn.configure(text="▶ Resume")
        elif self.agent.current_state == AgentState.PAUSED:
            self.agent.resume()
            self.pause_btn.configure(text="⏸ Pause")

    def _on_stop_clicked(self):
        self.agent.stop()
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled", text="⏸ Pause")

    def _on_agent_status_change(self, status: str):
        self.after(0, self._update_status_ui, status)

    def _update_status_ui(self, status: str):
        colors = {
            "idle": ("#334155", "#94a3b8"),
            "running": ("#16a34a", "#ffffff"),
            "paused": ("#ca8a04", "#ffffff"),
            "completed": ("#2563eb", "#ffffff"),
            "failed": ("#dc2626", "#ffffff"),
            "emergency_stopped": ("#dc2626", "#ffffff"),
        }
        bg, fg = colors.get(status, ("#334155", "#ffffff"))
        self.status_badge.configure(text=status.upper(), fg_color=bg, text_color=fg)

        if status in {"completed", "failed", "emergency_stopped", "idle"}:
            self.start_btn.configure(state="normal")
            self.pause_btn.configure(state="disabled", text="⏸ Pause")
        elif status == "running":
            self.start_btn.configure(state="disabled")
            self.pause_btn.configure(state="normal", text="⏸ Pause")
        elif status == "paused":
            self.pause_btn.configure(state="normal", text="▶ Resume")

    def _on_agent_step_event(self, event_data: dict):
        screenshot = event_data.get("screenshot")
        if screenshot:
            self.after(0, self._update_preview, screenshot)

    def _update_preview(self, pil_image: Image.Image):
        try:
            # Resize image to fit label (approx 500x320)
            img_copy = pil_image.copy()
            img_copy.thumbnail((500, 360), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img_copy, dark_image=img_copy, size=img_copy.size)
            self.preview_canvas.configure(image=ctk_img, text="")
            self.preview_image_ref = ctk_img
        except Exception:
            pass

    def _on_agent_log(self, message: str):
        self.after(0, self._log_gui, message)

    def _log_gui(self, message: str):
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")

    def _poll_status(self):
        # Poll failsafe periodically
        if self.agent.failsafe.is_stopped and self.agent.current_state != AgentState.STOPPED:
            self._update_status_ui("emergency_stopped")
        self.after(500, self._poll_status)


def run_gui():
    app = DesktopAgentApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
