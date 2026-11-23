"""Command line interface for terminal-snap.

Exit codes (documented in the README and enforced by tests):
  0  success
  1  the operation ran but a quality gate failed (e.g. validate found problems,
     render wrote nothing because --fail-on-warning triggered)
  2  usage error: bad flags, missing files, malformed scenes, unknown theme
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .colors import paint, safe_mark
from .errors import SnapError, UsageError
from .exporters import scene_to_html, scene_to_svg
from .fonts import discover_fonts, find_font
from .record import capture, plain_output, scene_from_capture, scene_to_yaml
from .renderer import measure, render_scene
from .scene import Scene, load_scene, parse_scene
from .themes import builtin_names, check_contrast, load_theme, palette_report

PROG = "terminal-snap"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (kept separate so tests can introspect it)."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Script terminal screenshots as YAML and render pixel-perfect PNGs.",
        epilog=(
            "examples:\n"
            "  terminal-snap render examples/install.yaml --out docs/install.png\n"
            "  terminal-snap record --cmd 'pytest -q' --out scenes/pytest.yaml\n"
            "  terminal-snap validate examples/install.yaml\n"
            "  terminal-snap themes --palette\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=PROG + " " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    render = sub.add_parser("render", help="render a scene to PNG (and optionally SVG/HTML)")
    render.add_argument("scene", help="scene file (.yaml, .yml or .json)")
    render.add_argument("--out", "-o", help="output PNG path (default: <scene>.png)")
    render.add_argument("--svg", help="also write a vector SVG of the same scene")
    render.add_argument("--html", help="also write a self-contained HTML page")
    render.add_argument("--theme", help="override the scene theme (name or .json path)")
    render.add_argument("--scale", type=int, help="device pixel ratio override (1-8)")
    render.add_argument("--font", help="override the font family (e.g. Consolas)")
    render.add_argument("--width", type=int, help="override the grid width in cells")
    render.add_argument("--dry-run", action="store_true", help="print the geometry, write nothing")
    render.add_argument("--json", action="store_true", help="print a JSON render report")
    render.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="exit 1 when the chosen font lacks glyphs for some characters",
    )

    record = sub.add_parser("record", help="capture a real command's output into a scene file")
    record.add_argument("--cmd", required=True, help="command to run (quoted)")
    record.add_argument("--out", "-o", required=True, help="scene file to write (.yaml)")
    record.add_argument("--title", default=None, help="window title (default: the command)")
    record.add_argument("--theme", default="dracula", help="theme name for the scene")
    record.add_argument("--width", type=int, default=88, help="grid width in cells")
    record.add_argument("--chrome", default="macos", choices=("macos", "windows", "plain"))
    record.add_argument("--max-lines", type=int, default=200, help="keep at most N lines of output")
    record.add_argument("--no-command-line", action="store_true", help="omit the prompt line")
    record.add_argument("--cwd", help="working directory for the command")
    record.add_argument("--render", help="also render the captured scene to this PNG")
    record.add_argument("--print", dest="print_plain", action="store_true",
                        help="print the captured output without ANSI to stdout")
    record.add_argument("--timeout", type=float, default=120.0, help="command timeout in seconds")

    validate = sub.add_parser("validate", help="check a scene file and report every problem")
    validate.add_argument("scene", help="scene file to validate")
    validate.add_argument("--json", action="store_true", help="machine-readable result")

    themes = sub.add_parser("themes", help="list built-in themes or show one palette")
    themes.add_argument("--palette", metavar="NAME", nargs="?", const="dracula",
                        help="print the 16 ANSI colours of a theme")
    themes.add_argument("--json", action="store_true", help="machine-readable output")
    themes.add_argument("--check-contrast", action="store_true",
                        help="report WCAG contrast warnings for every theme")

    fonts = sub.add_parser("fonts", help="list detected monospace fonts")
    fonts.add_argument("--json", action="store_true", help="machine-readable output")

    gallery = sub.add_parser("gallery", help="render every scene in a directory")
    gallery.add_argument("dir", help="directory containing scene files")
    gallery.add_argument("--out", "-o", required=True, help="output directory for PNGs")
    gallery.add_argument("--theme", help="override the theme for every scene")
    gallery.add_argument("--html", help="also write a self-contained gallery HTML page")
    gallery.add_argument("--json", action="store_true", help="machine-readable report")

    init = sub.add_parser("init", help="write a commented starter scene")
    init.add_argument("path", help="where to write the scene (e.g. scenes/hello.yaml)")
    init.add_argument("--theme", default="dracula", help="theme for the starter scene")
    init.add_argument("--force", action="store_true", help="overwrite an existing file")

    return parser


def _scene_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise UsageError("not a directory: " + str(directory))
    files = sorted(
        [p for p in directory.iterdir()
         if p.is_file() and p.suffix.lower() in (".yaml", ".yml", ".json")]
    )
    if not files:
        raise UsageError(
            "no scene files (*.yaml, *.yml, *.json) found in " + str(directory)
        )
    return files


def overload_scene(scene: Scene, args: argparse.Namespace) -> Scene:
    """Apply CLI overrides to a parsed scene."""
    if getattr(args, "theme", None):
        load_theme(args.theme)  # validates early, raises ThemeError
        scene.theme = args.theme
    if getattr(args, "scale", None):
        if args.scale < 1 or args.scale > 8:
            raise UsageError("--scale must be between 1 and 8")
        scene.scale = args.scale
    if getattr(args, "font", None):
        find_font(args.font)  # validates early, raises FontError
        scene.font = args.font
    if getattr(args, "width", None):
        if args.width < 20 or args.width > 400:
            raise UsageError("--width must be between 20 and 400 cells")
        scene.width = args.width
    return scene


def cmd_render(args: argparse.Namespace) -> int:
    scene = load_scene(Path(args.scene))
    scene = overload_scene(scene, args)
    out = Path(args.out) if args.out else Path(args.scene).with_suffix(".png")
    if args.dry_run:
        geometry = measure(scene)
        if args.json:
            print(json.dumps({"scene": str(args.scene), "geometry": geometry}, indent=2))
        else:
            print(str(args.scene) + ": " + str(geometry["columns"]) + " cells wide, "
                  + str(geometry["rows"]) + " rows -> "
                  + str(geometry["width"]) + "x" + str(geometry["height"]) + " px")
        return 0
    theme = load_theme(scene.theme)
    result = render_scene(scene, out, theme)
    if args.svg:
        from .exporters import write_text

        write_text(Path(args.svg), scene_to_svg(scene, theme))
    if args.html:
        from .exporters import write_text

        png = out.read_bytes()
        meta = {"width": result.width, "height": result.height,
                "columns": result.columns, "rows": result.rows}
        write_text(Path(args.html), scene_to_html(scene, png, meta, theme))
    if args.json:
        print(json.dumps({
            "scene": str(args.scene),
            "out": str(out),
            "width": result.width,
            "height": result.height,
            "columns": result.columns,
            "rows": result.rows,
            "bytes": out.stat().st_size,
            "theme": theme.name,
            "font": result.font.family,
            "wrapped_rows": result.wrapped_rows,
            "warnings": result.warnings,
        }, indent=2))
    else:
        print("rendered " + str(out) + "  " + str(result.width) + "x" + str(result.height)
              + " px  (" + str(out.stat().st_size // 1024) + " KB, theme "
              + theme.name + ", font " + result.font.family + ")")
        for warning in result.warnings:
            print("warning: " + warning, file=sys.stderr)
    if args.fail_on_warning and result.warnings:
        return 1
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd) if args.cwd else None
    if cwd is not None and not cwd.is_dir():
        raise UsageError("--cwd is not a directory: " + str(cwd))
    cap = capture(args.cmd, cwd=cwd, max_lines=args.max_lines, timeout=args.timeout)
    scene = scene_from_capture(
        cap,
        title=args.title or args.cmd,
        theme=args.theme,
        width=args.width,
        chrome=args.chrome,
        show_command=not args.no_command_line,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(scene_to_yaml(scene), encoding="utf-8")
    if args.print_plain:
        print(plain_output(cap))
    print(
        "recorded " + str(len(cap.lines)) + " lines from " + repr(args.cmd)
        + " (exit " + str(cap.exit_code) + ", " + str(cap.duration_ms) + " ms) -> " + str(out),
        file=sys.stderr,
    )
    if args.render:
        render_scene(scene, Path(args.render), load_theme(scene.theme))
        print("rendered " + str(args.render), file=sys.stderr)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.scene)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise UsageError("scene file not found: " + str(path)) from exc
    except OSError as exc:
        raise UsageError("cannot read scene file " + str(path) + ": " + str(exc)) from exc
    try:
        scene, problems = parse_scene(text, source=str(path))
    except SnapError as exc:
        if args.json:
            print(json.dumps({"ok": False, "scene": str(path),
                              "errors": [{"line": 0, "path": "", "message": exc.message}]},
                             indent=2))
            return 1
        raise
    if args.json:
        print(json.dumps({
            "ok": not problems,
            "scene": str(path),
            "lines": len(scene.lines),
            "theme": scene.theme,
            "errors": [{"line": p.line, "path": p.path, "message": p.message} for p in problems],
        }, indent=2))
    elif problems:
        for problem in problems:
            where = path.name + (":" + str(problem.line) if problem.line else "")
            print(paint("error", "red", "bold") + "  " + where + "  "
                  + paint(problem.path, "cyan") + ": " + problem.message)
    else:
        print(paint(safe_mark("✓", "OK") + " " + str(path), "green", "bold") + ": valid scene, "
              + str(len(scene.lines)) + " lines, theme " + scene.theme + ", "
              + str(scene.width) + " cells wide")
    if problems:
        print(str(len(problems)) + " problem(s) found", file=sys.stderr)
        return 1
    return 0


def cmd_themes(args: argparse.Namespace) -> int:
    names = builtin_names()
    if args.palette:
        theme = load_theme(args.palette)
        rows = list(palette_report(theme))
        if args.json:
            print(json.dumps({"theme": theme.name, "label": theme.label,
                              "background": "#%02x%02x%02x" % theme.background,
                              "palette": dict(rows)}, indent=2))
        else:
            print(theme.label + " (" + theme.name + ")")
            for label, hex_value in rows:
                rgb = tuple(int(hex_value[i : i + 2], 16) for i in (1, 3, 5))
                swatch = "[48;2;%d;%d;%dm      [0m" % rgb
                print("  " + label.ljust(15) + swatch + "  " + hex_value)
        return 0
    if args.check_contrast:
        failures = 0
        for name in names:
            theme = load_theme(name)
            warnings = check_contrast(theme)
            failures += len(warnings)
            status = "ok" if not warnings else str(len(warnings)) + " warning(s)"
            print(name.ljust(18) + status)
            for warning in warnings:
                print("  " + warning)
        return 0 if failures == 0 else 1
    if args.json:
        payload = []
        for name in names:
            theme = load_theme(name)
            payload.append({
                "name": theme.name,
                "label": theme.label,
                "background": "#%02x%02x%02x" % theme.background,
                "foreground": "#%02x%02x%02x" % theme.foreground,
                "accent": "#%02x%02x%02x" % theme.accent,
            })
        print(json.dumps(payload, indent=2))
        return 0
    print(str(len(names)) + " built-in themes:")
    for name in names:
        theme = load_theme(name)
        print("  " + name.ljust(18) + theme.label.ljust(20) + "#%02x%02x%02x" % theme.background)
    return 0


def cmd_fonts(args: argparse.Namespace) -> int:
    fonts = discover_fonts()
    chosen = find_font(None)
    if args.json:
        print(json.dumps({
            "default": chosen.family,
            "fonts": [{"family": f.family, "path": f.path} for f in fonts],
        }, indent=2))
        return 0
    if not fonts:
        print("no monospace TrueType font found; Pillow's bitmap default will be used")
        return 1
    print("default: " + chosen.describe())
    for spec in fonts:
        marker = "*" if spec == chosen else " "
        print(" " + marker + " " + spec.family.ljust(20) + str(spec.path))
    return 0


def cmd_gallery(args: argparse.Namespace) -> int:
    files = _scene_files(Path(args.dir))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    failures = 0
    for path in files:
        try:
            scene = load_scene(path)
        except SnapError as exc:
            print(str(exc), file=sys.stderr)
            failures += 1
            continue
        if args.theme:
            load_theme(args.theme)
            scene.theme = args.theme
        target = out_dir / (path.stem + ".png")
        result = render_scene(scene, target)
        results.append({
            "scene": str(path),
            "out": str(target),
            "width": result.width,
            "height": result.height,
            "rows": result.rows,
            "bytes": target.stat().st_size,
            "theme": scene.theme,
        })
        print(str(target) + "  " + str(result.width) + "x" + str(result.height)
              + "  " + str(target.stat().st_size // 1024) + " KB")
    if args.html:
        from .gallery import build_gallery_html, card_iter, write_html

        page = build_gallery_html(card_iter(results))
        write_html(Path(args.html), page)
        print("wrote " + str(args.html) + "  (" + str(len(results)) + " cards)")
    if args.json:
        print(json.dumps(results, indent=2))
    if failures:
        return 1
    return 0 if results else 1


STARTER = """# A terminal-snap scene. Everything here is data; no HTML, no browser.
title: {title}
theme: {theme}
width: 84
chrome: macos
prompt: "\u276f"
caption: generated with terminal-snap

