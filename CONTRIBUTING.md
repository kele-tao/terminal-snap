# Contributing

Thanks for taking the time to contribute. This is a small, dependency-light tool and
the bar for a change is: **it must be testable offline and it must not fake output.**

## Development setup

```bash
git clone https://github.com/kele-tao/terminal-snap
cd terminal-snap
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
```

Run the benchmarks if you touched the parser or the renderer:

```bash
python benchmarks/run.py --quick
```

Regenerate the gallery and the README screenshot after any rendering change:

```bash
python -m terminal_snap gallery examples --out docs/gallery --html docs/gallery.html
```

## Code layout

| Path | Responsibility |
| --- | --- |
| `src/terminal_snap/ansi.py` | ANSI/SGR parsing into immutable `Span`/`Style` runs, CR/BS/TAB handling, wcwidth. |
| `src/terminal_snap/yaml_lite.py` | The block-YAML subset parser plus a `path -> line` table. |
| `src/terminal_snap/scene.py` | Scene dataclasses, validation, colour parsing, wrapping. |
| `src/terminal_snap/themes.py` | Theme loading, colour resolution, WCAG contrast checks. |
| `src/terminal_snap/fonts.py` | Monospace font discovery, loading, glyph fallback lookup. |
| `src/terminal_snap/renderer.py` | The Pillow renderer and `measure()`. |
| `src/terminal_snap/exporters.py` | SVG and self-contained HTML output. |
| `src/terminal_snap/record.py` | Command capture into a scene file. |
| `src/terminal_snap/gallery.py` | The gallery HTML page. |
| `src/terminal_snap/cli.py` | Argument parsing, exit codes, human output. |
| `benchmarks/run.py` | The only source of the numbers in README.md. |

## Rules

1. **Nothing fake.** If a README table or screenshot quotes a number, a command must
   reproduce it. If a feature does not work, delete it and note it in `docs/ROADMAP.md`.
2. **Tests are behaviour, not internals.** Use `tmp_path`, `capsys` and real files. No
   network, no sleeps over 0.1 s, no mocking of terminal-snap modules.
3. **Determinism.** Two renders of the same scene must produce identical bytes. Do not
   add timestamps, randomness or locale-dependent formatting to the render path.
4. **Errors are sentences.** A user mistake must produce one clear line and exit code
   2, never a traceback. Add the case to `tests/test_cli.py`.
5. **Keep the dependency count at one.** Pillow is the only runtime dependency. Propose
   a new one only if you can show the stdlib cannot do the job.
6. **Type hints and ruff.** Public functions are typed; `ruff check .` must stay clean
   at line length 100.

## Pull request checklist

- [ ] `python -m pytest -q` passes (was 208 tests at v1.0.0; do not lower it).
- [ ] `python -m ruff check .` is clean.
- [ ] New user-facing behaviour is documented in README.md and CHANGELOG.md.
- [ ] New errors have a test that asserts the message and the exit code.
- [ ] Rendering changes regenerate `docs/gallery/*.png` and `docs/screenshot.png`.
- [ ] No unfinished-task markers, no commented-out code, no debug prints.

## Commit messages

```
<area>: <imperative summary>

Optional body explaining the why, not the what.
```

Areas: `ansi`, `scene`, `renderer`, `fonts`, `themes`, `cli`, `record`, `docs`, `bench`, `ci`.
