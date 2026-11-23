"""Build the gallery HTML page that the README screenshot is taken from.

Each card embeds a real rendered PNG as a base64 data URI plus the scene's own
metadata, so docs/gallery.html is a single offline file with no external requests.
"""
from __future__ import annotations

import base64
import html
from collections.abc import Iterable, Sequence
from pathlib import Path

from .themes import load_theme

CARD = """
  <figure class="card">
    <img alt="{alt}" src="data:image/png;base64,{payload}">
    <figcaption>
      <span class="scene">{scene}</span>
      <span class="meta">{width}&times;{height}px &middot; {bytes} KB &middot; {theme}
      &middot; {rows} rows</span>
    </figcaption>
  </figure>"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>terminal-snap gallery</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #0b0f17; color: #e6edf3;
         font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }}
  header {{ padding: 46px 40px 22px; max-width: 1180px; margin: 0 auto; }}
  h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: -0.02em; }}
  h1 code {{ color: #7ee787; font-family: ui-monospace, Menlo, Consolas, monospace; }}
  p.lede {{ margin: 0; color: #8b949e; max-width: 780px; }}
  .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 26px;
           padding: 20px 40px 56px; max-width: 1180px; margin: 0 auto; }}
  .card {{ margin: 0; background: #11161f; border: 1px solid #21262d; border-radius: 14px;
           padding: 14px; }}
  .card img {{ width: 100%; height: auto; display: block; border-radius: 8px; }}
  figcaption {{ display: flex; flex-direction: column; gap: 3px; padding: 12px 4px 2px; }}
  .scene {{ font: 600 13px ui-monospace, Menlo, Consolas, monospace; color: #58a6ff; }}
  .meta {{ font: 12px ui-monospace, Menlo, Consolas, monospace; color: #6e7681; }}
  footer {{ padding: 0 40px 46px; max-width: 1180px; margin: 0 auto;
            color: #6e7681; font-size: 13px; }}
  footer code {{ color: #7ee787; font-family: ui-monospace, Menlo, Consolas, monospace; }}
</style></head>
<body>
<header>
  <h1>terminal-snap <code>gallery</code></h1>
  <p class="lede">Six scenes, six real captures: pytest, a chained traceback, ANSI
  swatches, validation errors, theme palettes and font discovery. Every image below
  was rendered by <code style="color:#7ee787">terminal-snap gallery examples</code>
  with no browser and no external tool.</p>
</header>
<div class="grid">{cards}
</div>
<footer>Rendered with Pillow &middot; deterministic output &middot; sources in
<code>examples/</code></footer>
</body></html>
"""


def card_for(png_path: Path, scene_path: Path, theme: str, width: int, height: int,
             rows: int, title: str | None = None) -> str:
    """Build one gallery card for a rendered PNG."""
    payload = base64.b64encode(png_path.read_bytes()).decode("ascii")
    label = title or theme
    return CARD.format(
        alt=html.escape("terminal screenshot: " + scene_path.name),
        payload=payload,
        scene=html.escape("examples/" + scene_path.name),
        width=width,
        height=height,
        bytes=round(png_path.stat().st_size / 1024),
        theme=html.escape(load_theme(theme).label if theme else label),
        rows=rows,
    )


def build_gallery_html(cards: Sequence[str]) -> str:
    """Assemble the full gallery page from pre-rendered cards."""
    return PAGE.format(cards="".join(cards))


def write_html(path: Path, text: str) -> None:
    """Write UTF-8 HTML, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def card_iter(entries: Iterable[dict]) -> list[str]:
    """Build cards from the gallery command's result dictionaries."""
    out: list[str] = []
    for entry in entries:
        out.append(card_for(
            Path(str(entry["out"])),
            Path(str(entry["scene"])),
            str(entry["theme"]),
            int(entry["width"]),
            int(entry["height"]),
            int(entry.get("rows", 0)),
        ))
    return out
