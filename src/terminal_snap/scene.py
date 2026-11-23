"""Scene model: parse, validate and normalise a YAML/JSON terminal script.

A scene is a declarative description of one terminal window. The parser turns it
into a list of styled lines, and the validator collects *every* problem with the
line number that caused it before failing, which is what makes iterating on a
scene pleasant instead of whack-a-mole.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .ansi import EMPTY, Span, Style, cell_width, merge_spans, parse_ansi
from .errors import SceneError, ThemeError
from .themes import builtin_names, load_theme
from .yaml_lite import YamlError, parse_yaml

CHROME_CHOICES = ("macos", "windows", "plain")
LINE_KINDS = ("text", "cmd", "out", "notice", "blank")
STYLE_KEYS = ("fg", "bg", "bold", "dim", "italic", "underline", "reverse")

PALETTE = (
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
    "bright-black", "bright-red", "bright-green", "bright-yellow",
    "bright-blue", "bright-magenta", "bright-cyan", "bright-white",
)

DEFAULTS = {
    "title": "terminal",
    "theme": "dracula",
    "width": 88,
    "chrome": "macos",
    "padding": 26,
    "font_size": 15,
    "font": None,
    "line_numbers": False,
    "caption": None,
    "prompt": "\u276f",
    "scale": 2,
    "wrap": True,
    "cursor": False,
    "tab_width": 4,
    "shadow": True,
}


@dataclass
class Problem:
    """One validation problem, tied to a source line where possible."""

    line: int
    path: str
    message: str

    def render(self, filename: str) -> str:
        where = filename + (":" + str(self.line) if self.line else "")
        prefix = where + ": " if where else ""
        return prefix + self.path + ": " + self.message


@dataclass
class SceneLine:
    """One rendered line: parsed ANSI spans plus the raw text they came from."""

    spans: tuple[Span, ...]
    kind: str = "text"
    delay: int = 0
    origin: int = 0
    raw: str = ""

    @classmethod
    def from_raw(cls, raw: str, kind: str = "text", delay: int = 0, origin: int = 0,
                 tab_width: int = 4) -> SceneLine:
        return cls(tuple(parse_ansi(raw, tab_width=tab_width)), kind, delay, origin, raw)

    @property
    def text(self) -> str:
        """Plain text with ANSI colour codes removed."""
        return "".join(span.text for span in self.spans)

    def to_ansi(self) -> str:
        """Re-serialise the spans back to an ANSI string (used by record)."""
        return spans_to_ansi(self.spans)


@dataclass
class Scene:
    """A fully parsed, validated scene."""

    title: str = "terminal"
    theme: str = "dracula"
    width: int = 88
    chrome: str = "macos"
    padding: int = 26
    font_size: int = 15
    font: str | None = None
    line_numbers: bool = False
    caption: str | None = None
    prompt: str = "\u276f"
    scale: int = 2
    wrap: bool = True
    cursor: bool = False
    tab_width: int = 4
    shadow: bool = True
    lines: list[SceneLine] = field(default_factory=list)
    source: str = "<scene>"

    def to_dict(self) -> dict[str, Any]:
        """Round-trip back to the serialisable scene form (used by record)."""
        return {
            "title": self.title,
            "theme": self.theme,
            "width": self.width,
            "chrome": self.chrome,
            "padding": self.padding,
            "font_size": self.font_size,
            "font": self.font,
            "line_numbers": self.line_numbers,
            "caption": self.caption,
            "prompt": self.prompt,
            "scale": self.scale,
            "wrap": self.wrap,
            "cursor": self.cursor,
            "shadow": self.shadow,
            "lines": [{"text": line.text, "kind": line.kind} for line in self.lines],
        }


def color_to_sgr(
    value: Any, where: str, problems: list[Problem], line: int, background: bool = False
) -> str:
    """Convert a colour value to SGR parameters (empty string means default).

    The "background" flag switches the SGR family from 30/38/90 to 40/48/100, which
    is the only difference between a foreground and a background colour.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        problems.append(Problem(line, where, "colour must not be a boolean"))
        return ""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("#"):
            digits = text[1:]
            if len(digits) == 3:
                digits = "".join(c * 2 for c in digits)
            if len(digits) != 6:
                problems.append(Problem(line, where, "expected a hex colour like #ff79c6"))
                return ""
            try:
                rgb = tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                problems.append(Problem(line, where, "hex colour contains non-hex digits"))
                return ""
            return ("48;2;%d;%d;%d" if background else "38;2;%d;%d;%d") % rgb
        low = text.lower().replace("_", "-").replace(" ", "-")
        if low in PALETTE:
            index = PALETTE.index(low)
            if index < 8:
                return str((40 if background else 30) + index)
            return str((100 if background else 90) + index - 8)
        if low.isdigit():
            index = int(low)
            if 0 <= index <= 255:
                return ("48;5;" if background else "38;5;") + str(index)
        problems.append(
            Problem(
                line,
                where,
                "unknown colour " + repr(value)
                + "; use #rrggbb, a palette name or 0-255",
            )
        )
        return ""
    if isinstance(value, int):
        if 0 <= value <= 255:
            return ("48;5;" if background else "38;5;") + str(value)
        problems.append(Problem(line, where, "colour index must be 0-255"))
        return ""
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            rgb = tuple(int(c) for c in value)
        except (TypeError, ValueError):
            problems.append(Problem(line, where, "rgb list must contain three integers"))
            return ""
        if any(c < 0 or c > 255 for c in rgb):
            problems.append(Problem(line, where, "rgb components must be 0-255"))
            return ""
        return ("48;2;%d;%d;%d" if background else "38;2;%d;%d;%d") % rgb
    problems.append(Problem(line, where, "unsupported colour value: " + repr(value)))
    return ""


