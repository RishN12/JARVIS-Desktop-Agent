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
        raw = str(path or "").strip()
        if not raw:
            raise ValueError("A non-empty path is required.")
        p = Path(raw)
        if p.is_absolute():
            try:
                p = p.resolve()
                p.relative_to(self.workspace)
            except ValueError:
                # Safely handle simple hallucinated absolute paths by anchoring
                # their filename inside the configured workspace.
                if len(p.parts) <= 5:
                    p = self.workspace / p.name
                else:
                    raise ValueError(f"Path is outside workspace: {path}")
        else:
            p = self.workspace / p
        p = p.resolve()
        try:
            p.relative_to(self.workspace)
        except ValueError:
            raise ValueError(f"Path is outside workspace: {path}")
        return p

    def list_files(self, path: str = ".") -> str:
        root = self._path(path)
        if not root.exists():
            return f"Path does not exist: {path}"
        if not root.is_dir():
            return f"Not a directory: {path}"
        items = [
            {"name": p.name, "type": "dir" if p.is_dir() else "file"}
            for p in sorted(root.iterdir(), key=lambda x: x.name.lower())[:200]
        ]
        return json.dumps(
            {"path": str(root), "items": items}, ensure_ascii=False
        )

    def read_file(self, path: str, max_chars: int = 30000) -> str:
        p = self._path(path)
        if not p.is_file():
            return f"File does not exist: {path}"
        text = p.read_text(encoding="utf-8", errors="replace")
        return text if len(text) <= max_chars else text[:max_chars] + "\n...[truncated]"

    def write_file(self, path: str, content: str) -> str:
        if content is None:
            raise ValueError("write_file requires content.")
        p = self._path(path)
        if p.exists() and p.is_dir():
            raise ValueError(f"Cannot write a file over directory: {path}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(content), encoding="utf-8")
        return f"Wrote {len(str(content))} characters to {p}"

    def append_file(self, path: str, content: str) -> str:
        if content is None:
            raise ValueError("append_file requires content.")
        p = self._path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(str(content))
        return f"Appended {len(str(content))} characters to {p}"

    def make_directory(self, path: str) -> str:
        p = self._path(path)
        p.mkdir(parents=True, exist_ok=True)
        return f"Directory ready: {p}"

    def copy_file(self, source: str, destination: str) -> str:
        src, dst = self._path(source), self._path(destination)
        if not src.is_file():
            return f"Source file does not exist: {source}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return f"Copied {src} -> {dst}"

    def move_file(self, source: str, destination: str) -> str:
        src, dst = self._path(source), self._path(destination)
        if not src.exists():
            return f"Source does not exist: {source}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Moved {src} -> {dst}"

    def run_command(self, command: str, timeout: int = 30) -> str:
        if not str(command).strip():
            return "No command supplied."

        command = str(command).strip()

        # PowerShell splits unquoted Windows paths containing spaces. Repair
        # the common model-generated form: python C:\\path\\with spaces\\file.py
        parts = command.split(None, 1)
        if len(parts) == 2 and parts[0].lower() in ("python", "python.exe"):
            target = parts[1].strip().strip('"')
            target_path = Path(target)
            if (
                target.lower().endswith(".py")
                and " " in target
                and target_path.is_absolute()
            ):
                command = f'{parts[0]} "{target}"'

        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=max(1, min(timeout, 120)),
            )
            output = (result.stdout or "").strip()
            if result.stderr:
                output += ("\n" if output else "") + result.stderr.strip()
            return json.dumps(
                {
                    "return_code": result.returncode,
                    "success": result.returncode == 0,
                    "output": (output or "(no output)")[-12000:],
                },
                ensure_ascii=False,
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "success": False,
                    "timeout": True,
                    "output": f"Command timed out after {timeout}s.",
                }
            )

    def run_python(
        self, path: str, args: Optional[list] = None, timeout: int = 30
    ) -> str:
        """Runs a Python file inside the workspace and captures its output."""
        p = self._path(path)
        if not p.is_file():
            return f"Python file does not exist: {path}"

        cmd = ["python", str(p)] + [str(a) for a in (args or [])]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=max(1, min(timeout, 120)),
            )
            output = (result.stdout or "").strip()
            if result.stderr:
                output += ("\n" if output else "") + result.stderr.strip()
            return json.dumps(
                {
                    "return_code": result.returncode,
                    "success": result.returncode == 0,
                    "output": (output or "(no output)")[-12000:],
                },
                ensure_ascii=False,
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "success": False,
                    "timeout": True,
                    "output": f"Python program timed out after {timeout}s.",
                }
            )

    def test_python(self, path: str) -> str:
        p = self._path(path)
        if not p.is_file():
            return f"Python file does not exist: {path}"
        return self.run_command(f'python -m py_compile "{p}"', timeout=30)
