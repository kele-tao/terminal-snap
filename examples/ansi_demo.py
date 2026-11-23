"""Print every ANSI feature the renderer supports, for the ansi.yaml example scene.

Run it with:  python examples/ansi_demo.py
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RESET = "\x1b[0m"


def swatch(label: str, codes: str, text: str) -> str:
    return codes + label.ljust(12) + text + RESET


def main() -> int:
    print(swatch("bold", "\x1b[1m", "build succeeded"))
    print(swatch("dim", "\x1b[2m", "cache hit, no work to do"))
    print(swatch("italic", "\x1b[3m", "italic comment"))
    print(swatch("underline", "\x1b[4m", "link to the docs"))
    print(swatch("reverse", "\x1b[7m", " selected row "))
    print(swatch("strike", "\x1b[9m", "deprecated flag"))
    print()
    print("16-colour:  " + "".join("\x1b[%dm %2d " % (30 + i, i) + RESET for i in range(8)))
    print("bright:     " + "".join("\x1b[%dm %2d " % (90 + i, i + 8) + RESET for i in range(8)))
    print()
    print("256-colour ramp:")
    ramp = "".join("\x1b[48;5;%dm  " % i + RESET for i in range(196, 232))
    print("  " + ramp)
    print()
    print("truecolor:")
    truecolor = "".join(
        "\x1b[48;2;%d;%d;%dm  " % (r, g, b) + RESET
        for r, g, b in ((0x28, 0x2A, 0x36), (0xFF, 0x79, 0xC6), (0x8B, 0xE9, 0xFD),
                        (0x50, 0xFA, 0x7B), (0xF1, 0xFA, 0x8C), (0xBD, 0x93, 0xF9))
    )
    print("  " + truecolor)
    print()
    print("\x1b[32m\u2713\x1b[0m 12 assertions passed   \x1b[31m\u2717\x1b[0m 1 failed"
          "   \x1b[33m\u25b2\x1b[0m 2 warnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
