"""ANSI SGR parsing: text with escape codes -> styled spans.

Supports the subset a terminal actually emits for documentation screenshots:

* SGR 0-9 (reset, bold, dim, italic, underline, blink, reverse, hidden, strike)
* SGR 22-29 (the "off" switches)
* SGR 30-37 / 40-47 basic colours and 90-97 / 100-107 bright colours
* SGR 38;5;N / 48;5;N 256-colour palette, and 38;2;R;G;B / 48;2;R;G;B truecolor
* SGR 39 / 49 default foreground / background
* carriage return, backspace and tab normalisation so progress bars render sanely

Anything else is ignored, which is what makes parsing 20 years of log output safe.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass(frozen=True)
class ColorRef:
    """A colour as written in the input: palette index or RGB triple."""

    kind: str  # "index" | "rgb"
    index: int = 0
    rgb: tuple[int, int, int] = (0, 0, 0)


@dataclass(frozen=True)
class Style:
    """A complete text style; None means "use the theme default"."""

    fg: ColorRef | None = None
    bg: ColorRef | None = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False
    strike: bool = False
    hidden: bool = False


EMPTY = Style()


@dataclass(frozen=True)
class Span:
    """A run of text that shares one style."""

    text: str
    style: Style = EMPTY

    def __len__(self) -> int:
        return len(self.text)


def xterm256_rgb(index: int) -> tuple[int, int, int]:
    """Convert a 256-colour palette index >= 16 to RGB (xterm defaults)."""
    if index < 0 or index > 255:
        raise ValueError("colour index out of range: " + str(index))
    if index < 16:
        raise ValueError("system colours 0-15 are theme defined")
    if index < 232:
        n = index - 16
        steps = (0, 95, 135, 175, 215, 255)
        return (steps[n // 36], steps[(n // 6) % 6], steps[n % 6])
    level = 8 + (index - 232) * 10
    return (level, level, level)


_ATTR_ON = {
    1: "bold", 2: "dim", 3: "italic", 4: "underline", 7: "reverse", 8: "hidden", 9: "strike",
}
_ATTR_OFF = {22: ("bold", "dim"), 23: ("italic",), 24: ("underline",), 27: ("reverse",),
             28: ("hidden",), 29: ("strike",)}


def _apply(style: Style, codes: Sequence[int]) -> Style:
    """Apply one SGR parameter list to a style and return the new style.

    Styles are immutable dataclasses; instead of calling dataclasses.replace() for
    every single code (which dominates log parsing), the fields are mutated once per
    SGR sequence and a fresh Style is built at the end.
    """
    if not codes:
        return EMPTY
    values = {
        "fg": style.fg,
        "bg": style.bg,
        "bold": style.bold,
        "dim": style.dim,
        "italic": style.italic,
        "underline": style.underline,
        "reverse": style.reverse,
        "strike": style.strike,
        "hidden": style.hidden,
    }
    i = 0
    while i < len(codes):
        code = codes[i]
        if code == 0:
            values = dict.fromkeys(values, None)
            values.update({k: False for k in values if k not in ("fg", "bg")})
        elif code in _ATTR_ON:
            values[_ATTR_ON[code]] = True
        elif code in _ATTR_OFF:
            for name in _ATTR_OFF[code]:
                values[name] = False
        elif 30 <= code <= 37:
            values["fg"] = ColorRef("index", code - 30)
        elif code == 39:
            values["fg"] = None
        elif 40 <= code <= 47:
            values["bg"] = ColorRef("index", code - 40)
        elif code == 49:
            values["bg"] = None
        elif 90 <= code <= 97:
            values["fg"] = ColorRef("index", code - 90 + 8)
        elif 100 <= code <= 107:
            values["bg"] = ColorRef("index", code - 100 + 8)
        elif code in (38, 48):
            target = "fg" if code == 38 else "bg"
            if i + 2 < len(codes) and codes[i + 1] == 5:
                values[target] = ColorRef("index", codes[i + 2] % 256)
                i += 2
            elif i + 4 < len(codes) and codes[i + 1] == 2:
                values[target] = ColorRef(
                    "rgb", rgb=(codes[i + 2], codes[i + 3], codes[i + 4])
                )
                i += 4
            else:
                break
        i += 1
    return Style(**values)  # type: ignore[arg-type]


_STYLE_CACHE: dict[tuple[Style, str], Style] = {}
_SGR_SEQ_CACHE: dict[str, tuple[int, ...]] = {}


def parse_sgr_cached(seq: str) -> tuple[int, ...]:
    """Parse an SGR parameter string with a memo table (log lines repeat them)."""
    cached = _SGR_SEQ_CACHE.get(seq)
    if cached is not None:
        return cached
    codes = tuple(parse_sgr(seq))
    if len(_SGR_SEQ_CACHE) < 4096:
        _SGR_SEQ_CACHE[seq] = codes
    return codes


def apply_cached(style: Style, seq: str) -> Style:
    """Apply an SGR parameter string to a style, memoised on (style, sequence).

    Real logs use a handful of distinct colour sequences, so after the first few
    hundred cells parsing collapses to two dictionary lookups per escape sequence.
    """
    key = (style, seq)
    cached = _STYLE_CACHE.get(key)
    if cached is not None:
        return cached
    result = _apply(style, list(parse_sgr_cached(seq)))
    if len(_STYLE_CACHE) < 8192:
        _STYLE_CACHE[key] = result
    return result


def parse_sgr(seq: str) -> list[int]:
    """Split an SGR parameter string into integers ('1;31' -> [1, 31])."""
    if not seq:
        return []
    out: list[int] = []
    for part in seq.split(";"):
        try:
            out.append(int(part) if part else 0)
        except ValueError:
            continue
    return out


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences (used for measuring and budgeting)."""
    return ANSI_RE.sub("", text.replace("\x1b[m", ""))


