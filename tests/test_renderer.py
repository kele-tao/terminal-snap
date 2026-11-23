"""Tests for the Pillow renderer, exporters and measure()."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from terminal_snap.errors import RenderError
from terminal_snap.exporters import scene_to_html, scene_to_svg
from terminal_snap.fonts import discover_fonts, find_font, load_font
from terminal_snap.renderer import (
    Renderer,
    caption_height,
    chrome_height,
    gutter_cells,
    measure,
    render_scene,
    visible_plain,
)
from terminal_snap.scene import parse_scene
from terminal_snap.themes import load_theme

SCENE = """title: render test
theme: dracula
width: 64
lines:
  - cmd: echo hi
  - out: "hi"
  - text: "a table"
    bold: true
  - text: "  ┌────┬────┐"
  - text: "  │ ok │ 1  │"
  - text: "  └────┴────┘"
  - notice: "dim notice line"
  - blank: true
  - out: "coloured"
    fg: "#ff79c6"
    bg: "#44475a"
"""


def scene():
    parsed, problems = parse_scene(SCENE)
    assert problems == []
    return parsed


def test_font_discovery_finds_a_monospace_face() -> None:
    fonts = discover_fonts()
    assert fonts, "no monospace font found on this machine"
    assert fonts[0].path is not None
    assert "mono" in fonts[0].family.lower() or "consol" in fonts[0].family.lower() \
        or "code" in fonts[0].family.lower() or "courier" in fonts[0].family.lower() \
        or "lucida" in fonts[0].family.lower() or "menlo" in fonts[0].family.lower() \
        or "dejavu" in fonts[0].family.lower() or "ubuntu" in fonts[0].family.lower()


def test_find_font_by_family() -> None:
    chosen = discover_fonts()[0]
    assert find_font(chosen.family).path == chosen.path


def test_unknown_font_raises_with_options() -> None:
    from terminal_snap.errors import FontError

    with pytest.raises(FontError) as info:
        find_font("No Such Font 9000")
    assert "not installed" in str(info.value)


def test_load_font_rejects_missing_file() -> None:
    from terminal_snap.errors import FontError

    with pytest.raises(FontError):
        load_font("C:/nope/missing.ttf", 16)


def test_render_writes_a_png(tmp_path: Path) -> None:
    out = tmp_path / "shot.png"
    result = render_scene(scene(), out)
    assert out.exists()
    assert out.stat().st_size > 8000
    with Image.open(out) as image:
        assert image.size == (result.width, result.height)
        assert image.mode == "RGB"


def test_render_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    render_scene(scene(), first)
    render_scene(scene(), second)
    assert first.read_bytes() == second.read_bytes()


def test_measure_matches_actual_render(tmp_path: Path) -> None:
    result = render_scene(scene(), tmp_path / "shot.png")
    predicted = measure(scene())
    assert predicted["width"] == result.width
    assert predicted["height"] == result.height


def test_scale_doubles_pixels() -> None:
    small = scene()
    small.scale = 1
    one = measure(small)
    small.scale = 2
    two = measure(small)
    assert abs(two["cell_width"] - one["cell_width"] * 2) <= 1


def test_chrome_heights() -> None:
    s = scene()
    assert chrome_height(s, 30) > 0
    s.chrome = "plain"
    assert chrome_height(s, 30) == 0
    s.caption = "hello"
    assert caption_height(s, 30) > 0


def test_gutter_math() -> None:
    s = scene()
    assert gutter_cells(s) == 0
    s.line_numbers = True
    assert gutter_cells(s) >= 3


def test_line_numbers_render_wider(tmp_path: Path) -> None:
    plain = scene()
    numbered = scene()
    numbered.line_numbers = True
    plain_result = render_scene(plain, tmp_path / "plain.png")
    numbered_result = render_scene(numbered, tmp_path / "numbered.png")
    assert numbered_result.width > plain_result.width


def test_wrapping_increases_rows() -> None:
    s = scene()
    s.width = 20
    s.lines = [__import__("terminal_snap.scene", fromlist=["SceneLine"]).SceneLine.from_raw(
        "word " * 20)]
    rows_before = measure(s)["rows"]
    s.wrap = False
    rows_after = measure(s)["rows"]
    assert rows_before > rows_after


def test_renderer_reports_wrapped_rows(tmp_path: Path) -> None:
    s = scene()
    s.width = 20
    s.lines = [__import__("terminal_snap.scene", fromlist=["SceneLine"]).SceneLine.from_raw(
        "x" * 120)]
    result = render_scene(s, tmp_path / "wrapped.png")
    assert result.wrapped_rows > 0


def test_theme_changes_pixels(tmp_path: Path) -> None:
    s = scene()
    nord = tmp_path / "nord.png"
    s.theme = "nord"
    render_scene(s, nord)
    s.theme = "dracula"
    dracula = tmp_path / "dracula.png"
    render_scene(s, dracula)
    assert nord.read_bytes() != dracula.read_bytes()


def test_render_without_shadow(tmp_path: Path) -> None:
    s = scene()
    s.shadow = False
    result = render_scene(s, tmp_path / "flat.png")
    assert result.width > 0


def test_render_cursor(tmp_path: Path) -> None:
    s = scene()
    s.cursor = True
    result = render_scene(s, tmp_path / "cursor.png")
    assert result.width > 0


def test_empty_scene_lines_render_one_row(tmp_path: Path) -> None:
    s = scene()
    s.lines = []
    result = render_scene(s, tmp_path / "empty.png")
    assert result.rows == 1


def test_render_error_when_path_is_a_directory(tmp_path: Path) -> None:
    with pytest.raises(RenderError):
        render_scene(scene(), tmp_path)


def test_visible_plain_prefixes_prompts() -> None:
    text = visible_plain(scene())
    assert text.splitlines()[0].startswith("❯ echo hi")


def test_svg_export_contains_text_and_is_valid_xml(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    svg = scene_to_svg(scene())
    assert svg.startswith("<svg")
    assert "#ff79c6" in svg.lower() or "#44475a" in svg.lower()
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    path = tmp_path / "scene.svg"
    path.write_text(svg, encoding="utf-8")
    assert path.stat().st_size > 1000


def test_svg_escapes_markup() -> None:
    s = scene()
    s.lines.append(__import__("terminal_snap.scene", fromlist=["SceneLine"]).SceneLine.from_raw(
        "a < b & c > d"))
    svg = scene_to_svg(s)
    assert "&lt;" in svg and "&amp;" in svg
    assert "< b" not in svg


def test_html_export_embeds_png(tmp_path: Path) -> None:
    out = tmp_path / "shot.png"
    result = render_scene(scene(), out)
    page = scene_to_html(scene(), out.read_bytes(),
                         {"width": result.width, "height": result.height,
                          "columns": result.columns, "rows": result.rows})
    assert "data:image/png;base64," in page
    assert page.lstrip().startswith("<!doctype html>")
    assert str(result.width) in page


def test_fallback_glyph_is_reported(tmp_path: Path) -> None:
    from terminal_snap.fonts import fallback_font_path

    primary = discover_fonts()[0]
    if fallback_font_path("中", 30) is None:
        pytest.skip("no CJK-capable font installed on this machine")
    s = scene()
    s.font = primary.family
    s.lines = [
        __import__("terminal_snap.scene", fromlist=["SceneLine"]).SceneLine.from_raw("cjk 中文")
    ]
    result = render_scene(s, tmp_path / "cjk.png")
    assert result.fallback_glyphs, "expected CJK glyphs to need a fallback font"
    assert result.missing_glyphs == ()


def test_renderer_font_advance_is_positive() -> None:
    s = scene()
    renderer = Renderer(s, load_theme(s.theme))
    assert renderer.cw > 0
    assert renderer.line_height > renderer.font_size


def test_theme_parameter_overrides_scene_theme(tmp_path: Path) -> None:
    s = scene()
    s.theme = "nord"
    grub = load_theme("gruvbox")
    result = render_scene(s, tmp_path / "override.png", grub)
    assert result.theme.name == "gruvbox"
