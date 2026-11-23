"""A deliberately failing test used to record a realistic pytest scene.

Nothing in the package imports this file. It exists so examples/pytest.yaml can be
captured from a real test run with 'terminal-snap record' instead of being typed by
hand - the failure in the screenshot is a genuine assertion failure.
"""
from __future__ import annotations

import pytest

from terminal_snap.ansi import parse_ansi
from terminal_snap.scene import wrap_spans


def test_parse_bold() -> None:
    spans = parse_ansi("\x1b[1mhi\x1b[0m")
    assert spans[0].text == "hi"
    assert spans[0].style.bold is True


def test_256_colour_is_stable() -> None:
    spans = parse_ansi("\x1b[38;5;208morange\x1b[0m")
    assert spans[0].style.fg is not None
    assert spans[0].style.fg.index == 208


def test_wrap_hard_break() -> None:
    """Wrong on purpose: 120 cells at width 40 make 3 rows, so this assertion fails."""
    row_count = len(wrap_spans(parse_ansi("x" * 120), 40))
    assert row_count == 4


@pytest.mark.parametrize("text", ["plain", "with spaces", "cjk text"])
def test_roundtrip_text(text: str) -> None:
    assert "".join(span.text for span in parse_ansi(text)) == text
