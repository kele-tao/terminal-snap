# Architecture

terminal-snap is a pipeline of six small modules. Each one has one job and can be
tested without the others, which is what keeps a 3,000-line image tool debuggable.

```mermaid
flowchart TD
    subgraph input
        A1[scene.yaml / scene.json]
        A2[command line]
        A3[theme JSON]
    end
    subgraph parse
        B1[yaml_lite.parse_yaml]
        B2[record.capture]
        C1[themes.load_theme]
    end
    subgraph model
        D1[scene.parse_scene]
        D2[Scene + SceneLine]
        E1[ansi.parse_ansi]
        E2[Span + Style]
    end
    subgraph render
        F1[scene.wrap_spans]
        F2[renderer.Renderer]
        F3[fonts.find_font / load_font]
        F4[themes.Theme.resolve]
    end
    subgraph output
        G1[PNG]
        G2[SVG]
        G3[HTML]
        G4[scene YAML]
    end
    A1 --> B1 --> D1
    A2 --> B2 --> D1
    A3 --> C1 --> F4
    D1 --> D2
    D2 --> E1 --> E2
    E2 --> F1 --> F2
    F3 --> F2
    F4 --> F2
    F2 --> G1
    D2 --> G2
    G1 --> G3
    B2 --> G4
```

## Data flow in detail

1. **`yaml_lite.parse_yaml`** returns a `Document` containing both the
   parsed tree and a `dict[(path), line_number]`. The line table is the only reason
   validation errors can say `lines[5].fg` instead of `key 'fg'`.
2. **`scene.parse_scene`** validates the tree against the schema and builds a
   `Scene`. It never raises on the first problem: it collects a `Problem` for
   each one, sorts them by line, and returns them all. The CLI decides the exit code.
3. **`ansi.parse_ansi`** turns one raw line into a tuple of `Span`s. Each
   `Span` is `(text, Style)` where `Style` holds colour references
   (`ColorRef(index)` or `ColorRef(rgb=...)`), not resolved RGB — resolution
   happens later, once the theme is known.
4. **`scene.wrap_spans`** wraps at a cell width, keeping styles intact across the
   break and preferring spaces over hard splits.
5. **`renderer.Renderer`** measures the font advance once, computes geometry, and
   draws each row as runs of same-styled text. Glyph lookups are cached per character.
6. **Exporters** re-use the same model: `scene_to_svg` re-runs the layout and emits
   `<text>` elements; `scene_to_html` inlines the PNG as base64.

## Why the model is split this way

The ANSI layer knows nothing about themes, and the theme layer knows nothing about
text layout. That separation is what lets `terminal-snap validate` check a scene
without loading any font or touching Pillow, and what lets the SVG exporter work on a
machine where the PNG fonts are missing.

## Determinism

Three things would normally break byte-identical output, and each is handled:

| Risk | Handling |
| --- | --- |
| Font rendering differences | The advance width is measured, not assumed; all positions are integer multiples of it. |
| Anti-aliasing jitter | Pillow's rasteriser is deterministic for a given font file and size. |
| Metadata in PNG | `Image.save(..., optimize=True)` with no `pnginfo`, so no timestamps are written. |

What is *not* guaranteed: the same scene on a different machine with a different font
installed will differ, because the font is part of the input. `terminal-snap fonts`
exists so you can see exactly which file was used.
