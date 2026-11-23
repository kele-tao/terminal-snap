# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-23

First public release.

### Added

- **Scene format.** YAML or JSON scenes with `title`, `theme`, `width`, `chrome`,
  `padding`, `font`, `font_size`, `scale`, `prompt`, `caption`, `line_numbers`,
  `wrap`, `cursor`, `shadow`, and a list of `text` / `cmd` / `out` / `notice` /
  `blank` lines with per-line colour and attribute overrides.
- **Renderer.** Pillow-based fixed-grid renderer at 1x-8x with macOS, Windows and
  plain window chrome, caption bar, line-number gutter and a soft drop shadow.
- **ANSI support.** SGR parsing for 16-colour, 256-colour and truecolor codes plus
  bold, dim, italic, underline, reverse, strike and hidden; CR/BS/TAB normalisation
  so captured progress bars render correctly.
- **Glyph fallback.** Characters missing from the chosen monospace font are drawn
  from the first installed font that has them (CJK, symbol and emoji coverage).
- **`record`.** Capture a real command's combined stdout+stderr with ANSI preserved
  into a committable scene file; optional `--print`, `--render` and symmetric
  `--max-lines` elision.
- **`validate`.** Report every scene problem at once, each with its source line.
- **`themes` / `fonts`.** List the eight built-in themes, dump a theme's 16-colour
  palette with live swatches, run WCAG contrast checks, and list detected monospace
  fonts.
- **`gallery`.** Render every scene in a directory to PNG and build a self-contained
  HTML page (inline base64 images) for docs.
- **`init`.** Write a commented starter scene.
- **Exports.** Real SVG (`--svg`) and a self-contained HTML page (`--html`) alongside
  the PNG.
- **Library API.** `from terminal_snap import Scene, parse_ansi, render_scene` so CI
  jobs can render without shelling out.
- **Benchmarks.** `benchmarks/run.py` produces `results.json` and `results.md`; the
  README performance table is generated from it.
- 190 pytest tests, ruff-clean, Python 3.10/3.11/3.12 CI.

### Known limitations

- No animated output (typing animation or animated SVG).
- YAML anchors, tags and multi-document streams are rejected, not supported.
- Chrome title and caption text use a smaller font than the body; both snap to the
  body grid.
