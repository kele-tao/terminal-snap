"""SVG and HTML export, so the same scene can ship as vector art or a web page.

The SVG exporter walks the same layout code as the PNG renderer but emits <text>
and <rect> elements, which stay sharp at any zoom and are editable in Figma. The
HTML exporter embeds the PNG as a base64 data URI, so one file works offline.
"""
from __future__ import annotations

import base64
import html
from pathlib import Path

from .ansi import Span, Style, cell_width
from .scene import Scene, wrap_spans
from .themes import Theme, load_theme


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _xml(text: str) -> str:
    return html.escape(text, quote=False)


def _layout(scene: Scene) -> tuple[list[list[Span]], list[int | None]]:
    rows: list[list[Span]] = []
    numbers: list[int | None] = []
    for index, line in enumerate(scene.lines):
        spans = list(line.spans)
        if line.kind == "cmd" and scene.prompt:
            spans = [Span(scene.prompt + " ", Style(bold=True))] + spans
        if not spans:
            rows.append([])
            numbers.append(index + 1)
            continue
        if scene.wrap:
            pieces = wrap_spans(spans, scene.width)
            for piece_index, piece in enumerate(pieces):
                rows.append(list(piece))
                numbers.append(index + 1 if piece_index == 0 else None)
        else:
            rows.append(spans)
            numbers.append(index + 1)
    return rows or [[]], numbers or [1]


def scene_to_svg(scene: Scene, theme: Theme | None = None) -> str:
    """Serialise a scene as a standalone SVG document."""
    theme = theme or load_theme(scene.theme)
    rows, numbers = _layout(scene)
    font_size = scene.font_size
    # Monospace advance width is ~0.6em for the faces we ship with.
    cw = round(font_size * 0.6, 2)
    line_height = round(font_size * 1.62, 2)
    columns = max(
        [scene.width] + [sum(cell_width(ch) for span in row for ch in span.text) for row in rows]
    )
    gutter = (len(str(max(1, len(rows)))) + 2) if scene.line_numbers else 0
    pad = scene.padding
    chrome_h = round(font_size * 2.15) if scene.chrome != "plain" else 0
    caption_h = round(font_size * 1.95) if scene.caption else 0
    width = round((columns + gutter) * cw + pad * 2)
    height = round(chrome_h + caption_h + len(rows) * line_height + pad * 2)
    parts: list[str] = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="' + str(width) + '" height="'
        + str(height) + '" viewBox="0 0 ' + str(width) + " " + str(height)
        + '" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">'
    )
    parts.append('<rect width="100%" height="100%" fill="' + _hex(theme.canvas) + '"/>')
    parts.append(
        '<rect x="0.5" y="0.5" width="' + str(width - 1) + '" height="' + str(height - 1)
        + '" rx="7" fill="' + _hex(theme.background) + '" stroke="'
        + _hex(theme.chrome_border) + '"/>'
    )
    if chrome_h:
        parts.append(
            '<rect x="1" y="1" width="' + str(width - 2) + '" height="' + str(chrome_h - 1)
            + '" fill="' + _hex(theme.chrome_background) + '"/>'
        )
        if scene.chrome == "macos":
            cx = 13.0
            for colour in ((255, 95, 87), (254, 188, 46), (40, 200, 64)):
                parts.append(
                    '<circle cx="' + str(round(cx, 1)) + '" cy="' + str(round(chrome_h / 2, 1))
                    + '" r="4.6" fill="' + _hex(colour) + '"/>'
                )
                cx += 13.8
        parts.append(
            '<text x="' + str(round(width / 2, 1)) + '" y="' + str(round(chrome_h / 2 + 4, 1))
            + '" font-size="' + str(round(font_size * 0.86, 1)) + '" text-anchor="middle" fill="'
            + _hex(theme.chrome_foreground) + '">' + _xml(scene.title) + "</text>"
        )
    if caption_h:
        cy = height - caption_h / 2 + 4
        parts.append(
            '<text x="' + str(round(width / 2, 1)) + '" y="' + str(round(cy, 1))
            + '" font-size="' + str(round(font_size * 0.82, 1)) + '" text-anchor="middle" fill="'
            + _hex(theme.caption) + '">' + _xml(scene.caption or "") + "</text>"
        )
    top = chrome_h + pad
    for row_index, row in enumerate(rows):
        y = top + row_index * line_height
        baseline = round(y + font_size, 1)
        if gutter:
            label = numbers[row_index] if row_index < len(numbers) else None
            if label is not None:
                parts.append(
                    '<text x="' + str(pad) + '" y="' + str(baseline) + '" font-size="'
                    + str(round(font_size * 0.8, 1)) + '" fill="' + _hex(theme.line_number)
                    + '" xml:space="preserve">' + _xml(str(label).rjust(gutter - 2)) + "</text>"
                )
        col = gutter
        for span in row:
            fg, bg = theme.resolve(span.style)
            text = span.text
            if not text:
                continue
            if bg is not None:
                parts.append(
                    '<rect x="' + str(round(pad + col * cw, 2)) + '" y="' + str(round(y, 2))
                    + '" width="' + str(round(len(text) * cw, 2)) + '" height="'
                    + str(round(line_height, 2)) + '" fill="' + _hex(bg) + '"/>'
                )
            attrs = ' fill="' + _hex(fg) + '"'
            if span.style.bold:
                attrs += ' font-weight="700"'
            if span.style.italic:
                attrs += ' font-style="italic"'
            if span.style.underline:
                attrs += ' text-decoration="underline"'
            parts.append(
                '<text x="' + str(round(pad + col * cw, 2)) + '" y="' + str(baseline) + '"'
                + ' xml:space="preserve"' + attrs + ">" + _xml(text) + "</text>"
            )
            col += sum(cell_width(ch) for ch in text)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  html, body {{ margin: 0; padding: 0; background: {canvas}; }}
  .page {{ display: flex; flex-direction: column; align-items: center; gap: 18px;
           padding: 28px; }}
  img {{ max-width: 100%; height: auto; border-radius: 8px; }}
  p {{ margin: 0; color: {foreground}; font-size: 13px; line-height: 1.5;
       font-family: ui-monospace, Menlo, Consolas, monospace; }}
  p span {{ color: {accent}; }}
</style></head>
<body><div class="page">
  <img alt="{alt}" src="data:image/png;base64,{payload}">
  <p><span>terminal-snap</span> &middot; {theme}
     &middot; {columns}&times;{rows} cells &middot; {width}&times;{height}px</p>
</div></body></html>
"""


def scene_to_html(scene: Scene, png_bytes: bytes, meta: dict[str, object],
                  theme: Theme | None = None) -> str:
    """Wrap a rendered PNG in a self-contained HTML page (base64, no external files)."""
    theme = theme or load_theme(scene.theme)
    payload = base64.b64encode(png_bytes).decode("ascii")
    return HTML_TEMPLATE.format(
        title=html.escape(scene.title),
        alt=html.escape("terminal screenshot: " + scene.title),
        canvas=_hex(theme.canvas),
        foreground=_hex(theme.foreground),
        accent=_hex(theme.accent),
        theme=html.escape(theme.label),
        columns=meta.get("columns", scene.width),
        rows=meta.get("rows", len(scene.lines)),
        width=meta.get("width", 0),
        height=meta.get("height", 0),
        payload=payload,
    )


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 text, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
