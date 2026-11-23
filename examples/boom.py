"""A script that fails on purpose, to record a real (chained) traceback scene.

The frames, source lines and the "direct cause" chain are exactly what Python
produced. Only the working-directory prefix is stripped so the committed scene does
not leak a home directory and stays portable.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_theme(name: str) -> str:
    config = load_config(Path("scenes/missing.json"))
    return str(config["themes"][name])


def main() -> None:
    try:
        resolve_theme("dracula")
    except OSError as exc:
        raise RuntimeError("cannot start the renderer: theme config is unreadable") from exc


def render_relative_traceback(exc: BaseException) -> str:
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return text.replace(str(Path.cwd()) + os.sep, "")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - the demo wants every failure shape
        sys.stdout.write(render_relative_traceback(error))
        sys.exit(1)
