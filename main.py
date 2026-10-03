"""Launch the Agentic Commerce frontend and backend together.

Run ``python main.py`` from any working directory. Press Ctrl+C to stop both.
"""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "BackEnd-AI"
FRONTEND_DIR = ROOT / "FrontEnd"
BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:5173"
STARTUP_TIMEOUT_SECONDS = 60


def find_backend_python() -> Path:
    """Select an interpreter that can import the API's required packages."""
    candidates = [
        BACKEND_DIR / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "Scripts" / "python.exe",
        BACKEND_DIR / ".venv" / "bin" / "python",
        ROOT / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        check = subprocess.run(
            [
                str(resolved),
                "-c",
                "import fastapi, uvicorn",
            ],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode == 0:
            return resolved
    raise RuntimeError(
        "Could not find a Python environment with FastAPI and Uvicorn. "
        "Install them with `python -m pip install -r BackEnd-AI/requirements.txt`."
    )


def ensure_project_files() -> Path:
    """Validate the frontend setup and return the Node executable."""
    if not (BACKEND_DIR / "server.py").is_file():
        raise RuntimeError(f"Backend entry point not found: {BACKEND_DIR / 'server.py'}")
    if not (FRONTEND_DIR / "package.json").is_file():
        raise RuntimeError(f"Frontend package file not found: {FRONTEND_DIR / 'package.json'}")

    vite_cli = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_cli.is_file():
        raise RuntimeError(
            "Frontend dependencies are not installed. Run "
            "`npm install` from the FrontEnd directory, then retry."
        )

    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js was not found on PATH. Install Node.js 20 or newer.")
    return Path(node)


def http_is_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1):
            return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def wait_until_ready(processes: Mapping[str, subprocess.Popen[bytes]]) -> None:
    endpoints = {
        "Python API": f"{BACKEND_URL}/docs",
        "Vite frontend": FRONTEND_URL,
    }
    pending = dict(endpoints)
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS

    while pending and time.monotonic() < deadline:
        for name, process in processes.items():
            exit_code = process.poll()
            if exit_code is not None:
                raise RuntimeError(f"{name} exited during startup with code {exit_code}.")

        for name, url in list(pending.items()):
            if http_is_ready(url):
                print(f"{name} is ready at {url}")
                del pending[name]
        if pending:
            time.sleep(0.5)

    if pending:
        raise RuntimeError(
            "Timed out waiting for " + ", ".join(pending) + " to start."
        )


def stop_processes(processes: Mapping[str, subprocess.Popen[bytes]]) -> None:
    """Stop the child processes and wait for them to exit."""
    for process in reversed(list(processes.values())):
        if process.poll() is None:
            process.terminate()
    for process in processes.values():
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def handle_shutdown_signal(_signum: int, _frame: object) -> None:
    _ = (_signum, _frame)
    raise KeyboardInterrupt


def main() -> int:
    processes: dict[str, subprocess.Popen[bytes]] = {}
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handle_shutdown_signal)
    try:
        python = find_backend_python()
        node = ensure_project_files()
        vite_cli = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"

        print("Starting Agentic Commerce...")
        processes["Python API"] = subprocess.Popen(
            [
                str(python),
                "-m",
                "uvicorn",
                "server:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=BACKEND_DIR,
        )
        processes["Vite frontend"] = subprocess.Popen(
            [
                str(node),
                str(vite_cli),
                "--host",
                "127.0.0.1",
                "--port",
                "5173",
                "--strictPort",
            ],
            cwd=FRONTEND_DIR,
        )

        wait_until_ready(processes)
        print("The app is ready. Press Ctrl+C here to stop both servers.")
        webbrowser.open(FRONTEND_URL)

        while True:
            for name, process in processes.items():
                exit_code = process.poll()
                if exit_code is not None:
                    raise RuntimeError(f"{name} stopped with exit code {exit_code}.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping the frontend and backend...")
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"Startup error: {exc}", file=sys.stderr)
        return 1
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
