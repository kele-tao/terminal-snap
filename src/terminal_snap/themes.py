"""Theme loading and colour resolution.

A theme is a small JSON document: window background, text colour, chrome colours
and a 16-colour ANSI palette. Eight themes ship inside the package; custom themes
are plain JSON files with the same field names, so users can copy one and tweak
three hex codes.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .ansi import ColorRef, Style, xterm256_rgb
from .errors import ThemeError

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
BUILTIN_DIR = Path(__file__).resolve().parent / "themes"

RGB = tuple[int, int, int]


def parse_hex(value: str, where: str = "colour") -> RGB:
    """Parse a hex colour such as #rgb or #rrggbb into an RGB triple."""
    if not isinstance(value, str) or not HEX_RE.match(value.strip()):
        raise ThemeError(where + " must be a hex colour like #1e1f29, got " + repr(value))
    text = value.strip()[1:]
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """Linear blend between two colours; t=0 gives a, t=1 gives b."""
    t = max(0.0, min(1.0, t))
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def _luminance(rgb: RGB) -> float:
    def channel(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])


def contrast_ratio(a: RGB, b: RGB) -> float:
    """WCAG contrast ratio between two colours (1.0 to 21.0)."""
    la, lb = _luminance(a), _luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


@dataclass(frozen=True)
class Theme:
    """A resolved theme: every colour is an RGB triple."""

    name: str
    label: str
    background: RGB
    foreground: RGB
    canvas: RGB
    chrome_background: RGB
    chrome_foreground: RGB
    chrome_border: RGB
    caption: RGB
    line_number: RGB
    accent: RGB
    cursor: RGB
    palette: tuple[RGB, ...]

    def fg(self, ref: ColorRef | None) -> RGB:
        """Resolve a foreground reference, honouring 256-colour and truecolor."""
        if ref is None:
            return self.foreground
        if ref.kind == "rgb":
            return ref.rgb
        if ref.kind != "index":
            raise ThemeError("unknown colour kind: " + ref.kind)
        if ref.index < 16:
            return self.palette[ref.index]
        return xterm256_rgb(ref.index)

    def bg(self, ref: ColorRef | None) -> RGB | None:
        """Resolve a background reference; None means the terminal background."""
        if ref is None:
            return None
        return self.fg(ref)

    def resolve(self, style: Style) -> tuple[RGB, RGB | None]:
        """Resolve a style to foreground and background RGB, applying dim and reverse."""
        fg = self.fg(style.fg)
        bg = self.bg(style.bg)
        if style.reverse:
            fg, bg = (bg if bg is not None else self.background), fg
        if style.dim:
            base = bg if bg is not None else self.background
            fg = mix(fg, base, 0.45)
        if style.hidden:
            fg = bg if bg is not None else self.background
        return fg, bg


def _require(data: dict, key: str, where: str) -> object:
    if key not in data:
        raise ThemeError(where + ": missing required field " + repr(key))
    return data[key]


def theme_from_dict(data: dict, source: str = "<inline>") -> Theme:
    """Validate a theme mapping and convert it to a Theme."""
    if not isinstance(data, dict):
        raise ThemeError(source + ": theme must be a JSON object")
    nest = data.get("chrome") or {}
    if not isinstance(nest, dict):
        raise ThemeError(source + ": chrome must be an object")
    palette_raw = _require(data, "palette", source)
    if not isinstance(palette_raw, list) or len(palette_raw) < 16:
        raise ThemeError(source + ": palette must be a list of at least 16 hex colours")
    palette = tuple(
        parse_hex(c, source + " palette[" + str(i) + "]")
        for i, c in enumerate(palette_raw[:16])
    )
    background = parse_hex(_require(data, "background", source), source + " background")
    foreground = parse_hex(_require(data, "foreground", source), source + " foreground")
    record = {
        "name": str(data.get("name", "custom")),
        "label": str(data.get("label", data.get("name", "Custom"))),
        "background": background,
        "foreground": foreground,
        "canvas": parse_hex(data.get("canvas", data["background"]), source + " canvas"),
        "chrome_background": parse_hex(
            nest.get("background", mix(background, (255, 255, 255), 0.06)),
            source + " chrome.background",
        ),
        "chrome_foreground": parse_hex(
            nest.get("foreground", data["foreground"]), source + " chrome.foreground"
        ),
        "chrome_border": parse_hex(
            nest.get("border", mix(background, (0, 0, 0), 0.35)),
            source + " chrome.border",
        ),
        "caption": parse_hex(data.get("caption", data["foreground"]), source + " caption"),
        "line_number": parse_hex(
            data.get("line_number", nest.get("foreground", data["foreground"])),
            source + " line_number",
        ),
        "accent": parse_hex(data.get("accent", palette_raw[4]), source + " accent"),
        "cursor": parse_hex(data.get("cursor", data["foreground"]), source + " cursor"),
        "palette": palette,
    }
    return Theme(**record)  # type: ignore[arg-type]


def builtin_names() -> list[str]:
    """Names of the themes shipped with the package, alphabetically."""
    return sorted(p.stem for p in BUILTIN_DIR.glob("*.json"))


def load_theme(name_or_path: str) -> Theme:
    """Load a built-in theme by name, or a custom theme JSON file by path."""
    if not isinstance(name_or_path, str) or not name_or_path.strip():
        raise ThemeError("theme must be a non-empty string")
    candidate = Path(name_or_path)
    if candidate.suffix.lower() == ".json" or candidate.exists():
        return load_theme_file(candidate)
    slug = name_or_path.strip().lower().replace(" ", "-")
    path = BUILTIN_DIR / (slug + ".json")
    if not path.exists():
        names = ", ".join(builtin_names())
        raise ThemeError("unknown theme " + repr(name_or_path) + "; built-in themes: " + names)
    return load_theme_file(path)


def load_theme_file(path: Path) -> Theme:
    """Load a theme from a JSON file, with a friendly error on syntax problems."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ThemeError("cannot read theme file " + str(path) + ": " + str(exc)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ThemeError(
            "theme file " + str(path) + " is not valid JSON: line " + str(exc.lineno)
            + " column " + str(exc.colno) + ": " + exc.msg
        ) from exc
    return theme_from_dict(data, source=str(path))


PALETTE_NAMES = (
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
    "bright-black", "bright-red", "bright-green", "bright-yellow",
    "bright-blue", "bright-magenta", "bright-cyan", "bright-white",
)


def palette_report(theme: Theme) -> Iterable[tuple[str, str]]:
    """Yield (palette name, hex) rows for the themes command."""
    for label, rgb in zip(PALETTE_NAMES, theme.palette):
        yield label, "#%02x%02x%02x" % rgb


def check_contrast(theme: Theme) -> list[str]:
    """Return human-readable warnings about low-contrast theme colours."""
    warnings: list[str] = []
    main = contrast_ratio(theme.foreground, theme.background)
    if main < 4.5:
        warnings.append(
            theme.name + ": foreground/background contrast is %.2f:1 (below WCAG AA 4.5:1)" % main
        )
    # Only the chromatic slots are checked. Slots 0/8 are "black" and 7/15 are
    # "white": themes legitimately point those at their own background and text
    # colours (Solarized Light does exactly that), and reverse-video uses them as a
    # pair, so measuring each against the background says nothing useful.
    chromatic = (*range(1, 7), *range(9, 15))
    for index in chromatic:
        ratio = contrast_ratio(theme.palette[index], theme.background)
        if ratio < 2.0:
            warnings.append(
                theme.name + ": palette colour " + str(index) + " contrast is %.2f:1" % ratio
            )
    return warnings
