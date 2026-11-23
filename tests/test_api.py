"""Tests for the public library API and the error hierarchy.

The point of these tests is the contract a downstream CI job relies on: the names
exported from the package, their return types, and the exit codes the error classes
map to.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import terminal_snap
from terminal_snap import (
    Scene,
    SnapError,
    UsageError,
    load_scene,
    parse_ansi,
    render_scene,
    scene_from_text,
    scene_to_svg,
)


def test_version_is_semver() -> None:
    parts = terminal_snap.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_all_exports_are_importable() -> None:
    for name in terminal_snap.__all__:
        assert hasattr(terminal_snap, name), name


def test_error_exit_codes() -> None:
    assert SnapError("x").exit_code == 1
    assert UsageError("x").exit_code == 2
    assert issubclass(UsageError, SnapError)


def test_error_keeps_message() -> None:
    error = UsageError("scene file not found: x.yaml")
    assert error.message == "scene file not found: x.yaml"
    assert str(error) == "scene file not found: x.yaml"


def test_render_scene_library_call(tmp_path: Path) -> None:
    scene = scene_from_text("theme: nord\nlines:\n  - text: hi\n")
    out = tmp_path / "api.png"
    result = render_scene(scene, out)
    assert out.stat().st_size > 4000
    assert result.columns >= 20


def test_load_scene_and_svg_export(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text("lines:\n  - text: hello\n", encoding="utf-8")
    scene = load_scene(path)
    svg = scene_to_svg(scene)
    assert svg.startswith("<svg")
    assert ">hello</text>" in svg


def test_parse_ansi_library_call() -> None:
    spans = parse_ansi("\x1b[32mok\x1b[0m")
    assert spans[0].text == "ok"
    assert spans[0].style.fg is not None


def test_scene_defaults_are_documented(tmp_path: Path) -> None:
    scene = Scene()
    assert scene.chrome in ("macos", "windows", "plain")
    assert scene.scale == 2
    assert scene.wrap is True


def test_scene_error_is_raised_for_bad_text() -> None:
    from terminal_snap.errors import SceneError

    with pytest.raises(SceneError):
        scene_from_text("lines:\n  - wibble: x\n")
