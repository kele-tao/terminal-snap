"""terminal-snap - script terminal screenshots as YAML, render them as PNG.

Public API (stable for v1.x):

    from terminal_snap import Scene, render_scene, load_scene, parse_ansi

The CLI is a thin wrapper over these functions, so anything the terminal does can
be done from Python or CI.
"""
from __future__ import annotations

from .ansi import ColorRef, Span, Style, parse_ansi, strip_ansi, visible_length
from .errors import FontError, RenderError, SceneError, SnapError, ThemeError, UsageError
from .exporters import scene_to_html, scene_to_svg
from .fonts import FontSpec, discover_fonts, find_font
from .record import capture, scene_from_capture
from .renderer import Renderer, RenderResult, measure, render_scene
from .scene import Scene, SceneLine, load_scene, parse_scene, scene_from_text
from .themes import Theme, builtin_names, load_theme

__version__ = "1.0.0"

__all__ = [
    "ColorRef",
    "FontError",
    "FontSpec",
    "RenderError",
    "RenderResult",
    "Renderer",
    "Scene",
    "SceneError",
    "SceneLine",
    "SnapError",
    "Span",
    "Style",
    "Theme",
    "ThemeError",
    "UsageError",
    "__version__",
    "builtin_names",
    "capture",
    "discover_fonts",
    "find_font",
    "load_scene",
    "load_theme",
    "measure",
    "parse_ansi",
    "parse_scene",
    "render_scene",
    "scene_from_capture",
    "scene_from_text",
    "scene_to_html",
    "scene_to_svg",
    "strip_ansi",
    "visible_length",
]