def _style_sgr(item: dict, path: str, problems: list[Problem], line: int) -> str:
    """Build the SGR prefix for a line's style keys."""
    parts: list[str] = []
    for key in STYLE_KEYS:
        if key not in item:
            continue
        value = item[key]
        if key in ("bold", "dim", "italic", "underline", "reverse"):
            if not isinstance(value, bool):
                problems.append(Problem(line, path + "." + key, "expected true or false"))
                continue
            if value:
                parts.append({"bold": "1", "dim": "2", "italic": "3",
                              "underline": "4", "reverse": "7"}[key])
        else:
            sgr = color_to_sgr(value, path + "." + key, problems, line, key == "bg")
            if sgr:
                if key == "fg":
                    parts.insert(0, sgr)
                else:
                    parts.append(sgr)
    if not parts:
        return ""
    return "\x1b[" + ";".join(parts) + "m"


def _as_int(value: Any, path: str, problems: list[Problem], line: int,
            low: int, high: int, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(Problem(line, path, "expected an integer"))
        return default
    if value < low or value > high:
        problems.append(Problem(line, path, "must be between " + str(low) + " and " + str(high)))
        return default
    return value


def _as_bool(value: Any, path: str, problems: list[Problem], line: int, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        problems.append(Problem(line, path, "expected true or false"))
        return default
    return value


def _as_str(value: Any, path: str, problems: list[Problem], line: int,
            default: str | None, allow_empty: bool = False) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str):
        problems.append(Problem(line, path, "expected a string"))
        return default
    if not allow_empty and not value.strip():
        problems.append(Problem(line, path, "must not be empty"))
        return default
    return value


def _parse_line_item(item: Any, index: int, doc, path: tuple, problems: list[Problem],
                     tab_width: int) -> SceneLine | None:
    line_no = doc.line_of(path)
    where = "lines[" + str(index) + "]"
    if isinstance(item, str):
        return SceneLine.from_raw(item, "text", 0, line_no, tab_width=tab_width)
    if item is None:
        problems.append(Problem(line_no, where, "line must be a string or a mapping"))
        return None
    if not isinstance(item, dict):
        problems.append(Problem(line_no, where, "line must be a string or a mapping"))
        return None
    kind = "text"
    raw: str | None = None
    for candidate in LINE_KINDS:
        if candidate in item:
            if raw is not None:
                problems.append(Problem(line_no, where, "line defines more than one kind"))
                return None
            kind = candidate
            raw = item[candidate]
            break
    if raw is None:
        problems.append(
            Problem(line_no, where, "expected one of: " + ", ".join(LINE_KINDS))
        )
        return None
    if kind == "blank":
        if raw not in (True, None):
            problems.append(Problem(line_no, where + ".blank", "blank lines take no text"))
        return SceneLine((), "blank", 0, line_no)
    if not isinstance(raw, str):
        problems.append(Problem(line_no, where + "." + kind, "expected a string"))
        return None
    delay = _as_int(item.get("delay"), where + ".delay", problems, line_no, 0, 60_000, 0)
    sgr = _style_sgr(item, where, problems, line_no)
    return SceneLine.from_raw(sgr + raw, kind, delay, line_no, tab_width=tab_width)


def parse_scene(text: str, source: str = "<scene>") -> tuple[Scene, list[Problem]]:
    """Parse and validate a scene document. Returns (scene, problems)."""
    problems: list[Problem] = []
    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SceneError(
                source + ": invalid JSON at line " + str(exc.lineno) + " column "
                + str(exc.colno) + ": " + exc.msg
            ) from exc
        doc = _JsonDocument(data)
    else:
        try:
            doc = parse_yaml(text)
        except YamlError as exc:
            raise SceneError(source + ": " + exc.message + " (line " + str(exc.line) + ")") from exc

    data = doc.data
    if data is None:
        raise SceneError(source + ": scene is empty")
    if not isinstance(data, dict):
        raise SceneError(source + ": top level of a scene must be a mapping, not "
                         + type(data).__name__)

    known = set(DEFAULTS) | {"lines"}
    for key in data:
        if key not in known:
            line_no = doc.line_of((key,))
            problems.append(
                Problem(line_no, key, "unknown field; valid fields: " + ", ".join(sorted(known)))
            )

    tab_width = _as_int(data.get("tab_width"), "tab_width", problems, doc.line_of(("tab_width",)),
                        1, 16, DEFAULTS["tab_width"])
    scene = Scene(source=source, tab_width=tab_width)
    scene.title = _as_str(data.get("title"), "title", problems, doc.line_of(("title",)),
                          DEFAULTS["title"]) or DEFAULTS["title"]
    scene.theme = _as_str(data.get("theme"), "theme", problems, doc.line_of(("theme",)),
                          DEFAULTS["theme"]) or DEFAULTS["theme"]
    scene.width = _as_int(data.get("width"), "width", problems, doc.line_of(("width",)),
                          20, 400, DEFAULTS["width"])
    scene.padding = _as_int(data.get("padding"), "padding", problems, doc.line_of(("padding",)),
                            0, 160, DEFAULTS["padding"])
    scene.font_size = _as_int(data.get("font_size"), "font_size", problems,
                              doc.line_of(("font_size",)), 6, 96, DEFAULTS["font_size"])
    scene.scale = _as_int(data.get("scale"), "scale", problems, doc.line_of(("scale",)),
                          1, 8, DEFAULTS["scale"])
    scene.font = _as_str(data.get("font"), "font", problems, doc.line_of(("font",)), None)
    scene.caption = _as_str(data.get("caption"), "caption", problems,
                            doc.line_of(("caption",)), None, allow_empty=True)
    scene.prompt = _as_str(data.get("prompt"), "prompt", problems, doc.line_of(("prompt",)),
                           DEFAULTS["prompt"], allow_empty=True) or ""
    scene.line_numbers = _as_bool(data.get("line_numbers"), "line_numbers", problems,
                                  doc.line_of(("line_numbers",)), False)
    scene.wrap = _as_bool(data.get("wrap"), "wrap", problems, doc.line_of(("wrap",)), True)
    scene.cursor = _as_bool(data.get("cursor"), "cursor", problems,
                            doc.line_of(("cursor",)), False)
    scene.shadow = _as_bool(data.get("shadow"), "shadow", problems,
                            doc.line_of(("shadow",)), True)
    chrome = data.get("chrome")
    if chrome is None:
        scene.chrome = DEFAULTS["chrome"]
    elif not isinstance(chrome, str):
        problems.append(Problem(doc.line_of(("chrome",)), "chrome", "expected a string"))
    elif chrome not in CHROME_CHOICES:
        problems.append(
            Problem(doc.line_of(("chrome",)), "chrome",
                    "must be one of: " + ", ".join(CHROME_CHOICES))
        )
    else:
        scene.chrome = chrome

    if not any("theme" in str(p.path).split(".")[0] for p in problems):
        try:
            load_theme(scene.theme)
        except ThemeError as exc:
            problems.append(Problem(doc.line_of(("theme",)), "theme", str(exc)))

    lines = data.get("lines")
    if lines is None:
        problems.append(Problem(0, "lines", "scene must define at least one line"))
    elif not isinstance(lines, list):
        problems.append(Problem(doc.line_of(("lines",)), "lines", "expected a list"))
    else:
        for index, item in enumerate(lines):
            parsed = _parse_line_item(item, index, doc, ("lines", index), problems, tab_width)
            if parsed is not None:
                scene.lines.append(parsed)
        if not scene.lines and not problems:
            problems.append(Problem(0, "lines", "scene must define at least one line"))

    problems.sort(key=lambda p: (p.line, p.path))
    return scene, problems


class _JsonDocument:
    """Minimal line table for JSON scenes (JSON has no useful line lookup here)."""

    def __init__(self, data: Any) -> None:
        self.data = data

    def line_of(self, path: tuple[Any, ...]) -> int:
        return 0


def load_scene(path: Path) -> Scene:
    """Read and validate a scene file, raising SceneError listing every problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SceneError("scene file not found: " + str(path)) from exc
    except OSError as exc:
        raise SceneError("cannot read scene file " + str(path) + ": " + str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise SceneError("scene file " + str(path) + " is not valid UTF-8: " + str(exc)) from exc
    scene, problems = parse_scene(text, source=str(path))
    if problems:
        detail = "\n".join("  " + p.render(path.name) for p in problems[:20])
        more = "" if len(problems) <= 20 else "\n  ... and " + str(len(problems) - 20) + " more"
        raise SceneError(
            "invalid scene " + str(path) + ":\n" + detail + more
        )
    return scene


def _sgr_for(style: Style) -> str:
    """Serialise a Style back into an SGR sequence (empty when it is the default)."""
    parts: list[str] = []
    if style.bold:
        parts.append("1")
    if style.dim:
        parts.append("2")
    if style.italic:
        parts.append("3")
    if style.underline:
        parts.append("4")
    if style.reverse:
        parts.append("7")
    if style.strike:
        parts.append("9")
    for ref, base in ((style.fg, 30), (style.bg, 40)):
        if ref is None:
            continue
        if ref.kind == "rgb":
            parts.extend([str(base + 8), "2", str(ref.rgb[0]), str(ref.rgb[1]), str(ref.rgb[2])])
        elif ref.index < 8:
            parts.append(str(base + ref.index))
        elif ref.index < 16:
            parts.append(str(base + 60 + ref.index - 8))
        else:
            parts.extend([str(base + 8), "5", str(ref.index)])
    return "\x1b[" + ";".join(parts) + "m" if parts else ""


def spans_to_ansi(spans: Sequence[Span]) -> str:
    """Render spans back to an ANSI-coded string, resetting at every style change."""
    out: list[str] = []
    current = EMPTY
    for span in spans:
        if not span.text:
            continue
        if span.style != current:
            sgr = _sgr_for(span.style)
            out.append(sgr if not out else "\x1b[0m" + sgr)
            current = span.style
        out.append(span.text)
    if current != EMPTY:
        out.append("\x1b[0m")
    return "".join(out)


def wrap_spans(spans: Sequence[Span], width: int) -> list[tuple[Span, ...]]:
    """Hard-wrap styled spans to a cell width, breaking on spaces when possible."""
    if width <= 0:
        return [tuple(spans)]
    lines: list[tuple[Span, ...]] = []
    current: list[Span] = []
    cells = 0
    last_space: int | None = None
    for span in spans:
        for ch in span.text:
            w = cell_width(ch)
            if cells + w > width:
                if ch == " ":
                    # The space itself does not fit: break here and drop it, which is
                    # what a terminal does, so words never get separated from a break.
                    lines.append(tuple(current))
                    current = []
                    cells = 0
                    last_space = None
                    continue
                if last_space is not None and last_space > 0:
                    head, tail = _split_cells(current, last_space)
                    lines.append(tuple(head))
                    current = tail
                    cells = sum(cell_width(c) for s in current for c in s.text)
                else:
                    lines.append(tuple(current))
                    current = []
                    cells = 0
                last_space = None
            if ch == " ":
                last_space = cells
            current.append(Span(ch, span.style))
            cells += w
    lines.append(tuple(current))
    return [tuple(merge_spans(line)) for line in lines]


def _split_cells(spans: list[Span], at: int) -> tuple[list[Span], list[Span]]:
    """Split a span list into two lists at a cell offset (space is dropped)."""
    head: list[Span] = []
    tail: list[Span] = []
    pos = 0
    for span in spans:
        for ch in span.text:
            w = cell_width(ch)
            if pos < at:
                head.append(Span(ch, span.style))
            elif pos == at and ch == " ":
                pass
            else:
                tail.append(Span(ch, span.style))
            pos += w
    return head, tail


def scene_from_text(text: str, source: str = "<inline>") -> Scene:
    """Convenience wrapper that raises on the first validation failure."""
    scene, problems = parse_scene(text, source=source)
    if problems:
        raise SceneError("\n".join(p.render(source) for p in problems))
    return scene


def iter_effective_lines(scene: Scene) -> Iterable[SceneLine]:
    """Yield lines with prompt prefixes applied, as the renderer sees them."""
    for line in scene.lines:
        if line.kind == "cmd" and scene.prompt:
            prefix = Span(scene.prompt + " ", Style(fg=None, bold=True))
            yield replace(line, spans=(prefix,) + line.spans)
        else:
            yield line


def theme_choices() -> list[str]:
    """Names accepted by the theme field (for help text and error messages)."""
    return builtin_names()
