import os
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

class DeveloperTools:
    """Workspace-scoped tools for autonomous software development."""

    def __init__(self, workspace: Optional[str] = None):
        self.workspace = Path(workspace or os.getcwd()).resolve()

    def _path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        p = p.resolve()
        try:
            p.relative_to(self.workspace)
        except ValueError:
            raise ValueError(f"Path is outside workspace: {path}")
        return p

    def list_files(self, path: str = ".") -> str:
        root = self._path(path)
        if not root.exists(): return f"Path does not exist: {path}"
        if not root.is_dir(): return f"Not a directory: {path}"
        items = [{"name": p.name, "type": "dir" if p.is_dir() else "file"} for p in sorted(root.iterdir(), key=lambda x: x.name.lower())[:200]]
        return json.dumps({"path": str(root), "items": items}, ensure_ascii=False)

    def read_file(self, path: str, max_chars: int = 30000) -> str:
        p = self._path(path)
        if not p.is_file(): return f"File does not exist: {path}"
        text = p.read_text(encoding="utf-8", errors="replace")
        return text if len(text) <= max_chars else text[:max_chars] + "\n...[truncated]"

    def write_file(self, path: str, content: str) -> str:
        p = self._path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {p}"

    def append_file(self, path: str, content: str) -> str:
        p = self._path(path); p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f: f.write(content)
        return f"Appended {len(content)} characters to {p}"

    def make_directory(self, path: str) -> str:
        p = self._path(path); p.mkdir(parents=True, exist_ok=True)
        return f"Directory ready: {p}"

    def copy_file(self, source: str, destination: str) -> str:
        src, dst = self._path(source), self._path(destination)
        if not src.is_file(): return f"Source file does not exist: {source}"
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
        return f"Copied {src} -> {dst}"

    def move_file(self, source: str, destination: str) -> str:
        src, dst = self._path(source), self._path(destination)
        if not src.exists(): return f"Source does not exist: {source}"
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(src), str(dst))
        return f"Moved {src} -> {dst}"

    def run_command(self, command: str, timeout: int = 30) -> str:
        if not command.strip(): return "No command supplied."
        try:
            result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], cwd=str(self.workspace), capture_output=True, text=True, timeout=max(1, min(timeout, 120)))
            output = (result.stdout or "").strip()
            if result.stderr: output += ("\n" if output else "") + result.stderr.strip()
            return json.dumps({"return_code": result.returncode, "success": result.returncode == 0, "output": (output or "(no output)")[-12000:]}, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            return json.dumps({"success": False, "timeout": True, "output": f"Command timed out after {timeout}s."})

    def test_python(self, path: str) -> str:
        p = self._path(path)
        if not p.is_file(): return f"Python file does not exist: {path}"
        return self.run_command(f'python -m py_compile "{p}"', timeout=30)
