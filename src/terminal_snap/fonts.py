"""Monospace font discovery and cached loading.

The renderer needs a fixed-advance font: table layouts and box drawing only line
up when every glyph is the same width. We search a list of well-known monospace
faces per platform, then fall back to any font whose M/W/i/0 advance widths agree,
and finally to Pillow's bitmap default (which never fails, but is reported so the
user knows why the output looks different).
"""
from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .errors import FontError

PREFERRED = (
    "JetBrains Mono",
    "Cascadia Mono",
    "Cascadia Code",
    "Consolas",
    "SF Mono",
    "Menlo",
    "DejaVu Sans Mono",
    "Ubuntu Mono",
    "Liberation Mono",
    "Noto Sans Mono",
    "Source Code Pro",
    "Courier New",
)

FONT_GLOBS = ("*.ttf", "*.otf", "*.ttc")

FAMILY_ALIASES = {
    "consola": "Consolas",
    "consolab": "Consolas",
    "consolaz": "Consolas",
    "consolai": "Consolas",
    "cascadiamono": "Cascadia Mono",
    "cascadiacode": "Cascadia Code",
    "lucon": "Lucida Console",
    "cour": "Courier New",
    "courbd": "Courier New",
    "dejavusansmono": "DejaVu Sans Mono",
    "menlo": "Menlo",
    "jetbrainsmono": "JetBrains Mono",
    "ubuntumono": "Ubuntu Mono",
    "liberationmono": "Liberation Mono",
    "notosansmono": "Noto Sans Mono",
}


@dataclass(frozen=True)
class FontSpec:
    """A resolved monospace font."""

    path: str | None
    family: str
    index: int = 0

    @property
    def is_bitmap(self) -> bool:
        return self.path is None

    def describe(self) -> str:
        """Human-readable description used by 'fonts' output and error messages."""
        if self.is_bitmap:
            return "Pillow default bitmap font (no monospace TTF found)"
        return self.family + " (" + self.path + ")"


