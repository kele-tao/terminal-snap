"""Tests for scene parsing and validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal_snap.ansi import parse_ansi
from terminal_snap.errors import SceneError, ThemeError
from terminal_snap.scene import (
    DEFAULTS,
    Scene,
    SceneLine,
    load_scene,
    parse_scene,
    scene_from_text,
    spans_to_ansi,
    wrap_spans,
)

GOOD = """title: demo
theme: nord
width: 72
chrome: windows
lines:
  - cmd: echo hello
  - out: hello
  - blank: true
  - text: "coloured"
    fg: green
    bold: true
    underline: true
"""


def test_valid_scene_has_no_problems() -> None:
    scene, problems = parse_scene(GOOD)
    assert problems == []
    assert scene.title == "demo"
    assert scene.theme == "nord"
    assert scene.chrome == "windows"
    assert len(scene.lines) == 4


def test_defaults_are_applied() -> None:
    scene, problems = parse_scene("lines:\n  - text: hi\n")
    assert problems == []
    assert scene.title == DEFAULTS["title"]
    assert scene.theme == DEFAULTS["theme"]
    assert scene.width == DEFAULTS["width"]


def test_line_styles_become_spans() -> None:
    scene, _ = parse_scene(GOOD)
    styled = scene.lines[3]
    assert styled.spans[0].style.bold is True
    assert styled.spans[0].style.underline is True
    assert styled.spans[0].style.fg is not None


def test_unknown_field_is_reported_with_line() -> None:
    scene, problems = parse_scene("theme: nord\ncolr: red\nlines:\n  - text: hi\n")
    assert len(problems) == 1
    assert problems[0].path == "colr"
    assert problems[0].line == 2
    assert "unknown field" in problems[0].message


def test_bad_theme_is_reported() -> None:
    scene, problems = parse_scene("theme: nope\nlines:\n  - text: hi\n")
    assert any("unknown theme" in p.message for p in problems)


def test_width_out_of_range() -> None:
    _, problems = parse_scene("width: 4\nlines:\n  - text: hi\n")
    assert any("between 20 and 400" in p.message for p in problems)


def test_width_must_be_integer() -> None:
    _, problems = parse_scene('width: "80"\nlines:\n  - text: hi\n')
    assert any("expected an integer" in p.message for p in problems)


def test_missing_lines_is_reported() -> None:
    _, problems = parse_scene("title: x\n")
    assert any(p.path == "lines" for p in problems)


def test_empty_scene_is_a_usage_error() -> None:
    with pytest.raises(SceneError) as info:
        parse_scene("")
    assert "empty" in str(info.value)


def test_top_level_must_be_a_mapping() -> None:
    with pytest.raises(SceneError) as info:
        parse_scene("- one\n- two\n")
    assert "mapping" in str(info.value)


def test_yaml_error_becomes_scene_error_with_line() -> None:
    with pytest.raises(SceneError) as info:
        parse_scene("a:\n  b: 1\n c: 2\n")
    assert "line" in str(info.value)


def test_json_scene_is_supported() -> None:
    text = '{"title": "json scene", "theme": "nord", "lines": [{"text": "hi"}]}'
    scene, problems = parse_scene(text)
    assert problems == []
    assert scene.title == "json scene"


def test_bad_json_has_line_and_column() -> None:
    with pytest.raises(SceneError) as info:
        parse_scene('{"title": "x",}')
    assert "invalid JSON" in str(info.value)


def test_unknown_line_kind_is_reported() -> None:
    _, problems = parse_scene("lines:\n  - wibble: hi\n")
    assert problems and "expected one of" in problems[0].message


def test_line_text_must_be_string() -> None:
    _, problems = parse_scene("lines:\n  - text: 42\n")
    assert problems and "expected a string" in problems[0].message


def test_blank_line_takes_no_text() -> None:
    _, problems = parse_scene("lines:\n  - blank: yes please\n")
    assert problems and "blank lines take no text" in problems[0].message


def test_bad_chrome_choice() -> None:
    _, problems = parse_scene("chrome: amiga\nlines:\n  - text: hi\n")
    assert problems and "macos, windows, plain" in problems[0].message


def test_colour_forms_are_normalised() -> None:
    text = (
        "lines:\n"
        "  - text: hex\n    fg: \"#ff79c6\"\n"
        "  - text: short\n    fg: \"#f0c\"\n"
        "  - text: name\n    fg: bright-cyan\n"
        "  - text: index\n    fg: 208\n"
        "  - text: rgb\n    bg: [1, 2, 3]\n"
    )
    scene, problems = parse_scene(text)
    assert problems == []
    fg_values = [line.spans[0].style.fg for line in scene.lines]
    assert fg_values[0].rgb == (255, 121, 198)
    assert fg_values[1].rgb == (255, 0, 204)
    assert fg_values[2].index == 14
    assert fg_values[3].index == 208
    assert scene.lines[4].spans[0].style.bg.rgb == (1, 2, 3)


def test_bad_colour_message() -> None:
    _, problems = parse_scene('lines:\n  - text: x\n    fg: "#12"\n')
    assert problems and "hex colour" in problems[0].message


def test_negative_delay_is_reported() -> None:
    _, problems = parse_scene("lines:\n  - out: x\n    delay: -1\n")
    assert problems and "delay" in problems[0].path


def test_problems_are_sorted_by_line() -> None:
    text = "colour: red\nwidth: 2\ntheme: nope\nlines:\n  - text: hi\n"
    _, problems = parse_scene(text)
    lines = [p.line for p in problems]
    assert lines == sorted(lines)


def test_prompt_prefix_is_only_for_cmd_lines() -> None:
    scene, _ = parse_scene('prompt: ">" \nlines:\n  - cmd: ls\n  - out: file\n')
    assert scene.lines[0].kind == "cmd"
    assert scene.lines[0].text == "ls"
    assert scene.prompt == ">"


def test_wrap_spans_hard_break() -> None:
    rows = wrap_spans(parse_ansi("x" * 120), 40)
    assert len(rows) == 3
    widths = [sum(len(span.text) for span in row) for row in rows]
    assert widths == [40, 40, 40]


def test_wrap_spans_merges_runs() -> None:
    rows = wrap_spans(parse_ansi("x" * 120), 40)
    assert all(len(row) == 1 for row in rows)


def test_wrap_spans_prefers_spaces() -> None:
    rows = wrap_spans(parse_ansi("hello world again"), 11)
    assert "".join(s.text for s in rows[0]) == "hello world"


def test_wrap_zero_width_returns_single_row() -> None:
    rows = wrap_spans(parse_ansi("abc"), 0)
    assert len(rows) == 1


def test_spans_to_ansi_roundtrip() -> None:
    original = "\x1b[1;32mok\x1b[0m plain \x1b[38;5;208morange\x1b[0m"
    spans = parse_ansi(original)
    again = parse_ansi(spans_to_ansi(spans))
    assert [s.text for s in again] == [s.text for s in spans]
    assert again[0].style.bold is True
    assert again[0].style.fg.index == 2
    assert again[-1].style.fg.index == 208


def test_scene_line_to_ansi_has_no_codes_when_plain() -> None:
    line = SceneLine.from_raw("plain text")
    assert line.to_ansi() == "plain text"


def test_load_scene_missing_file() -> None:
    with pytest.raises(SceneError) as info:
        load_scene(Path("does-not-exist.yaml"))
    assert "not found" in str(info.value)


def test_load_scene_reports_every_problem(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("theme: nope\nwidth: 3\nlines:\n  - wibble: x\n", encoding="utf-8")
    with pytest.raises(SceneError) as info:
        load_scene(bad)
    message = str(info.value)
    assert "unknown theme" in message
    assert "between 20 and 400" in message
    assert "expected one of" in message


def test_load_scene_good_file(tmp_path: Path) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(GOOD, encoding="utf-8")
    scene = load_scene(good)
    assert scene.source == str(good)


def test_scene_from_text_raises_on_problems() -> None:
    with pytest.raises(SceneError):
        scene_from_text("lines: []\n")


def test_scene_to_dict_roundtrips_through_parser() -> None:
    scene, _ = parse_scene(GOOD)
    from terminal_snap.yaml_lite import dump_yaml

    again, problems = parse_scene(dump_yaml(scene.to_dict()))
    assert problems == []
    assert [line.text for line in again.lines] == [line.text for line in scene.lines]


def test_scene_dataclass_defaults() -> None:
    scene = Scene()
    assert scene.width == 88
    assert scene.lines == []
    assert scene.chrome == "macos"


def test_theme_error_is_usage_error() -> None:
    from terminal_snap.errors import UsageError

    assert issubclass(ThemeError, UsageError)
