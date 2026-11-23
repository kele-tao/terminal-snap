"""The Pillow renderer: scene -> pixel-perfect PNG.

Layout is a fixed character grid: every cell is exactly one measured advance wide,
so box drawing, aligned tables and progress bars line up. Everything is drawn at
scale x font size (2x by default), which is what keeps the output crisp when GitHub
downscales it in a README.

Determinism: given the same scene, font file and Pillow version the output bytes are
identical. No timestamps, no random jitter, no sub-pixel drift - the soft drop
shadow is a fixed blur of a fixed shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from .ansi import Span, Style, cell_width
from .errors import RenderError
from .fonts import FontSpec, fallback_font_path, find_font, load_font
from .scene import Scene, SceneLine, wrap_spans
from .themes import Theme, load_theme, mix

MIN_SCALE = 1
MAX_SCALE = 8
LINE_HEIGHT_RATIO = 1.62


@dataclass
class RenderResult:
    """Everything the CLI and tests want to know after a render."""

    path: Path
    width: int
    height: int
    columns: int
    rows: int
    font: FontSpec
    theme: Theme
    missing_glyphs: tuple[str, ...] = ()
    fallback_glyphs: tuple[str, ...] = ()
    wrapped_rows: int = 0
    warnings: list[str] = field(default_factory=list)


def _cell_width(font, sample: str = "M") -> int:
    try:
        value = font.getlength(sample)
    except Exception as exc:  # pragma: no cover - defensive for exotic fonts
        raise RenderError("font has no measurable advance width: " + str(exc)) from exc
    width = round(value)
    if width <= 0:
        raise RenderError("font advance width measured as " + str(value) + "px; pick another font")
    return width


def _signature(mask) -> bytes:
    return bytes(mask) + str(mask.size).encode()


PRIMARY = "primary"
FALLBACK = "fallback"
MISSING = "missing"


class GlyphChecker:
    """Classifies every character once: primary font, fallback font, or nothing.

    getmask() is not cheap, so the answer is cached per character. Rendering a
    1000-row scene touches each distinct character once instead of once per cell.
    """

    def __init__(self, font, size: int) -> None:
        self.font = font
        self.size = size
        self._tofu = _signature(font.getmask("\uffff"))
        self._cache: dict[str, tuple[str, str | None]] = {}

    def lookup(self, ch: str) -> tuple[str, str | None]:
        """Return (kind, fallback_path) for one character."""
        if ch in " \t\n":
            return PRIMARY, None
        cached = self._cache.get(ch)
        if cached is not None:
            return cached
        try:
            mask = self.font.getmask(ch)
            drawable = bool(mask.getbbox()) and _signature(mask) != self._tofu
        except Exception:
            drawable = False
        if drawable:
            result: tuple[str, str | None] = (PRIMARY, None)
        else:
            path = fallback_font_path(ch, self.size)
            result = (FALLBACK, path) if path else (MISSING, None)
        self._cache[ch] = result
        return result


class Renderer:
    """Draws a Scene into a PNG. Reuse one instance to share glyph caches."""

    def __init__(self, scene: Scene, theme: Theme, font: FontSpec | None = None) -> None:
        self.scene = scene
        self.theme = theme
        self.font_spec = font or find_font(scene.font)
        self.scale = max(MIN_SCALE, min(MAX_SCALE, scene.scale))
        self.font_size = scene.font_size * self.scale
        self.font = load_font(self.font_spec.path, self.font_size)
        self.cw = _cell_width(self.font)
        self.line_height = round(self.font_size * LINE_HEIGHT_RATIO)
        self.glyphs = GlyphChecker(self.font, self.font_size)
        self._fallback_cache: dict[tuple[str, bool, bool], object] = {}

    # -- fonts --------------------------------------------------------------
    def _font_for(self, path: str | None, bold: bool, italic: bool):
        if path is None:
            return load_font(self.font_spec.path, self.font_size, bold, italic)
        key = (path, bold, italic)
        cached = self._fallback_cache.get(key)
        if cached is None:
            cached = load_font(path, self.font_size, bold, italic)
            self._fallback_cache[key] = cached
        return cached

    def _glyph_font(self, ch: str, style: Style):
        """Return (font, fallback_path) for one character."""
        path = self.glyphs.font_path_for(ch)
        return self._font_for(path, style.bold, style.italic), path

    # -- text ---------------------------------------------------------------
    def _draw_spans(
        self,
        draw: ImageDraw.ImageDraw,
        spans,
        x_cells: int,
        top: int,
        cell_limit: int | None = None,
        missing: list[str] | None = None,
        fallbacks: list[str] | None = None,
        x_offset: int = 0,
    ) -> int:
        """Draw styled spans starting at cell offset x_cells; returns the end cell."""
        theme = self.theme
        cw = self.cw
        lh = self.line_height
        col = x_cells
        run: list[str] = []
        run_style: Style | None = None
        run_font = None
        run_start = col

        def flush() -> None:
            nonlocal run, run_style, run_start
            if not run:
                return
            style = run_style or Style()
            fg, bg = theme.resolve(style)
            text = "".join(run)
            px = x_offset + run_start * cw
            cells = sum(cell_width(c) for c in text)
            if bg is not None:
                draw.rectangle([px, top, px + cells * cw - 1, top + lh - 1], fill=bg)
            draw.text((px, top), text, font=run_font, fill=fg, anchor="la")
            if style.underline:
                y = top + round(self.font_size * 1.2)
                draw.rectangle([px, y, px + max(1, cells * cw - 2), y + max(1, self.scale)],
                               fill=fg)
            if style.strike:
                y = top + round(self.font_size * 0.62)
                draw.rectangle([px, y, px + max(1, cells * cw - 2), y + max(1, self.scale) - 1],
                               fill=fg)
            run = []
            run_start = col

        for span in spans:
            for ch in span.text:
                w = cell_width(ch)
                if cell_limit is not None and col + w > cell_limit:
                    flush()
                    return col
                kind, path = self.glyphs.lookup(ch)
                if kind == MISSING:
                    if missing is not None and ch not in missing:
                        missing.append(ch)
                    flush()
                    col += w
                    continue
                if kind == FALLBACK and fallbacks is not None and ch not in fallbacks:
                    fallbacks.append(ch)
                font = self._font_for(path, span.style.bold, span.style.italic)
                if run and (span.style != run_style or font is not run_font):
                    flush()
                if not run:
                    run_style = span.style
                    run_font = font
                    run_start = col
                run.append(ch)
                col += w
        flush()
        return col

    # -- window furniture ---------------------------------------------------
    def _draw_shadow(self, image: Image.Image, box: tuple[int, int, int, int]) -> None:
        """Composite a soft drop shadow behind the window.

        A Gaussian blur at render resolution costs more than everything else combined,
        so the shadow is built from a handful of nested rounded rectangles with
        decreasing alpha: it reads as a soft shadow, it is deterministic, and it costs
        a few milliseconds instead of hundreds.
        """
        if not self.scene.shadow:
            return
        layers = 7
        offset = max(4, self.scale * 6)
        x0, y0, x1, y1 = box
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for step in range(layers, 0, -1):
            grow = round(step * self.scale * 1.6)
            alpha = max(6, round(46 / step))
            draw.rounded_rectangle(
                [x0 + offset // 2 - grow // 2, y0 + offset - grow // 2,
                 x1 + offset // 2 + grow // 2, y1 + offset + grow // 2],
                radius=max(4, round(self.scale * 7)) + grow,
                fill=(0, 0, 0, alpha),
            )
        image.alpha_composite(overlay)

    def _draw_chrome(self, draw: ImageDraw.ImageDraw, x0: int, y0: int, w: int, h: int) -> None:
        theme = self.theme
        scene = self.scene
        draw.rectangle([x0, y0, x0 + w, y0 + h - 1], fill=theme.chrome_background)
        draw.line([x0, y0 + h - 1, x0 + w, y0 + h - 1], fill=theme.chrome_border,
                  width=max(1, self.scale))
        dot_r = max(3, round(self.scale * 4.6))
        cy = y0 + h // 2
        if scene.chrome == "macos":
            cx = x0 + round(self.scale * 14)
            for colour in ((255, 95, 87), (254, 188, 46), (40, 200, 64)):
                draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=colour)
                cx += dot_r * 3
        elif scene.chrome == "windows":
            symbol_font = load_font(self.font_spec.path, round(self.font_size * 0.8))
            cx = x0 + w - round(self.scale * 18)
            for glyph in ("-", "\u25a1", "\u00d7"):
                draw.text((cx, cy), glyph, font=symbol_font, fill=theme.chrome_foreground,
                          anchor="mm")
                cx += round(self.scale * 13)
        title_font = load_font(self.font_spec.path, round(self.font_size * 0.86))
        if scene.chrome == "macos":
            draw.text((x0 + w // 2, cy), scene.title, font=title_font,
                      fill=theme.chrome_foreground, anchor="mm")
        else:
            draw.text((x0 + round(self.scale * 14), cy), scene.title, font=title_font,
                      fill=theme.chrome_foreground, anchor="lm")

    def _draw_caption(self, draw: ImageDraw.ImageDraw, x0: int, y0: int, w: int, h: int) -> None:
        if not self.scene.caption:
            return
        theme = self.theme
        draw.rectangle([x0, y0, x0 + w, y0 + h - 1], fill=theme.chrome_background)
        draw.line([x0, y0, x0 + w, y0], fill=theme.chrome_border, width=max(1, self.scale))
        font = load_font(self.font_spec.path, round(self.font_size * 0.82))
        draw.text((x0 + w // 2, y0 + h // 2), self.scene.caption, font=font,
                  fill=theme.caption, anchor="mm")

    # -- layout -------------------------------------------------------------
    def _rows(self) -> tuple[list[list[Span]], list[int | None], int]:
        scene = self.scene
        rows: list[list[Span]] = []
        numbers: list[int | None] = []
        wrapped = 0
        for index, line in enumerate(scene.lines):
            spans = self._prefixed(line)
            if not spans:
                rows.append([])
                numbers.append(index + 1)
                continue
            if scene.wrap:
                pieces = wrap_spans(spans, scene.width)
                if len(pieces) > 1:
                    wrapped += 1
                for piece_index, piece in enumerate(pieces):
                    rows.append(list(piece))
                    numbers.append(index + 1 if piece_index == 0 else None)
            else:
                rows.append(list(spans))
                numbers.append(index + 1)
        if not rows:
            rows = [[]]
            numbers = [1]
        return rows, numbers, wrapped

    def _prefixed(self, line: SceneLine) -> list[Span]:
        spans = list(line.spans)
        if line.kind == "cmd" and self.scene.prompt:
            spans = [Span(self.scene.prompt + " ", Style(bold=True))] + spans
        elif line.kind == "notice" and not any(s.style.fg is not None for s in spans):
            spans = [Span(s.text, Style(dim=True)) for s in spans]
        return spans

    def _geometry(self, rows: list[list[Span]]) -> dict[str, int]:
        scene = self.scene
        columns = scene.width
        for spans in rows:
            columns = max(columns, sum(cell_width(ch) for span in spans for ch in span.text))
        gutter = gutter_cells(scene)
        pad = scene.padding * self.scale
        chrome_h = chrome_height(scene, self.font_size)
        caption_h = caption_height(scene, self.font_size)
        width = max((columns + gutter) * self.cw + pad * 2, pad * 2 + self.cw * 8)
        height = chrome_h + caption_h + len(rows) * self.line_height + pad * 2
        return {
            "columns": columns,
            "rows": len(rows),
            "gutter": gutter,
            "pad": pad,
            "chrome": chrome_h,
            "caption": caption_h,
            "width": width,
            "height": height,
        }

    # -- main ---------------------------------------------------------------
    def render(self) -> tuple[Image.Image, RenderResult]:
        scene = self.scene
        theme = self.theme
        scale = self.scale
        rows, numbers, wrapped = self._rows()
        geo = self._geometry(rows)
        width, height = geo["width"], geo["height"]
        image = Image.new("RGBA", (width, height), theme.canvas + (255,))
        box = (0, 0, width - 1, height - 1)
        self._draw_shadow(image, box)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            box, radius=max(4, round(scale * 7)), fill=theme.background + (255,),
            outline=theme.chrome_border + (255,), width=max(1, scale),
        )
        if geo["chrome"]:
            self._draw_chrome(draw, 0, 0, width - 1, geo["chrome"])
        if geo["caption"]:
            self._draw_caption(draw, 0, height - geo["caption"] - 1, width - 1, geo["caption"])

        missing: list[str] = []
        fallbacks: list[str] = []
        left = geo["pad"]
        top = geo["chrome"] + geo["pad"]
        gutter = geo["gutter"]
        number_font = load_font(self.font_spec.path, round(self.font_size * 0.8))
        for row_index, spans in enumerate(rows):
            y = top + row_index * self.line_height
            if gutter:
                label = numbers[row_index] if row_index < len(numbers) else None
                if label is not None:
                    draw.text((left, y), str(label).rjust(gutter - 2), font=number_font,
                              fill=theme.line_number, anchor="la")
                sep_x = left + (gutter - 2) * self.cw + round(self.cw * 0.2)
                draw.rectangle(
                    [sep_x, y + round(self.font_size * 0.12), sep_x,
                     y + self.line_height - round(self.font_size * 0.3)],
                    fill=mix(theme.line_number, theme.background, 0.45),
                )
            self._draw_spans(draw, spans, gutter, y, cell_limit=geo["columns"],
                             missing=missing, fallbacks=fallbacks, x_offset=left)

        if scene.cursor and rows:
            cells = sum(cell_width(ch) for span in rows[-1] for ch in span.text)
            cx = left + cells * self.cw
            cy = top + (len(rows) - 1) * self.line_height
            draw.rectangle(
                [cx, cy + round(self.font_size * 0.1), cx + self.cw - 2,
                 cy + self.line_height - 1],
                fill=mix(theme.cursor, theme.background, 0.35),
            )

        result = RenderResult(
            path=Path("."),
            width=width,
            height=height,
            columns=geo["columns"],
            rows=len(rows),
            font=self.font_spec,
            theme=theme,
            missing_glyphs=tuple(missing),
            fallback_glyphs=tuple(fallbacks),
            wrapped_rows=wrapped,
        )
        if fallbacks:
            result.warnings.append(
                "rendered " + str(len(fallbacks)) + " glyph(s) with a fallback font: "
                + " ".join(fallbacks[:12])
            )
        if missing:
            result.warnings.append(
                "no installed font can draw: " + " ".join(missing)
                + " (rendered as blank cells)"
            )
        return image, result


def gutter_cells(scene: Scene) -> int:
    """Cells reserved for the line-number gutter (0 when disabled)."""
    if not scene.line_numbers:
        return 0
    return len(str(max(1, len(scene.lines)))) + 2


def chrome_height(scene: Scene, font_size: int) -> int:
    """Pixel height of the window chrome bar."""
    if scene.chrome == "plain":
        return 0
    return round(font_size * 2.15)


def caption_height(scene: Scene, font_size: int) -> int:
    """Pixel height of the caption bar (0 when no caption is set)."""
    return round(font_size * 1.95) if scene.caption else 0


def render_scene(scene: Scene, out: Path, theme: Theme | None = None) -> RenderResult:
    """Render a scene to a PNG file and return the render metadata."""
    theme = theme or load_theme(scene.theme)
    renderer = Renderer(scene, theme)
    image, result = renderer.render()
    out = Path(out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(out, format="PNG", optimize=True)
    except OSError as exc:
        raise RenderError("cannot write " + str(out) + ": " + str(exc)) from exc
    result.path = out
    return result


def measure(scene: Scene) -> dict[str, int]:
    """Predict the pixel size without rasterising (used by --dry-run and tests)."""
    theme = load_theme(scene.theme)
    renderer = Renderer(scene, theme)
    rows, _, _ = renderer._rows()
    geo = renderer._geometry(rows)
    return {
        "width": geo["width"],
        "height": geo["height"],
        "columns": geo["columns"],
        "rows": geo["rows"],
        "cell_width": renderer.cw,
        "line_height": renderer.line_height,
    }


def visible_plain(scene: Scene) -> str:
    """Plain-text rendering of a scene (used by --text and for smoke tests)."""
    out: list[str] = []
    for line in scene.lines:
        if line.kind == "cmd" and scene.prompt:
            out.append(scene.prompt + " " + line.text)
        else:
            out.append(line.text if line.kind != "blank" else "")
    return "\n".join(out)
