"""A small, dependency-free YAML subset parser with line numbers.

terminal-snap scenes are meant to be readable YAML, but the package should not drag
PyYAML into every install just for that. This parser implements the block-style
subset that scene files actually need:

* mappings, sequences (nested, any depth), and sequences of mappings
* plain scalars with YAML 1.2 core-schema typing (null, bool, int, float, str)
* single- and double-quoted strings with escapes
* literal and folded block scalars: |, |-, |+, >, >-, >+
* flow collections on one line: [a, b, 3] and {k: v}
* comments, blank lines, and a leading document marker

It also returns a path -> line-number table so the scene validator can say
"scene.yaml line 17: theme must be a string" instead of a Python traceback.
Anchors, aliases, tags and multi-document streams are rejected explicitly rather
than silently mis-parsed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class YamlError(ValueError):
    """A malformed YAML document. Carries a 1-based line number."""

    def __init__(self, message: str, line: int) -> None:
        super().__init__("line " + str(line) + ": " + message)
        self.message = message
        self.line = line


@dataclass
class Document:
    """Parsed data plus a lookup from tuple-path to source line."""

    data: Any
    lines: dict[tuple[Any, ...], int] = field(default_factory=dict)

    def line_of(self, path: tuple[Any, ...]) -> int:
        """Return the most specific known source line for a path (0 if unknown)."""
        probe = path
        while probe:
            if probe in self.lines:
                return self.lines[probe]
            probe = probe[:-1]
        return self.lines.get((), 0)


@dataclass
class _Line:
    number: int
    indent: int
    text: str


_INT_RE = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")
_FLOAT_RE = re.compile(r"^[-+]?([0-9]+\.[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?$")
_HEX4_RE = re.compile(r"[0-9A-Fa-f]{4}")
_HEX2_RE = re.compile(r"[0-9A-Fa-f]{2}")


def _strip_comment(text: str) -> str:
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return text[:i].rstrip()
        i += 1
    return text.rstrip()


def _split_lines(source: str) -> list[_Line]:
    out: list[_Line] = []
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    for idx, raw in enumerate(text.split("\n"), 1):
        leading = raw[: len(raw) - len(raw.lstrip(" \t"))]
        if "\t" in leading:
            raise YamlError("tabs are not allowed for indentation; use spaces", idx)
        stripped = _strip_comment(raw)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        out.append(_Line(idx, indent, stripped[indent:]))
    return out


def _parse_scalar(token: str, line: int) -> Any:
    token = token.strip()
    if token == "":
        return None
    if token[0] == '"':
        return _parse_double_quoted(token, line)
    if token[0] == "'":
        return _parse_single_quoted(token, line)
    low = token.lower()
    if low in ("null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if _INT_RE.match(token):
        return int(token)
    if _FLOAT_RE.match(token):
        return float(token)
    return token


_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\x00",
    '"': '"',
    "\\": "\\",
    "/": "/",
    "e": "\x1b",
    "b": "\b",
    "f": "\f",
}


def _parse_double_quoted(token: str, line: int) -> str:
    if len(token) < 2 or token[-1] != '"':
        raise YamlError("unterminated double-quoted string", line)
    body = token[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= len(body):
            raise YamlError("string ends with a dangling backslash", line)
        esc = body[i + 1]
        if esc in _ESCAPES:
            out.append(_ESCAPES[esc])
            i += 2
        elif esc == "u":
            part = body[i + 2 : i + 6]
            if len(part) != 4 or not _HEX4_RE.fullmatch(part):
                raise YamlError("bad \\u escape; expected four hex digits", line)
            out.append(chr(int(part, 16)))
            i += 6
        elif esc == "x":
            part = body[i + 2 : i + 4]
            if len(part) != 2 or not _HEX2_RE.fullmatch(part):
                raise YamlError("bad \\x escape; expected two hex digits", line)
            out.append(chr(int(part, 16)))
            i += 4
        else:
            raise YamlError("unknown escape sequence: \\" + esc, line)
    return "".join(out)


def _parse_single_quoted(token: str, line: int) -> str:
    if len(token) < 2 or token[-1] != "'":
        raise YamlError("unterminated single-quoted string", line)
    return token[1:-1].replace("''", "'")


def _parse_flow_value(token: str, line: int) -> Any:
    token = token.strip()
    if token[:1] in ("[", "{"):
        return _parse_flow(token, line)
    return _parse_scalar(token, line)


def _split_flow(inner: str, line: int) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    start = 0
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch in ("[", "{"):
            depth += 1
        elif ch in ("]", "}"):
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(inner[start:i])
            start = i + 1
        i += 1
    if quote:
        raise YamlError("unterminated string inside flow collection", line)
    parts.append(inner[start:])
    return [p.strip() for p in parts if p.strip()]


def _parse_flow(token: str, line: int) -> Any:
    """Parse a one-line flow collection such as [a, b, 3] or {k: v}."""
    token = token.strip()
    if token.startswith("["):
        if not token.endswith("]"):
            raise YamlError("unterminated flow sequence; expected ]", line)
        inner = token[1:-1].strip()
        if not inner:
            return []
        return [_parse_flow_value(part, line) for part in _split_flow(inner, line)]
    if token.startswith("{"):
        if not token.endswith("}"):
            raise YamlError("unterminated flow mapping; expected }", line)
        inner = token[1:-1].strip()
        if not inner:
            return {}
        mapping: dict[str, Any] = {}
        for part in _split_flow(inner, line):
            if ":" not in part:
                raise YamlError("flow mapping entry is missing a colon", line)
            raw_key, raw_value = part.split(":", 1)
            key = raw_key.strip()
            if key[:1] in ("'", '"') and key[-1:] == key[:1]:
                key = key[1:-1]
            mapping[key] = _parse_flow_value(raw_value, line)
        return mapping
    raise YamlError("not a flow collection", line)


def _has_mapping_colon(text: str) -> int:
    """Return the index of the mapping colon, or -1 when this line is a scalar."""
    quote: str | None = None
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch in ("[", "{"):
            depth += 1
        elif ch in ("]", "}"):
            depth -= 1
        elif ch == ":" and depth == 0:
            if i + 1 == len(text) or text[i + 1] == " ":
                return i
        i += 1
    return -1


class _Parser:
    def __init__(self, lines: list[_Line]) -> None:
        self.lines = lines
        self.pos = 0
        self.lines_map: dict[tuple[Any, ...], int] = {}

    def peek(self) -> _Line | None:
        return self.lines[self.pos] if self.pos < len(self.lines) else None

    def parse(self) -> Any:
        if not self.lines:
            return None
        first = self.lines[0]
        if first.text == "---" and first.indent == 0:
            self.pos += 1
        if self.pos >= len(self.lines):
            return None
        value = self.parse_node(self.lines[self.pos].indent, ())
        if self.pos < len(self.lines):
            raise YamlError("unexpected content (bad indentation?)", self.lines[self.pos].number)
        return value

    def parse_node(self, indent: int, path: tuple[Any, ...]) -> Any:
        line = self.peek()
        if line is None:
            return None
        if line.indent != indent:
            raise YamlError(
                "expected indentation of " + str(indent) + " spaces, got " + str(line.indent),
                line.number,
            )
        if line.text == "-" or line.text.startswith("- "):
            return self.parse_sequence(indent, path)
        return self.parse_mapping(indent, path)

    def parse_sequence(self, indent: int, path: tuple[Any, ...]) -> list[Any]:
        items: list[Any] = []
        while True:
            line = self.peek()
            if line is None or line.indent < indent:
                break
            if line.indent > indent:
                raise YamlError("unexpected indentation inside sequence", line.number)
            if not (line.text == "-" or line.text.startswith("- ")):
                break
            item_path = path + (len(items),)
            rest = line.text[1:].lstrip(" ")
            self.lines_map[item_path] = line.number
            if rest == "":
                self.pos += 1
                nxt = self.peek()
                if nxt is None or nxt.indent <= indent:
                    items.append(None)
                else:
                    items.append(self.parse_node(nxt.indent, item_path))
                continue
            if rest[0] in ("&", "*", "!"):
                raise YamlError("YAML anchors, aliases and tags are not supported", line.number)
            colon = _has_mapping_colon(rest)
            if colon >= 0:
                items.append(self.parse_inline_mapping(rest, colon, indent, item_path, line))
                continue
            if rest[0] in ("[", "{"):
                items.append(_parse_flow(rest, line.number))
                self.pos += 1
                continue
            items.append(_parse_scalar(rest, line.number))
            self.pos += 1
        return items

    def parse_inline_mapping(
        self,
        rest: str,
        colon: int,
        indent: int,
        item_path: tuple[Any, ...],
        line: _Line,
    ) -> dict[str, Any]:
        """Parse a sequence item that starts a mapping: '- key: value'."""
        raw_key = rest[:colon].strip()
        if not raw_key:
            raise YamlError("empty key", line.number)
        if raw_key[:1] in ("'", '"') and raw_key[-1:] == raw_key[:1]:
            key = raw_key[1:-1]
        else:
            key = raw_key
        value_token = rest[colon + 1 :].strip()
        self.lines_map[item_path + (key,)] = line.number
        mapping: dict[str, Any] = {}
        self.pos += 1
        if value_token == "":
            nxt = self.peek()
            if nxt is not None and nxt.indent > indent:
                mapping[key] = self.parse_node(nxt.indent, item_path + (key,))
            else:
                mapping[key] = None
        elif value_token[0] in ("|", ">"):
            mapping[key] = self.parse_block_scalar(value_token, line.number, indent)
        elif value_token[0] in ("[", "{"):
            mapping[key] = _parse_flow(value_token, line.number)
        elif value_token[0] in ("&", "*", "!"):
            raise YamlError("YAML anchors, aliases and tags are not supported", line.number)
        else:
            mapping[key] = _parse_scalar(value_token, line.number)
        nxt = self.peek()
        if nxt is not None and nxt.indent > indent:
            extra = self.parse_mapping(nxt.indent, item_path)
            mapping.update(extra)
        return mapping

    def parse_mapping(self, indent: int, path: tuple[Any, ...]) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        while True:
            line = self.peek()
            if line is None or line.indent < indent:
                break
            if line.indent > indent:
                raise YamlError(
                    "unexpected indentation (a value is indented too far?)", line.number
                )
            if line.text == "-" or line.text.startswith("- "):
                break
            colon = _has_mapping_colon(line.text)
            if colon < 0:
                raise YamlError(
                    "expected 'key: value' but found: " + line.text[:40], line.number
                )
            raw_key = line.text[:colon].strip()
            if not raw_key:
                raise YamlError("empty key", line.number)
            if raw_key[:1] in ("'", '"') and raw_key[-1:] == raw_key[:1]:
                key = raw_key[1:-1]
            else:
                key = raw_key
            self.lines_map[path + (key,)] = line.number
            value_token = line.text[colon + 1 :].strip()
            self.pos += 1
            if value_token == "":
                nxt = self.peek()
                if nxt is not None and nxt.indent > indent:
                    mapping[key] = self.parse_node(nxt.indent, path + (key,))
                elif nxt is not None and nxt.indent == indent and nxt.text.startswith("-"):
                    mapping[key] = self.parse_sequence(indent, path + (key,))
                else:
                    mapping[key] = None
            elif value_token[0] in ("|", ">"):
                mapping[key] = self.parse_block_scalar(value_token, line.number, indent)
            elif value_token[0] in ("[", "{"):
                mapping[key] = _parse_flow(value_token, line.number)
            elif value_token[0] in ("&", "*", "!"):
                raise YamlError("YAML anchors, aliases and tags are not supported", line.number)
            else:
                mapping[key] = _parse_scalar(value_token, line.number)
        return mapping

    def parse_block_scalar(self, header: str, line_no: int, parent_indent: int) -> str:
        style = header[0]
        chomp = header[1:2]
        if chomp and chomp not in ("-", "+"):
            raise YamlError("unsupported block scalar header: " + header, line_no)
        if self.pos >= len(self.lines) or self.lines[self.pos].indent <= parent_indent:
            raise YamlError("block scalar has no indented content", line_no)
        collected: list[str] = []
        block_indent: int | None = None
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            if line.indent <= parent_indent:
                break
            if block_indent is None:
                block_indent = line.indent
            collected.append(" " * max(0, line.indent - block_indent) + line.text)
            self.pos += 1
        text = "\n".join(collected) if style == "|" else _fold(collected)
        if chomp == "-":
            return text.rstrip("\n")
        if chomp == "+":
            return text + "\n"
        return text + "\n"


def _fold(lines: list[str]) -> str:
    """Fold block lines the way YAML folded scalars do (blank line -> newline)."""
    out: list[str] = []
    pending_blank = False
    for line in lines:
        if line == "":
            pending_blank = True
            continue
        if out:
            out.append("\n" if pending_blank else " ")
        out.append(line)
        pending_blank = False
    return "".join(out)


def parse_yaml(source: str) -> Document:
    """Parse YAML source into a Document (data plus a path -> line table)."""
    if not isinstance(source, str):
        raise YamlError("source must be a string", 1)
    if "\x00" in source:
        raise YamlError("document contains NUL bytes; is this really a text file?", 1)
    lines = _split_lines(source)
    for index, line in enumerate(lines):
        if line.text in ("---", "...") and line.indent == 0:
            if index == 0 and line.text == "---":
                continue
            raise YamlError("multi-document YAML is not supported", line.number)
    parser = _Parser(lines)
    data = parser.parse()
    return Document(data, parser.lines_map)


def _dump_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    risky = set(":#[]{}&*!|>'\"%@")
    control = any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text)
    needs_quote = (
        text.strip() != text or text == "" or any(c in risky for c in text) or control
    )
    if needs_quote:
        pieces: list[str] = []
        for ch in text:
            if ch == "\\":
                pieces.append("\\\\")
            elif ch == '"':
                pieces.append('\\"')
            elif ch == "\n":
                pieces.append("\\n")
            elif ch == "\t":
                pieces.append("\\t")
            elif ch == "\r":
                pieces.append("\\r")
            elif ord(ch) < 0x20 or ord(ch) == 0x7F:
                pieces.append("\\x%02x" % ord(ch))
            else:
                pieces.append(ch)
        return '"' + "".join(pieces) + '"'
    return text


def dump_yaml(value: Any, indent: int = 0) -> str:
    """Serialise simple data back to block YAML (used by record and scene export)."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return pad + "{}"
        out: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                out.append(pad + str(key) + ":")
                out.append(dump_yaml(item, indent + 1))
            else:
                out.append(pad + str(key) + ": " + _dump_scalar(item))
        return "\n".join(out)
    if isinstance(value, list):
        if not value:
            return pad + "[]"
        out = []
        for item in value:
            if isinstance(item, dict) and item:
                pairs = list(item.items())
                first_key, first_value = pairs[0]
                out.append(pad + "- " + str(first_key) + ": " + _dump_scalar(first_value))
                for key, sub in pairs[1:]:
                    if isinstance(sub, (dict, list)) and sub:
                        out.append(pad + "  " + str(key) + ":")
                        out.append(dump_yaml(sub, indent + 2))
                    else:
                        out.append(pad + "  " + str(key) + ": " + _dump_scalar(sub))
            elif isinstance(item, list) and item:
                out.append(pad + "-")
                out.append(dump_yaml(item, indent + 1))
            else:
                out.append(pad + "- " + _dump_scalar(item))
        return "\n".join(out)
    return pad + _dump_scalar(value)
