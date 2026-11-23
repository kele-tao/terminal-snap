# Roadmap

What v1.0 deliberately does not do, and why. Nothing here is a promise; it is the
honest boundary of the current release. Items marked **cut** were considered for 1.0
and removed rather than shipped half-working.

## Cut from v1.0

### Animated output (typing animations, animated SVG)

`record` stores a per-line `delay` field and the scene model accepts it, but
nothing consumes it: the renderer produces a single frame. Shipping an animation
format needs a decision about frame timing, file size and how a GIF/APNG of a
terminal is reviewed in a pull request, and a half-finished animation is worse than
none. `delay` is retained in the schema because it documents intent in a scene and
costs nothing.

### Font bundling and downloading

The renderer discovers fonts already installed on the machine. This means a scene
renders differently on Linux (DejaVu Sans Mono) than on macOS (Menlo) than on Windows
(Cascadia Mono). Bundling a font would fix that but adds a multi-megabyte binary to the
repository and a licence to track. The current answer is explicit: `terminal-snap fonts`
shows what was used, and the gallery documents that cross-platform pixel equality is
not claimed.

### Windows console colour detection beyond environment variables

Colour output honours `NO_COLOR`, `FORCE_COLOR` and `isatty()`. The legacy Windows
console (pre-Windows Terminal) needs `SetConsoleMode(ENABLE_VIRTUAL_TERMINAL_PROCESSING)`
to render ANSI at all; v1.0 does not call into Win32 for that. Modern Windows
Terminal, VS Code's terminal and every Unix terminal work already.

### Per-word styling inside a line

A line is one string with one style. You cannot write "the third word is red" without
splitting the line and using an escape sequence. Adding an inline markup syntax was
cut because ANSI escapes already express it, and every markup syntax we designed was
noisier than `\x1b[31m`.

## Next releases

### 1.1 — scene inheritance and variables

```yaml
extends: ../base.yaml
vars:
  version: 1.0.0
lines:
  - out: "installed terminal-snap {{ version }}"
```

Shared theme/padding/chrome blocks across a docs set, plus `{{ var }}` substitution
from the scene, the environment, or `--set key=value`. This is the single most
requested shape for a docs tool and it can be added without touching the renderer.

### 1.2 — perceptual image diff

`terminal-snap diff old.png new.png --threshold 0.02` using a cheap downscaled
comparison, so CI can fail when a scene change moves pixels. The hard part is not the
metric, it is calibrating the threshold so that re-rendering on a different OS does
not produce false failures — which is why it needs its own release.

### 1.3 — WebP and retina conventions

`--format webp` and an `@2x` filename convention so GitHub serves the sharp image on
HiDPI screens. Small, mechanical, and only worth doing once the scene format is stable.

### 1.4 — Ligature aware rendering

Today each character is drawn in its own grid cell, so programming ligatures
(`->`, `!=`, `=>`) appear as separate glyphs. Drawing them requires detecting
ligature runs, letting the font apply them, and keeping the grid honest for selection
boxes. Doable, but it changes the central measurement assumption of the renderer.

## Not planned

- **A web service or hosted image API.** The whole point is offline and committed.
- **A GUI editor.** Scenes are text; a text editor plus `--dry-run` is the workflow.
- **Terminal emulation.** We parse the ANSI that programs emit, not full VT100 state
  (no scrolling regions, no alternate screen buffer). For screenshots of finished
  output that is the right scope.
