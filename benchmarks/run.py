"""Benchmark terminal-snap and write the numbers the README quotes.

This script is the only source of the performance table in README.md: run it, then
read benchmarks/results.md. Everything is measured on this machine with
time.perf_counter, repeating each case so the reported number is a median rather
than a lucky first run.

    python benchmarks/run.py             # full run, writes results.json + results.md
    python benchmarks/run.py --quick     # smaller inputs, same code paths
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from terminal_snap.ansi import parse_ansi  # noqa: E402
from terminal_snap.renderer import Renderer, render_scene  # noqa: E402
from terminal_snap.scene import load_scene, parse_scene  # noqa: E402
from terminal_snap.themes import load_theme  # noqa: E402
from terminal_snap.yaml_lite import parse_yaml  # noqa: E402

OUT_JSON = Path(__file__).resolve().parent / "results.json"
OUT_MD = Path(__file__).resolve().parent / "results.md"

COLOURS = ["\x1b[32m", "\x1b[31m", "\x1b[33m", "\x1b[36m", "\x1b[38;5;208m", "\x1b[0m"]


def timeit(fn, repeat: int = 5) -> float:
    """Median wall time in milliseconds for one call of fn."""
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 2)


def build_scene(lines: int, width: int = 100) -> str:
    """Synthesise a realistic log-ish scene file with the requested line count."""
    out = [
        "title: benchmark",
        "theme: dracula",
        "width: " + str(width),
        "chrome: macos",
        "line_numbers: true",
        "lines:",
    ]
    for i in range(lines):
        colour = COLOURS[i % (len(COLOURS) - 1)]
        out.append(
            '  - out: "' + colour + "module " + str(i % 17) + ": handled request "
            + str(i) + " in " + str(3 + i % 40) + "ms\x1b[0m\""
        )
    return "\n".join(out) + "\n"


def bench_parse(sizes: list[int]) -> list[dict]:
    rows = []
    for size in sizes:
        text = build_scene(size)
        rows.append({
            "case": "parse scene (" + str(size) + " lines)",
            "ms": timeit(lambda: parse_yaml(text)),
            "measured": "parse_yaml() on a synthetic scene",
        })
    return rows


def bench_ansi(megabytes: list[float]) -> list[dict]:
    rows = []
    line = "".join(COLOURS[i % len(COLOURS)] + "token" + str(i) + " " for i in range(20))
    line += "\n"
    for size in megabytes:
        count = max(1, int(size * 1024 * 1024 / len(line)))
        payload = line * count
        chunks = payload.splitlines()

        def run() -> None:
            for text in chunks:
                parse_ansi(text)

        rows.append({
            "case": "parse ANSI log (" + str(size) + " MB)",
            "ms": timeit(run, repeat=3),
            "measured": str(count) + " lines, " + str(round(len(payload) / 1e6, 1)) + " MB",
        })
    return rows


def bench_render(counts: list[int], scale: int) -> list[dict]:
    out = []
    for count in counts:
        scene, problems = parse_scene(build_scene(count))
        if problems:
            raise SystemExit("benchmark scene is invalid: " + str(problems[:2]))
        scene.scale = scale
        renderer = Renderer(scene, load_theme(scene.theme))
        geometry = renderer._geometry(renderer._rows()[0])
        out.append({
            "case": "rasterise " + str(count) + " rows @" + str(scale) + "x",
            "ms": timeit(lambda: renderer.render(), repeat=3),
            "px": str(geometry["width"]) + "x" + str(geometry["height"]),
            "measured": "Renderer.render() in memory",
        })
    return out


def bench_write(tmp: Path, counts: list[int]) -> list[dict]:
    out = []
    for count in counts:
        scene, _ = parse_scene(build_scene(count))
        target = tmp / ("bench_" + str(count) + ".png")
        ms = timeit(lambda: render_scene(scene, target), repeat=3)
        out.append({
            "case": "render + PNG encode " + str(count) + " rows",
            "ms": ms,
            "kb": round(target.stat().st_size / 1024, 1),
            "measured": "full render path including disk write",
        })
    return out


def bench_gallery(tmp: Path) -> dict:
    scenes = sorted((ROOT / "examples").glob("*.yaml"))
    parsed = [(load_scene(path), path.stem) for path in scenes]

    def run() -> None:
        for scene, stem in parsed:
            render_scene(scene, tmp / (stem + ".png"))

    return {
        "case": "render the bundled gallery (" + str(len(parsed)) + " scenes)",
        "ms": timeit(run, repeat=3),
        "measured": "load_scene() plus render_scene() for every examples/*.yaml",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark scene parsing and rendering.")
    parser.add_argument("--quick", action="store_true", help="smaller inputs")
    parser.add_argument("--json-only", action="store_true", help="skip the Markdown table")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="terminal-snap-bench-"))
    parse_sizes = [1000, 5000] if args.quick else [1000, 5000, 20000]
    ansi_sizes = [1.0, 3.0] if args.quick else [1.0, 3.0, 5.0]
    results: list[dict] = []
    results.extend(bench_parse(parse_sizes))
    results.extend(bench_ansi(ansi_sizes))
    results.extend(bench_render([40, 200], scale=2))
    results.extend(bench_render([40], scale=1))
    results.extend(bench_render([40], scale=3))
    results.extend(bench_write(tmp, [40, 200]))
    results.append(bench_gallery(tmp))

    payload = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "generated_by": "benchmarks/run.py",
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Benchmarks",
        "",
        "Generated by benchmarks/run.py on Python " + payload["python"],
        "(" + payload["platform"] + "). Times are the median of 3-5 runs; lower is better.",
        "",
        "| Case | Time | Notes |",
        "| --- | --- | --- |",
    ]
    for row in results:
        extra = ""
        if "kb" in row:
            extra = ", " + str(row["kb"]) + " KB PNG"
        if "px" in row:
            extra = ", " + row["px"] + " px"
        lines.append(
            "| " + row["case"] + " | " + str(row["ms"]) + " ms" + extra + " | "
            + row.get("measured", "") + " |"
        )
    lines.append("")
    lines.append("Rows are rasterised at 2x unless the case says otherwise, because 2x is the")
    lines.append("default and the slowest common path. Timings include font loading on the")
    lines.append("first call, which is why they are medians rather than minimums.")
    lines.append("")
    if not args.json_only:
        OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for row in results:
        print(row["case"].ljust(40) + str(row["ms"]).rjust(9) + " ms")
    print("")
    print("wrote " + str(OUT_JSON.relative_to(ROOT)))
    if not args.json_only:
        print("wrote " + str(OUT_MD.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
