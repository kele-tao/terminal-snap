"""Tiny ANSI colour helper for CLI output.

Colour is enabled when stdout is a TTY, when FORCE_COLOR is set (CI screenshot
tools do this), or when --color is passed explicitly. NO_COLOR always wins, which
is the convention every modern CLI follows.
"""
from __future__ import annotations

import os
import sys

RESET = "\x1b[0m"
CODES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "grey": "90",
}


def color_enabled(stream=None) -> bool:
    """Decide whether to emit ANSI colour on this stream."""
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") not in (None, "", "0"):
        return True
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def paint(text: str, *styles: str, enabled: bool | None = None) -> str:
    """Wrap text in the given ANSI styles (no-op when colour is disabled)."""
    if enabled is None:
        enabled = color_enabled()
    if not enabled or not styles:
        return text
    prefix = "".join("\x1b[" + CODES[s] + "m" for s in styles if s in CODES)
    return prefix + text + RESET


def can_encode(text: str, stream=None) -> bool:
    """True when this stream can print the text (Windows consoles are often GBK)."""
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def safe_mark(unicode_mark: str, ascii_mark: str, stream=None) -> str:
    """Pick a check/cross mark the terminal can actually render."""
    return unicode_mark if can_encode(unicode_mark, stream) else ascii_mark

