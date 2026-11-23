"""Tests for theme loading, colour resolution and contrast checks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from terminal_snap.ansi import ColorRef, Style
from terminal_snap.errors import ThemeError
from terminal_snap.themes import (
    PALETTE_NAMES,
    builtin_names,
    check_contrast,
    contrast_ratio,
    load_theme,
    mix,
    palette_report,
    parse_hex,
    theme_from_dict,
)

THEMES = builtin_names()


def test_at_least_eight_themes_ship() -> None:
    assert len(THEMES) >= 8
    for expected in ("dracula", "nord", "gruvbox", "github-dark", "solarized-dark"):
        assert expected in THEMES


@pytest.mark.parametrize("name", THEMES)
def test_every_builtin_theme_loads(name: str) -> None:
    theme = load_theme(name)
    assert theme.name == name
    assert len(theme.palette) == 16
    assert all(0 <= c <= 255 for colour in theme.palette for c in colour)


@pytest.mark.parametrize("name", THEMES)
def test_builtin_themes_have_readable_text(name: str) -> None:
    theme = load_theme(name)
    assert contrast_ratio(theme.foreground, theme.background) >= 4.5


def test_theme_name_is_case_and_space_insensitive() -> None:
    assert load_theme("GitHub Dark").name == "github-dark"
    assert load_theme("SOLARIZED-LIGHT").name == "solarized-light"


def test_unknown_theme_lists_alternatives() -> None:
    with pytest.raises(ThemeError) as info:
        load_theme("solarized-purple")
    assert "built-in themes" in str(info.value)


def test_custom_theme_file(tmp_path: Path) -> None:
    base = json.loads((Path("src/terminal_snap/themes/nord.json")).read_text(encoding="utf-8"))
    base["name"] = "custom"
    base["background"] = "#101010"
    path = tmp_path / "custom.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    theme = load_theme(str(path))
    assert theme.name == "custom"
    assert theme.background == (16, 16, 16)


def test_broken_theme_json_reports_position(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{oops}", encoding="utf-8")
    with pytest.raises(ThemeError) as info:
        load_theme(str(path))
    assert "line 1" in str(info.value)


def test_theme_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "half.json"
    path.write_text('{"background": "#000000"}', encoding="utf-8")
    with pytest.raises(ThemeError) as info:
        load_theme(str(path))
    assert "missing required field" in str(info.value)


def test_palette_must_have_sixteen_colours() -> None:
    with pytest.raises(ThemeError) as info:
        theme_from_dict({"background": "#000000", "foreground": "#ffffff", "palette": ["#000"]})
    assert "at least 16" in str(info.value)


def test_parse_hex_forms() -> None:
    assert parse_hex("#fff") == (255, 255, 255)
    assert parse_hex("#102030") == (16, 32, 48)


def test_parse_hex_rejects_garbage() -> None:
    with pytest.raises(ThemeError):
        parse_hex("blue")


def test_foreground_resolution_uses_palette() -> None:
    theme = load_theme("nord")
    assert theme.fg(ColorRef("index", 1)) == theme.palette[1]
    assert theme.fg(None) == theme.foreground


def test_256_colour_resolution() -> None:
    theme = load_theme("nord")
    assert theme.fg(ColorRef("index", 208)) == (255, 135, 0)


def test_truecolor_resolution() -> None:
    theme = load_theme("nord")
    assert theme.fg(ColorRef("rgb", rgb=(1, 2, 3))) == (1, 2, 3)


def test_reverse_swaps_colours() -> None:
    theme = load_theme("nord")
    fg, bg = theme.resolve(Style(fg=ColorRef("index", 1), bg=ColorRef("index", 2), reverse=True))
    assert fg == theme.palette[2]
    assert bg == theme.palette[1]


def test_dim_lightens_toward_background() -> None:
    theme = load_theme("dracula")
    plain, _ = theme.resolve(Style(fg=None))
    dim, _ = theme.resolve(Style(fg=None, dim=True))
    assert dim != plain
    assert contrast_ratio(dim, theme.background) < contrast_ratio(plain, theme.background)


def test_hidden_uses_background() -> None:
    theme = load_theme("dracula")
    fg, _ = theme.resolve(Style(fg=None, hidden=True))
    assert fg == theme.background


def test_palette_report_has_named_rows() -> None:
    rows = list(palette_report(load_theme("gruvbox")))
    assert len(rows) == 16
    assert [name for name, _ in rows] == list(PALETTE_NAMES)
    assert rows[0][1].startswith("#")


def test_contrast_check_is_quiet_for_builtins() -> None:
    for name in THEMES:
        assert check_contrast(load_theme(name)) == []


def test_contrast_check_flags_low_contrast() -> None:
    data = json.loads((Path("src/terminal_snap/themes/nord.json")).read_text(encoding="utf-8"))
    data["foreground"] = "#2e3440"
    theme = theme_from_dict(data)
    warnings = check_contrast(theme)
    assert warnings and "WCAG" in warnings[0]


def test_mix_endpoints() -> None:
    assert mix((0, 0, 0), (255, 255, 255), 0.0) == (0, 0, 0)
    assert mix((0, 0, 0), (255, 255, 255), 1.0) == (255, 255, 255)
    assert mix((0, 0, 0), (200, 200, 200), 0.5) == (100, 100, 100)
