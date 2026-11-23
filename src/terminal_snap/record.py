"""Capture real command output into a scene file.

The point of 'record' is honesty: instead of typing output into a YAML file by hand
(where it silently rots), you run the command once, keep the ANSI codes, and commit
the resulting scene. Re-rendering later cannot invent output that never happened.

Capture rules:
  * stdout and stderr are merged exactly like a terminal sees them
  * ANSI SGR sequences are preserved, other control sequences are stripped
  * carriage-return progress bars are flattened to their final state
  * trailing blank lines are dropped, optional --max-lines truncation keeps the tail
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .ansi import SGR_RE, strip_ansi
from .errors import UsageError
from .scene import Scene, SceneLine
from .yaml_lite import dump_yaml

# Escape sequences we drop: everything that is not an SGR colour/style code.
NON_SGR_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-ln-z]")
MAX_CAPTURE_BYTES = 4 * 1024 * 1024


@dataclass
class Capture:
    """The raw result of running a command for recording."""

    command: str
    exit_code: int
    lines: list[str] = field(default_factory=list)
    truncated: bool = False
    duration_ms: int = 0


def split_command(command: str) -> list[str]:
    """Split a command line without invoking a shell when possible."""
    if not command or not command.strip():
        raise UsageError("--cmd must not be empty")
    if sys.platform.startswith("win"):
        try:
            parts = shlex.split(command, posix=False)
        except ValueError as exc:
            raise UsageError("cannot parse --cmd: " + str(exc)) from exc
    else:
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            raise UsageError("cannot parse --cmd: " + str(exc)) from exc
    return [p.strip('"') for p in parts]


def _flatten_line(raw: str) -> str:
    """Flatten '\\r' progress output and drop non-SGR escape sequences."""
    text = raw
    if "\r" in text:
        pieces = [p for p in text.split("\r") if p]
        text = pieces[-1] if pieces else ""
    # Keep SGR colour codes (that is the whole point) but drop cursor moves,
    # clears and other terminal-control noise that would corrupt a static image.
    placeholders: list[str] = []

    def hold(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return "\x00" + str(len(placeholders) - 1) + "\x00"

    text = SGR_RE.sub(hold, text)
    text = NON_SGR_RE.sub("", text)
    for index, seq in enumerate(placeholders):
        text = text.replace("\x00" + str(index) + "\x00", seq)
    return text.rstrip()


def capture(command: str, cwd: Path | None = None, max_lines: int = 200,
            timeout: float = 120.0) -> Capture:
    """Run a command and capture its combined output as ANSI-preserving lines."""
    import time

    argv = split_command(command)
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["TERM"] = env.get("TERM") or "xterm-256color"
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge at the OS level so interleaving is real
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError as exc:
        raise UsageError("command not found: " + argv[0]) from exc
    except subprocess.TimeoutExpired as exc:
        raise UsageError(
            "command timed out after " + str(int(timeout)) + "s: " + command
        ) from exc
    elapsed = int((time.monotonic() - started) * 1000)
    raw = proc.stdout or b""
    if len(raw) > MAX_CAPTURE_BYTES:
        raise UsageError(
            "command produced more than " + str(MAX_CAPTURE_BYTES // (1024 * 1024))
            + " MB of output; narrow it with --max-lines or a filter"
        )
    decoded = raw.decode("utf-8", "replace")
    lines = [_flatten_line(part) for part in decoded.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    truncated = False
    if max_lines and len(lines) > max_lines:
        lines = _elide_middle(lines, max_lines)
        truncated = True
    return Capture(command, proc.returncode, lines, truncated, elapsed)


def _elide_middle(lines: list[str], limit: int) -> list[str]:
    """Keep the head and the tail of a long capture, eliding the dull middle.

    Tracebacks and test reports are most useful at both ends, so a symmetric cut
    beats plain head truncation. The marker is a real line in the scene, so the
    render shows exactly what happened.
    """
    if limit < 3:
        return lines[-limit:] if limit > 0 else []
    keep = (limit - 1) // 2
    remainder = limit - 1 - keep
    omitted = len(lines) - keep - remainder
    marker = "\u2026 " + str(omitted) + " lines omitted \u2026"
    return lines[:keep] + [marker] + lines[len(lines) - remainder:]


def scene_from_capture(
    cap: Capture,
    title: str,
    theme: str,
    width: int,
    chrome: str = "macos",
    prompt: str = "\u276f",
    show_command: bool = True,
    line_numbers: bool = False,
) -> Scene:
    """Turn a capture into an in-memory scene ready for dumping or rendering."""
    scene = Scene(
        title=title,
        theme=theme,
        width=width,
        chrome=chrome,
        prompt=prompt,
        line_numbers=line_numbers,
        caption=None,
    )
    if show_command:
        scene.lines.append(SceneLine((), "cmd"))
        scene.lines[-1] = SceneLine.from_raw(cap.command, "cmd")
    for text in cap.lines:
        scene.lines.append(SceneLine.from_raw(text, "out"))
    if not cap.lines:
        # Keep the scene renderable and explicit about what happened, rather than
        # emitting a window with a prompt and nothing after it.
        scene.lines.append(SceneLine.from_raw("(no output)", "notice"))
    return scene


def scene_to_yaml(scene: Scene) -> str:
    """Serialise a scene to the committed YAML form."""
    data: dict = {
        "title": scene.title,
        "theme": scene.theme,
        "width": scene.width,
        "chrome": scene.chrome,
        "prompt": scene.prompt,
        "lines": [
            {"cmd": line.to_ansi()} if line.kind == "cmd" else {"out": line.to_ansi()}
            for line in scene.lines
        ],
    }
    header = (
        "# Captured by terminal-snap record on " + sys.platform
        + " - output is verbatim, ANSI codes preserved.\n"
    )
    return header + dump_yaml(data) + "\n"


def plain_output(cap: Capture) -> str:
    """Plain text output with ANSI removed (record --print)."""
    return "\n".join(strip_ansi(line) for line in cap.lines)
