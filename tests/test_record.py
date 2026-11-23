"""Tests for the record module: capture semantics and scene serialisation."""
from __future__ import annotations

import sys

import pytest

from terminal_snap.errors import UsageError
from terminal_snap.record import (
    Capture,
    _elide_middle,
    capture,
    plain_output,
    scene_from_capture,
    scene_to_yaml,
    split_command,
)


def python(code: str) -> str:
    """Build a command that runs a snippet with this interpreter."""
    return '"' + sys.executable + '" -c "' + code + '"'


def test_split_command_requires_text() -> None:
    with pytest.raises(UsageError):
        split_command("   ")


def test_split_command_keeps_quoted_arguments() -> None:
    parts = split_command('echo "two words" three')
    assert parts[0] == "echo"
    assert "two words" in parts[1] or "two words" in " ".join(parts[1:])


def test_capture_records_stdout() -> None:
    cap = capture(python("print('alpha'); print('beta')"))
    assert cap.exit_code == 0
    assert cap.lines == ["alpha", "beta"]
    assert cap.truncated is False


def test_capture_merges_stderr_in_order() -> None:
    code = "import sys; print('out1'); print('err1', file=sys.stderr); print('out2')"
    cap = capture(python(code))
    joined = "\n".join(cap.lines)
    assert "out1" in joined and "err1" in joined and "out2" in joined


def test_capture_keeps_ansi() -> None:
    cap = capture(python("print('\\x1b[31mred\\x1b[0m')"))
    assert any("\x1b[31m" in line for line in cap.lines), cap.lines


def test_capture_flattens_carriage_returns() -> None:
    cap = capture(python("print('10%\\r50%\\r100%', end='')"))
    assert cap.lines == ["100%"]


def test_capture_reports_exit_code() -> None:
    cap = capture(python("import sys; sys.exit(3)"))
    assert cap.exit_code == 3


def test_capture_missing_command() -> None:
    with pytest.raises(UsageError) as info:
        capture("definitely-not-a-real-binary-xyz")
    assert "command not found" in str(info.value)


def test_capture_timeout() -> None:
    with pytest.raises(UsageError) as info:
        capture(python("import time; time.sleep(5)"), timeout=0.2)
    assert "timed out" in str(info.value)


def test_capture_accepts_large_but_bounded_output() -> None:
    # 100 KB of output is under the 4 MB guard, so it must be captured normally.
    cap = capture(python("print('x' * 100000)"), timeout=30)
    assert len(cap.lines) == 1
    assert len(cap.lines[0]) == 100000


def test_elide_middle_keeps_head_and_tail() -> None:
    lines = [str(i) for i in range(100)]
    result = _elide_middle(lines, 9)
    assert len(result) == 9
    assert result[0] == "0"
    assert result[-1] == "99"
    assert "omitted" in result[4]


def test_elide_middle_small_limit() -> None:
    assert _elide_middle(["a", "b", "c"], 2) == ["b", "c"]


def test_capture_truncates_long_output() -> None:
    cap = capture(python("for i in range(50): print(i)"), max_lines=11)
    assert cap.truncated is True
    assert len(cap.lines) == 11
    assert cap.lines[0] == "0"
    assert "omitted" in cap.lines[5]
    assert cap.lines[-1] == "49"


def test_scene_from_capture_adds_prompt_line() -> None:
    cap = Capture("echo hi", 0, ["hi"], False, 5)
    scene = scene_from_capture(cap, title="t", theme="nord", width=70)
    assert scene.lines[0].kind == "cmd"
    assert scene.lines[1].kind == "out"
    assert scene.title == "t"


def test_scene_from_capture_can_omit_command() -> None:
    cap = Capture("echo hi", 0, ["hi"], False, 5)
    scene = scene_from_capture(cap, title="t", theme="nord", width=70, show_command=False)
    assert len(scene.lines) == 1
    assert scene.lines[0].kind == "out"


def test_scene_from_capture_empty_output() -> None:
    scene = scene_from_capture(Capture("true", 0, [], False, 1),
                               title="t", theme="nord", width=70)
    assert scene.lines[-1].kind == "notice"


def test_scene_to_yaml_roundtrips_through_parser() -> None:
    from terminal_snap.scene import parse_scene

    cap = Capture("echo hi", 0, ["hi", "\x1b[32mgreen\x1b[0m"], False, 5)
    scene = scene_from_capture(cap, title="t", theme="nord", width=70)
    text = scene_to_yaml(scene)
    assert text.startswith("# Captured by terminal-snap record")
    scene_again, problems = parse_scene(text)
    assert problems == []
    assert len(scene_again.lines) == len(scene.lines)


def test_plain_output_strips_ansi() -> None:
    cap = Capture("x", 0, ["\x1b[31mred\x1b[0m"], False, 1)
    assert plain_output(cap) == "red"
