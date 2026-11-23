"""Tests for the ANSI SGR parser."""
from __future__ import annotations

import pytest

from terminal_snap.ansi import (
    EMPTY,
    Span,
    Style,
    cell_width,
    parse_ansi,
    strip_ansi,
    visible_length,
    xterm256_rgb,
)


def _styles(text: str) -> list[Style]:
    return [span.style for span in parse_ansi(text)]


def test_plain_text_has_no_style() -> None:
    spans = parse_ansi("hello world")
    assert len(spans) == 1
    assert spans[0].text == "hello world"
    assert spans[0].style == EMPTY


def test_bold_and_reset() -> None:
    spans = parse_ansi("\x1b[1mbold\x1b[0mplain")
    assert [s.text for s in spans] == ["bold", "plain"]
    assert spans[0].style.bold is True
    assert spans[1].style == EMPTY


@pytest.mark.parametrize(
    "code,attribute",
    [("2", "dim"), ("3", "italic"), ("4", "underline"), ("7", "reverse"), ("9", "strike")],
)
def test_attribute_codes(code: str, attribute: str) -> None:
    spans = parse_ansi("\x1b[" + code + "mx")
    assert getattr(spans[0].style, attribute) is True


def test_basic_colours_map_to_palette_indexes() -> None:
    spans = parse_ansi("\x1b[31mred\x1b[42mred-on-green")
    assert spans[0].style.fg is not None and spans[0].style.fg.index == 1
    assert spans[1].style.bg is not None and spans[1].style.bg.index == 2


def test_bright_colours() -> None:
    spans = parse_ansi("\x1b[91mx")
    assert spans[0].style.fg is not None and spans[0].style.fg.index == 9


def test_256_colour() -> None:
    spans = parse_ansi("\x1b[38;5;208morange\x1b[0m")
    fg = spans[0].style.fg
    assert fg is not None and fg.kind == "index" and fg.index == 208


def test_truecolor() -> None:
    spans = parse_ansi("\x1b[38;2;255;121;198mpink\x1b[0m")
    fg = spans[0].style.fg
    assert fg is not None and fg.kind == "rgb" and fg.rgb == (255, 121, 198)


def test_background_truecolor() -> None:
    spans = parse_ansi("\x1b[48;2;40;42;54mx")
    bg = spans[0].style.bg
    assert bg is not None and bg.rgb == (40, 42, 54)


def test_reset_codes_for_colour() -> None:
    spans = parse_ansi("\x1b[31ma\x1b[39mb")
    assert spans[1].style.fg is None


def test_bold_off() -> None:
    spans = parse_ansi("\x1b[1ma\x1b[22mb")
    assert spans[0].style.bold is True
    assert spans[1].style.bold is False


def test_xterm256_ramp() -> None:
    assert xterm256_rgb(16) == (0, 0, 0)
    assert xterm256_rgb(196) == (255, 0, 0)
    assert xterm256_rgb(231) == (255, 255, 255)
    assert xterm256_rgb(232) == (8, 8, 8)


def test_xterm256_rejects_system_colours() -> None:
    with pytest.raises(ValueError):
        xterm256_rgb(3)


def test_carriage_return_flattens_progress_bar() -> None:
    spans = parse_ansi("10%\r50%\r100% done")
    assert "".join(s.text for s in spans) == "100% done"


def test_backspace_overwrites() -> None:
    assert "".join(s.text for s in parse_ansi("ab\bc")) == "ac"


def test_tab_expands_to_stop() -> None:
    assert "".join(s.text for s in parse_ansi("a\tb")) == "a   b"


def test_unknown_escape_is_dropped_at_capture_layer() -> None:
    assert strip_ansi("\x1b[2K\x1b[1mhi\x1b[0m") == "hi"


def test_unicode_widths() -> None:
    assert visible_length(parse_ansi("abc")) == 3
    assert visible_length(parse_ansi("中文")) == 4
    assert visible_length(parse_ansi("e\u0301")) == 1


def test_cell_width_rules() -> None:
    assert cell_width("a") == 1
    assert cell_width("中") == 2
    assert cell_width("\u0301") == 0


def test_empty_string() -> None:
    assert parse_ansi("") == []


def test_span_text_roundtrip() -> None:
    spans = parse_ansi("a\x1b[32mb\x1b[0mc")
    assert "".join(span.text for span in spans) == "abc"
    assert isinstance(spans[0], Span)
