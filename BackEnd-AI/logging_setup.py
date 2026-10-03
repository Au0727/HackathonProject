"""
logging_setup.py
================
Logging for the Intent-to-Purchase pipeline.

Three distinct streams, because they answer different questions:

1. **Console** — is it alive, and what is it doing right now. Human-readable and
   colourised when attached to a terminal. Stage progress goes to stdout so it
   can be piped; diagnostics go to stderr via the logging handler.
2. **``logs/pipeline.log``** — a timestamped record of everything the process
   did, for after-the-fact debugging.
3. **``logs/llm-interactions.jsonl``** — one JSON object per model call, holding
   the stage, the exact messages sent, the raw reply, latency and token usage.
   This is what you read to answer "what did I actually send the model?".

Security: the API key is **never** written to any of these. The request body is
logged with the ``Authorization`` header excluded and any credential-bearing
field redacted, so these files are safe to attach to a bug report.

Usage::

    from logging_setup import setup_logging

    handles = setup_logging(level="INFO", directory="logs", session="run1")
    print(handles.pipeline_log, handles.llm_log)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Anything matching one of these keys is redacted before being written.
SECRET_KEYS = frozenset({
    "api_key", "apikey", "authorization", "auth", "token", "access_token",
    "secret", "password", "key",
})

REDACTED = "***REDACTED***"

CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
FILE_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
DATE_FORMAT = "%H:%M:%S"
FILE_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_ANSI = {
    "DEBUG": "\x1b[90m",     # grey
    "INFO": "\x1b[36m",      # cyan
    "WARNING": "\x1b[33m",   # yellow
    "ERROR": "\x1b[31m",     # red
    "CRITICAL": "\x1b[41m",  # red background
}
_ANSI_RESET = "\x1b[0m"


def redact(value: Any) -> Any:
    """Recursively replace credential-looking values with a placeholder.

    Applied to every dict written to the JSONL log, so a key cannot reach disk
    even if a caller passes a whole request body by mistake.
    """
    if isinstance(value, str):
        value = re.sub(
            r"(?i)\b(api[_ -]?key|authorization|access[_ -]?token|password|secret)"
            r"[\"']?(\s*[:=]\s*)(?:bearer\s+)?[\"']?[^\s,;\"']+",
            r"\1\2" + REDACTED,
            value,
        )
        return re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", REDACTED, value)
    if isinstance(value, dict):
        return {
            key: (REDACTED if key.casefold() in SECRET_KEYS else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


class _ColourFormatter(logging.Formatter):
    """Colourise the level name when writing to a real terminal."""

    def __init__(self, *args: Any, use_colour: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.use_colour = use_colour

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if not self.use_colour:
            return text
        colour = _ANSI.get(record.levelname)
        if not colour:
            return text
        return f"{colour}{text}{_ANSI_RESET}"


def _supports_colour(stream: Any) -> bool:
    if os.environ.get("NO_COLOR"):          # https://no-color.org/
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return bool(stream.isatty())
    except Exception:                        # pragma: no cover - exotic streams
        return False


@dataclass
class LogHandles:
    """Where this session's logs went."""

    pipeline_log: Optional[Path] = None
    llm_log: Optional[Path] = None
    directory: Optional[Path] = None
    session: str = ""
    level: str = "INFO"
    console: bool = True

    def describe(self) -> List[str]:
        lines = [f"log level  : {self.level}"]
        if self.directory:
            lines.append(f"log dir    : {self.directory}")
        if self.pipeline_log:
            lines.append(f"pipeline   : {self.pipeline_log}")
        if self.llm_log:
            lines.append(f"llm calls  : {self.llm_log}")
        if not self.directory:
            lines.append("log files  : disabled (logging.directory is null)")
        return lines


