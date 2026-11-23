# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x | yes |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Email the maintainer
at the address on the GitHub profile ([@kele-tao](https://github.com/kele-tao)) with:

- the terminal-snap version (`terminal-snap --version`),
- a minimal scene file or command line that reproduces the issue,
- what you expected versus what happened.

You can expect an acknowledgement within 72 hours and a coordinated disclosure
timeline once the report is triaged.

## Threat model

terminal-snap is a local CLI that turns a text file into a PNG. Its realistic attack
surface is small, but these are the areas we treat as security-relevant:

- **Scene files are untrusted input.** A scene can be very large, deeply indented, or
  malformed. The parser must fail with a message rather than hang, recurse without
  bound, or exhaust memory. `yaml_lite` is iterative (no recursion over nesting
  depth) and rejects anchors/tags rather than resolving them.
- **`record` executes a command.** That is its purpose; it runs exactly the argv you
  give it, without a shell, and it never elevates privileges. Do not point it at
  untrusted input. It captures at most 4 MB and times out after 120 s by default.
- **Theme files are JSON data.** Colours are validated as hex/RGB and converted to
  integers before use; no code is evaluated.
- **Output paths** are created with `mkdir(parents=True, exist_ok=True)` from the
  path you pass on the command line. There is no templating of output paths.

## What is not a vulnerability

- A command you ask `record` to run doing something harmful.
- Arbitrary filesystem writes to a path you explicitly passed to `--out`.
- Denial of service by rendering an absurdly large scene **you** wrote locally; there
  are documented caps (400 columns, 8x scale, 4 MB capture) but a 20,000-line scene is
  an intentional supported input.
