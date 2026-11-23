"""Error types shared by the whole package.

Every user-facing failure in terminal-snap is a :class:`SnapError` subclass so the
CLI can print one actionable line (and never a raw traceback) and choose the right
exit code.
"""
from __future__ import annotations


class SnapError(Exception):
    """Base class for all expected, user-facing failures."""

    exit_code = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UsageError(SnapError):
    """Bad invocation or unusable input (exit code 2)."""

    exit_code = 2


class SceneError(UsageError):
    """The scene file is malformed or missing required fields (exit code 2)."""


class ThemeError(UsageError):
    """A theme name or theme JSON file could not be loaded (exit code 2)."""


class FontError(UsageError):
    """No usable monospace font was found (exit code 2)."""


class RenderError(SnapError):
    """Rendering failed for an environmental reason (exit code 1)."""
