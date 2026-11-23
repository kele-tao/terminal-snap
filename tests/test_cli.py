"""End-to-end CLI tests: exit codes, error messages, and every documented flag."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from terminal_snap.cli import build_parser, main


def run(argv: list[str]) -> tuple[int, str]:
    """Run main() and capture stdout."""
    code = main(argv)
    return code, ""


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "render" in out and "validate" in out and "themes" in out


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert "terminal-snap 1.0.0" in capsys.readouterr().out


def test_parser_exposes_all_commands() -> None:
    parser = build_parser()
    actions = [a for a in parser._actions if a.dest == "command"]
    choices = sorted(actions[0].choices)  # type: ignore[attr-defined]
    assert choices == ["fonts", "gallery", "init", "record", "render", "themes", "validate"]


def test_render_writes_png(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("theme: nord\nlines:\n  - cmd: hi\n  - out: there\n", encoding="utf-8")
    out = tmp_path / "out.png"
    assert main(["render", str(scene), "--out", str(out)]) == 0
    assert out.exists()
    assert "rendered" in capsys.readouterr().out


def test_render_default_output_path(tmp_path: Path) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("lines:\n  - text: hi\n", encoding="utf-8")
    assert main(["render", str(scene)]) == 0
    assert (tmp_path / "scene.png").exists()


def test_render_json_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("theme: nord\nlines:\n  - text: hi\n", encoding="utf-8")
    out = tmp_path / "out.png"
    assert main(["render", str(scene), "--out", str(out), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["width"] > 0
    assert payload["theme"] == "nord"
    assert payload["bytes"] == out.stat().st_size


def test_render_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("lines:\n  - text: hi\n", encoding="utf-8")
    out = tmp_path / "out.png"
    assert main(["render", str(scene), "--out", str(out), "--dry-run"]) == 0
    assert not out.exists()
    assert "cells wide" in capsys.readouterr().out


def test_render_svg_and_html(tmp_path: Path) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("lines:\n  - text: hi\n", encoding="utf-8")
    out = tmp_path / "out.png"
    svg = tmp_path / "out.svg"
    page = tmp_path / "out.html"
    assert main(["render", str(scene), "--out", str(out), "--svg", str(svg),
                 "--html", str(page)]) == 0
    assert svg.read_text(encoding="utf-8").startswith("<svg")
    assert "data:image/png;base64," in page.read_text(encoding="utf-8")


def test_render_theme_override(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("theme: nord\nlines:\n  - text: hi\n", encoding="utf-8")
    assert main(["render", str(scene), "--out", str(tmp_path / "o.png"),
                 "--theme", "gruvbox", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["theme"] == "gruvbox"


def test_render_scale_override(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("lines:\n  - text: hi\n", encoding="utf-8")
    main(["render", str(scene), "--out", str(tmp_path / "a.png"), "--scale", "1", "--json"])
    one = json.loads(capsys.readouterr().out)
    main(["render", str(scene), "--out", str(tmp_path / "b.png"), "--scale", "3", "--json"])
    three = json.loads(capsys.readouterr().out)
    assert three["width"] > one["width"]


def test_render_bad_scale_is_usage_error(tmp_path: Path) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("lines:\n  - text: hi\n", encoding="utf-8")
    assert main(["render", str(scene), "--out", str(tmp_path / "o.png"), "--scale", "99"]) == 2


def test_render_missing_scene_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["render", "nope.yaml", "--out", "x.png"]) == 2
    assert "not found" in capsys.readouterr().err


def test_render_bad_theme_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("lines:\n  - text: hi\n", encoding="utf-8")
    assert main(["render", str(scene), "--out", str(tmp_path / "o.png"),
                 "--theme", "nope"]) == 2
    assert "unknown theme" in capsys.readouterr().err


def test_render_invalid_scene_is_usage_error(tmp_path: Path,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("theme: nope\nlines:\n  - text: hi\n", encoding="utf-8")
    assert main(["render", str(scene), "--out", str(tmp_path / "o.png")]) == 2
    assert "invalid scene" in capsys.readouterr().err


def test_validate_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("theme: nord\nlines:\n  - text: hi\n", encoding="utf-8")
    assert main(["validate", str(scene)]) == 0
    assert "valid scene" in capsys.readouterr().out


def test_validate_reports_every_problem(tmp_path: Path,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("theme: nope\nwidth: 2\nlines:\n  - wibble: x\n", encoding="utf-8")
    assert main(["validate", str(scene)]) == 1
    out = capsys.readouterr()
    assert "unknown theme" in out.out
    assert "problem(s) found" in out.err


def test_validate_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scene = tmp_path / "scene.yaml"
    scene.write_text("theme: nope\nlines:\n  - text: hi\n", encoding="utf-8")
    assert main(["validate", str(scene), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"][0]["path"] == "theme"


def test_validate_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "nope.yaml"]) == 2
    assert "not found" in capsys.readouterr().err


def test_themes_lists_every_theme(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["themes"]) == 0
    out = capsys.readouterr().out
    assert "dracula" in out and "nord" in out


def test_themes_palette(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["themes", "--palette", "nord"]) == 0
    out = capsys.readouterr().out
    assert "bright-magenta" in out
    assert "#3b4252" in out


def test_themes_palette_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["themes", "--palette", "nord", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["theme"] == "nord"
    assert payload["palette"]["black"] == "#3b4252"


def test_themes_check_contrast(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["themes", "--check-contrast"]) == 0
    assert "ok" in capsys.readouterr().out


def test_themes_unknown_palette(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["themes", "--palette", "nope"]) == 2
    assert "unknown theme" in capsys.readouterr().err


def test_fonts_lists_fonts(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["fonts"]) == 0
    assert "default:" in capsys.readouterr().out


def test_fonts_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["fonts", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["default"]
    assert isinstance(payload["fonts"], list)


def test_record_captures_real_output(tmp_path: Path,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    code = (
        sys.executable + " -c \"print('captured line one'); print('captured line two')\""
    )
    out = tmp_path / "cap.yaml"
    assert main(["record", "--cmd", code, "--out", str(out), "--max-lines", "10"]) == 0
    text = out.read_text(encoding="utf-8")
    assert "captured line one" in text
    assert "cmd:" in text


def test_record_print_plain(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = sys.executable + " -c \"print('hello from record')\""
    out = tmp_path / "cap.yaml"
    assert main(["record", "--cmd", code, "--out", str(out), "--print"]) == 0
    captured = capsys.readouterr()
    assert "hello from record" in captured.out


def test_record_missing_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["record", "--cmd", "definitely-not-a-real-binary-xyz",
                 "--out", "x.yaml"]) == 2
    assert "not found" in capsys.readouterr().err


def test_record_empty_command_is_usage_error(tmp_path: Path,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["record", "--cmd", "   ", "--out", str(tmp_path / "x.yaml")]) == 2
    assert "--cmd must not be empty" in capsys.readouterr().err


def test_record_renders_when_asked(tmp_path: Path) -> None:
    code = sys.executable + " -c \"print('render me')\""
    out = tmp_path / "cap.yaml"
    png = tmp_path / "cap.png"
    assert main(["record", "--cmd", code, "--out", str(out), "--render", str(png)]) == 0
    assert png.exists() and png.stat().st_size > 4000


def test_init_writes_starter(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "hello.yaml"
    assert main(["init", str(target)]) == 0
    text = target.read_text(encoding="utf-8")
    assert "lines:" in text
    assert main(["init", str(target)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert main(["init", str(target), "--force"]) == 0


def test_gallery_renders_directory(tmp_path: Path) -> None:
    src = tmp_path / "scenes"
    src.mkdir()
    (src / "a.yaml").write_text("theme: nord\nlines:\n  - text: a\n", encoding="utf-8")
    (src / "b.yaml").write_text("theme: dracula\nlines:\n  - text: b\n", encoding="utf-8")
    out = tmp_path / "gallery"
    page = tmp_path / "gallery.html"
    assert main(["gallery", str(src), "--out", str(out), "--html", str(page)]) == 0
    assert (out / "a.png").exists()
    assert (out / "b.png").exists()
    assert "data:image/png;base64," in page.read_text(encoding="utf-8")


def test_gallery_empty_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "empty"
    src.mkdir()
    assert main(["gallery", str(src), "--out", str(tmp_path / "o")]) == 2
    assert "no scene files" in capsys.readouterr().err


def test_gallery_missing_directory(tmp_path: Path) -> None:
    assert main(["gallery", str(tmp_path / "nope"), "--out", str(tmp_path / "o")]) == 2


def test_module_entry_point_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "terminal_snap", "--version"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0
    assert "terminal-snap 1.0.0" in (proc.stdout + proc.stderr)


def test_examples_directory_validates() -> None:
    for path in sorted(Path("examples").glob("*.yaml")):
        assert main(["validate", str(path)]) == 0, path
