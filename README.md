# Autonomous Desktop Agent

A standalone, quota-free Windows desktop automation agent that controls your mouse, keyboard, applications, and browser while you are AFK. Built on local **Ollama** intelligence with built-in safety failsafes and designed for future direct integration with **JARVIS**.

---

## Features

- **Autonomous Execution**: Accepts high-level human goals (e.g. *"Open Chrome and check my email"*, *"Open Notepad and type my notes"*, *"Organize files"*).
- **Quota-Free & Offline**: Runs on local Ollama models (`qwen2.5:3b`, `qwen2.5:7b`, `dolphin3`). Never runs out of API tokens.
- **Full Windows Control**:
  - Mouse clicks, double clicks, right clicks, drags, and scrolling.
  - Keyboard typing (safe clipboard paste with unicode and emojis) and hotkeys (`Ctrl+C`, `Win+R`, `Alt+Tab`).
  - Fast-path app launcher and web browser navigation.
- **AFK Safety & Failsafes**:
  - **Emergency Hotkey**: `Ctrl+Shift+Esc` or `Ctrl+Alt+S` stops the agent immediately.
  - **Corner Slam Failsafe**: Slamming the mouse into any corner halts execution.
  - **Human Movement Detection**: Pauses execution if you touch your mouse during automation.
  - **Step Limits**: Prevents infinite loops while you are away.
- **Modern Dark-Mode GUI**: Built with CustomTkinter, featuring real-time screen sight previews and activity reasoning logs.
- **JARVIS Ready**: Exposes an IPC REST server (`http://127.0.0.1:5055`) matching JARVIS's desktop agent schema.

---

## Quick Start

### 1. Run System Diagnostics
To verify your screen capture, mouse tracking, and Ollama connection:
```powershell
python main.py --test
```

### 2. Launch GUI Dashboard
```powershell
python main.py
```

### 3. Run via Headless CLI
```powershell
python main.py --cli --goal "Open calculator and type 42"
```

---

## Safety Controls
- **Emergency Stop Hotkey**: `Ctrl + Shift + Esc`
- **Mouse Corner Failsafe**: Move mouse vigorously to any corner of the screen.
- **GUI Stop Button**: Click the red "Emergency Stop" button anytime.