lines:
  - cmd: python -m terminal_snap validate scenes/hello.yaml
  - out: ""
  - notice: "This file renders to a PNG with:"
  - cmd: python -m terminal_snap render scenes/hello.yaml --out hello.png
  - out: "rendered hello.png  1024x412 px  (72 KB, theme {theme}, font ...)"
{extra}"""


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if path.exists() and not args.force:
        raise UsageError("refusing to overwrite " + str(path) + " (pass --force)")
    load_theme(args.theme)
    body = STARTER.format(title="hello", theme=args.theme, extra="")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    print("wrote starter scene " + str(path))
    print("next: " + PROG + " render " + str(path) + " --out " + str(path.with_suffix(".png")))
    return 0


HANDLERS = {
    "render": cmd_render,
    "record": cmd_record,
    "validate": cmd_validate,
    "themes": cmd_themes,
    "fonts": cmd_fonts,
    "gallery": cmd_gallery,
    "init": cmd_init,
}


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; returns a process exit code (never raises for user errors)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    handler = HANDLERS[args.command]
    try:
        return handler(args)
    except SnapError as exc:
        print("error: " + exc.message, file=sys.stderr)
        return exc.exit_code
    except BrokenPipeError:  # pragma: no cover - shell piping edge case
        return 0
    except KeyboardInterrupt:  # pragma: no cover - interactive cancel
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