class LLMInteractionLog:
    """Append-only JSONL log of model interactions.

    One record per call: what was asked, what came back, how long it took and
    what it cost in tokens. Written with UTF-8 so non-ASCII product names and
    currency symbols survive.
    """

    def __init__(self, path: Optional[Path], session: str = "",
                 enabled: bool = True) -> None:
        self.path = Path(path) if path else None
        self.session = session
        self.enabled = bool(enabled and self.path)
        self._sequence = 0
        self.totals: Dict[str, int] = {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Start each session with a marker so the file can be split later.
            self._append({
                "event": "session_start",
                "session": self.session,
                "started_at": _iso_now(),
                "pid": os.getpid(),
            })

    # -- writing -----------------------------------------------------------
    def record(
        self,
        *,
        stage: str,
        model: str,
        provider: str,
        system_prompt: str,
        user_prompt: str,
        response: Optional[Dict[str, Any]],
        raw_content: str = "",
        latency_ms: float = 0.0,
        usage: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._sequence += 1
        usage = usage or {}
        entry: Dict[str, Any] = {
            "event": "llm_call",
            "session": self.session,
            "seq": self._sequence,
            "at": _iso_now(),
            "stage": stage,
            "provider": provider,
            "model": model,
            "latency_ms": round(latency_ms, 1),
            "request": {
                # The Authorization header is never part of this payload, and
                # redact() removes any credential-bearing field defensively.
                "system": redact(system_prompt),
                "user": redact(user_prompt),
                "prompt_chars": len(system_prompt) + len(user_prompt),
            },
            "response": {
                "content_chars": len(raw_content or ""),
                "parsed": redact(response),
            },
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
            "error": redact(error),
        }
        if usage.get("prompt_tokens"):
            self.totals["prompt_tokens"] += int(usage["prompt_tokens"])
        if usage.get("completion_tokens"):
            self.totals["completion_tokens"] += int(usage["completion_tokens"])
        if usage.get("total_tokens"):
            self.totals["total_tokens"] += int(usage["total_tokens"])
        self.totals["calls"] += 1
        self._append(entry)
        return entry

    def _append(self, entry: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:               # logging must never break a run
            logging.getLogger("intent_to_purchase").warning(
                "could not write LLM log %s: %s", self.path, exc
            )

    # -- reporting ---------------------------------------------------------
    def summary(self) -> str:
        if not self.enabled or not self.totals["calls"]:
            return "llm calls  : 0"
        t = self.totals
        return (
            f"llm calls  : {t['calls']} "
            f"(prompt {t['prompt_tokens']} + completion {t['completion_tokens']} "
            f"= {t['total_tokens']} tokens)"
        )


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _safe_session_name(name: Optional[str]) -> str:
    if not name:
        return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    keep = "-_.:"
    return "".join(c if (c.isalnum() or c in keep) else "-" for c in name)


def setup_logging(
    level: str = "INFO",
    *,
    directory: Optional[str | Path] = "logs",
    console: bool = True,
    colour: Optional[bool] = None,
    session: Optional[str] = None,
    llm_payloads: bool = True,
    stream: Optional[Any] = None,
) -> LogHandles:
    """Configure the root logger and open this session's log files.

    Safe to call repeatedly: existing handlers installed by this module are
    removed first, so a second call does not duplicate every line.

    `directory=None` disables file logging entirely (console only).
    """
    resolved_level = getattr(logging, str(level).upper(), logging.INFO)
    session_name = _safe_session_name(session)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)          # handlers decide what is emitted
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:                 # pragma: no cover
            pass

    use_colour = _supports_colour(stream or sys.stdout) if colour is None else colour
    formatter = logging.Formatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT)

    handles = LogHandles(session=session_name, level=logging.getLevelName(resolved_level),
                         console=console)

    if console:
        # Default to stdout: this is a CLI, and writing ordinary diagnostics to
        # stderr makes PowerShell render every log line as a red error record.
        console_handler = logging.StreamHandler(stream or sys.stdout)
        console_handler.setLevel(resolved_level)
        console_handler.setFormatter(_ColourFormatter(
            CONSOLE_FORMAT, datefmt=DATE_FORMAT, use_colour=use_colour,
        ))
        root.addHandler(console_handler)

    if directory:
        log_dir = Path(directory).expanduser()
        llm_enabled = bool(llm_payloads)
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            pipeline_path = log_dir / f"pipeline-{session_name}.log"
            file_handler = logging.FileHandler(pipeline_path, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(
                FILE_FORMAT, datefmt=FILE_DATE_FORMAT,
            ))
            root.addHandler(file_handler)
            handles.pipeline_log = pipeline_path
            handles.directory = log_dir
            handles.llm_log = (
                log_dir / f"llm-{session_name}.jsonl" if llm_enabled else None
            )
        except OSError as exc:
            # A read-only or unwritable directory must not stop the pipeline.
            logging.getLogger("intent_to_purchase").warning(
                "file logging disabled: %s (%s)", log_dir, exc
            )

    logging.getLogger("intent_to_purchase").debug(
        "logging configured: level=%s console=%s dir=%s",
        handles.level, handles.console, handles.directory,
    )
    return handles


# ---------------------------------------------------------------------------
# Console presentation helpers
# ---------------------------------------------------------------------------

_GLYPHS = {
    "info": "\u2022",     # bullet
    "ok": "\u2713",       # check
    "fail": "\u2717",     # cross
    "arrow": "\u2192",    # right arrow
    "warn": "!",
}


def glyph(name: str) -> str:
    """A single-width ASCII fallback when the console cannot render box art."""
    if os.environ.get("DSH_ASCII_ONLY"):
        return {"info": "-", "ok": "+", "fail": "x", "arrow": "->", "warn": "!"}[name]
    return _GLYPHS[name]


def stage(message: str, *, stream: Optional[Any] = None) -> None:
    """Print a stage progress line to stdout (pipe-friendly, no colour codes)."""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=stream or sys.stdout, flush=True)


def banner(title: str, *, width: int = 78, stream: Optional[Any] = None) -> None:
    out = stream or sys.stdout
    print("=" * width, file=out, flush=True)
    print(title, file=out, flush=True)
    print("=" * width, file=out, flush=True)