def _cells_to_spans(cells: list[tuple[str, Style]]) -> list[Span]:
    spans: list[Span] = []
    for ch, style in cells:
        if spans and spans[-1].style == style:
            spans[-1] = Span(spans[-1].text + ch, style)
        else:
            spans.append(Span(ch, style))
    return spans


CONTROL_CHARS = ("\r", "\b", "\t", "\x00", "\x07", "\x0b", "\x0c")
_CONTROL_RE = re.compile("[\r\b\t\x00\x07\x0b\x0c]")


def merge_spans(spans: Iterable[Span]) -> list[Span]:
    """Coalesce adjacent spans that share a style (and drop empty ones).

    Wrapping naturally produces one span per character; merging them back means the
    renderer issues one draw call per style run instead of one per cell, and the SVG
    exporter writes one <text> element instead of hundreds.
    """
    merged: list[Span] = []
    for span in spans:
        if not span.text:
            continue
        if merged and merged[-1].style == span.style:
            merged[-1] = Span(merged[-1].text + span.text, span.style)
        else:
            merged.append(span)
    return merged


def normalize_controls(spans: Iterable[Span], tab_width: int = 4) -> list[Span]:
    """Interpret CR / BS / TAB / NUL exactly like a single terminal line does.

    The overwhelming majority of lines contain no control characters at all, so that
    case returns the spans untouched (minus empty runs) instead of walking every
    character through a cell buffer. This is the difference between parsing a 5 MB
    log in 3 seconds and in 11.
    """
    materialised = [span for span in spans if span.text]
    if _CONTROL_RE.search("".join(span.text for span in materialised)) is None:
        return materialised
    cells: list[tuple[str, Style]] = []
    pos = 0
    for span in materialised:
        for ch in span.text:
            if ch == "\r":
                pos = 0
                continue
            if ch == "\b":
                pos = max(0, pos - 1)
                continue
            if ch == "\t":
                pad = tab_width - (pos % tab_width)
                for _ in range(pad):
                    if pos < len(cells):
                        cells[pos] = (" ", span.style)
                    else:
                        cells.append((" ", span.style))
                    pos += 1
                continue
            if ch in ("\x00", "\x07", "\x0b", "\x0c"):
                continue
            if pos < len(cells):
                cells[pos] = (ch, span.style)
            else:
                cells.append((ch, span.style))
            pos += 1
    return _cells_to_spans(cells)


def parse_ansi(text: str, tab_width: int = 4) -> list[Span]:
    """Parse a single line of ANSI-coloured text into styled spans."""
    if "\x1b" not in text:
        if not text:
            return []
        if _CONTROL_RE.search(text) is None:
            return [Span(text, EMPTY)]
    spans: list[Span] = []
    style = EMPTY
    pos = 0
    for m in SGR_RE.finditer(text):
        if m.start() > pos:
            spans.append(Span(text[pos:m.start()], style))
        style = apply_cached(style, m.group(1))
        pos = m.end()
    if pos < len(text):
        spans.append(Span(text[pos:], style))
    return normalize_controls(spans, tab_width=tab_width)


def cell_width(ch: str) -> int:
    """Best-effort wcwidth: 0 for combining marks, 2 for East Asian wide chars."""
    if unicodedata.combining(ch) or ch in ("\u200b", "\ufeff"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def visible_length(spans: Sequence[Span]) -> int:
    """Number of terminal cells the spans occupy (wide CJK chars count as 2)."""
    return sum(cell_width(ch) for span in spans for ch in span.text)


def plain_text(spans: Sequence[Span]) -> str:
    """Concatenate span text back into a plain string."""
    return "".join(span.text for span in spans)