def font_dirs() -> list[Path]:
    """Directories that plausibly contain TrueType fonts on this platform."""
    dirs: list[Path] = []
    home = Path.home()
    if sys.platform.startswith("win"):
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        dirs += [windir / "Fonts", home / "AppData/Local/Microsoft/Windows/Fonts"]
    elif sys.platform == "darwin":
        dirs += [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library/Fonts"]
    else:
        dirs += [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            home / ".local/share/fonts",
        ]
    return [d for d in dirs if d.is_dir()]


def _iter_font_files(dirs: Iterable[Path]) -> Iterable[Path]:
    for base in dirs:
        for pattern in FONT_GLOBS:
            yield from sorted(base.rglob(pattern))


MONOSPACE_HINTS = ("mono", "code", "consol", "courier", "fixed", "typewriter", "cascadia")


def _family_of(path: Path) -> str:
    """Best-effort family name from the file name (consola -> Consolas)."""
    stem = path.stem.split("-")[0].split("_")[0]
    return FAMILY_ALIASES.get(stem.lower(), stem)


def looks_monospace(family: str) -> bool:
    """Reject symbol fonts that pass the width test but are not terminal faces.

    Wingdings and icon fonts happen to have equal advances, which makes them pass a
    pure measurement check; they are useless as a terminal font, so the family name
    has to look monospace too.
    """
    low = family.lower()
    return any(hint in low for hint in MONOSPACE_HINTS)


def _family_for_file(path: Path) -> str | None:
    """Family name for a font file, or None when it cannot be a terminal face."""
    family = _family_of(path)
    return family if looks_monospace(family) else None


def _is_fixed_advance(path: Path, index: int = 0) -> bool:
    """True when M, W, i, l and 0 all share one advance width."""
    from PIL import ImageFont

    try:
        font = ImageFont.truetype(str(path), 24, index=index)
    except OSError:
        return False
    try:
        widths = {round(font.getlength(ch), 2) for ch in ("M", "W", "i", "l", "0")}
    except Exception:
        return False
    return len(widths) == 1


@lru_cache(maxsize=1)
def discover_fonts() -> tuple[FontSpec, ...]:
    """All fixed-advance fonts found on this machine, best candidates first."""
    found: list[FontSpec] = []
    seen: set[str] = set()
    families: set[str] = set()
    for path in _iter_font_files(font_dirs()):
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        family = _family_for_file(path)
        if family is None or family in families:
            continue
        if not _is_fixed_advance(path):
            continue
        families.add(family)
        found.append(FontSpec(str(path), family))

    def rank(spec: FontSpec) -> tuple[int, str]:
        fam = spec.family.replace(" ", "").lower()
        for pos, pref in enumerate(PREFERRED):
            if fam == pref.replace(" ", "").lower():
                return (pos, fam)
        return (len(PREFERRED), fam)

    found.sort(key=rank)
    return tuple(found)


def find_font(family: str | None = None) -> FontSpec:
    """Resolve the requested font family, or the best available monospace face."""
    fonts = discover_fonts()
    if not fonts:
        return FontSpec(None, "default-bitmap")
    if family:
        wanted = family.replace(" ", "").lower()
        for spec in fonts:
            if spec.family.replace(" ", "").lower() == wanted:
                return spec
        for spec in fonts:
            if wanted in spec.family.replace(" ", "").lower():
                return spec
        available = ", ".join(sorted({s.family for s in fonts})[:12])
        raise FontError(
            "font " + repr(family) + " is not installed on this machine; found: " + available
        )
    return fonts[0]


@lru_cache(maxsize=64)
def load_font(path: str | None, size: int, bold: bool = False, italic: bool = False):
    """Load a Pillow font object, raising FontError instead of leaking OSError."""
    from PIL import ImageFont

    if path is None:
        return ImageFont.load_default()
    if bold or italic:
        candidate = variant_path(Path(path), bold, italic)
        if candidate is not None:
            path = str(candidate)
    try:
        return ImageFont.truetype(str(path), size)
    except OSError as exc:
        raise FontError("cannot load font " + str(path) + ": " + str(exc)) from exc


def variant_path(base: Path, bold: bool, italic: bool) -> Path | None:
    """Find a bold/italic sibling of a font file (consola.ttf -> consolab.ttf)."""
    table = {(False, False): "", (True, False): "b", (False, True): "i", (True, True): "z"}
    if base.suffix.lower() == ".ttc":
        return None
    suffix = table[(bold, italic)]
    if not suffix:
        return None
    candidate = base.with_name(base.stem + suffix + base.suffix)
    return candidate if candidate.exists() else None


# ---------------------------------------------------------------------------
# Glyph fallback: CJK text and emoji are the two things that make a terminal
# screenshot look broken. Monospace faces rarely cover them, so when the primary
# font has no glyph we look for any installed font that does (CJK UI fonts,
# Segoe UI Emoji, symbol fonts) and draw just those cells with it.
# ---------------------------------------------------------------------------

FALLBACK_FILES = (
    "msyh.ttc",
    "msyhbd.ttc",
    "simsun.ttc",
    "seguisym.ttf",
    "seguiemj.ttf",
    "NotoSansCJK-Regular.ttc",
    "NotoSansSymbols2-Regular.ttf",
    "AppleColorEmoji.ttc",
    "DejaVuSans.ttf",
)


def _candidate_font_files() -> list[Path]:
    """Font files worth trying for a missing glyph, cheap and likely ones first."""
    by_name: dict[str, Path] = {}
    everything: list[Path] = []
    for directory in font_dirs():
        for path in _iter_font_files([directory]):
            everything.append(path)
            by_name.setdefault(path.name.lower(), path)
    ordered: list[Path] = []
    for name in FALLBACK_FILES:
        found = by_name.get(name.lower())
        if found is not None and found not in ordered:
            ordered.append(found)
    for path in everything:
        if path not in ordered and path.suffix.lower() in (".ttf", ".ttc", ".otf"):
            ordered.append(path)
    return ordered[:400]


def _tofu_signature(font) -> bytes:
    mask = font.getmask("\uffff")
    return bytes(mask) + str(mask.size).encode()


@lru_cache(maxsize=8)
def _fallback_index(size: int) -> tuple[tuple[str, bytes], ...]:
    """Fonts usable for fallback at this size, with their notdef signature."""
    out: list[tuple[str, bytes]] = []
    for path in _candidate_font_files():
        try:
            font = load_font(str(path), size)
        except FontError:
            continue
        try:
            out.append((str(path), _tofu_signature(font)))
        except Exception:
            continue
    return tuple(out)


@lru_cache(maxsize=4096)
def fallback_font_path(ch: str, size: int) -> str | None:
    """Return a font path that can draw this character, or None when none can."""
    for path, tofu in _fallback_index(int(size)):
        try:
            font = load_font(path, int(size))
            mask = font.getmask(ch)
        except Exception:
            continue
        if not mask.getbbox():
            continue
        if bytes(mask) + str(mask.size).encode() == tofu:
            continue
        return path
    return None

