"""Tests for the dependency-free YAML subset parser."""
from __future__ import annotations

import pytest

from terminal_snap.yaml_lite import Document, YamlError, dump_yaml, parse_yaml


def test_scalars_and_types() -> None:
    doc = parse_yaml("name: demo\ncount: 3\nratio: 1.5\nflag: true\nnothing: null\n")
    assert doc.data == {"name": "demo", "count": 3, "ratio": 1.5, "flag": True, "nothing": None}


def test_nested_mapping() -> None:
    doc = parse_yaml("a:\n  b:\n    c: 1\n")
    assert doc.data == {"a": {"b": {"c": 1}}}


def test_sequence_of_scalars() -> None:
    doc = parse_yaml("items:\n  - one\n  - two\n  - 3\n")
    assert doc.data == {"items": ["one", "two", 3]}


def test_sequence_of_mappings() -> None:
    text = "lines:\n  - cmd: run\n    delay: 2\n  - out: done\n"
    doc = parse_yaml(text)
    assert doc.data == {"lines": [{"cmd": "run", "delay": 2}, {"out": "done"}]}


def test_quoted_strings_with_escapes() -> None:
    doc = parse_yaml('a: "tab\\there"\nb: "quote \\" inside"\nc: \'single\'\n')
    assert doc.data == {"a": "tab\there", "b": 'quote " inside', "c": "single"}


def test_unicode_escape() -> None:
    doc = parse_yaml('a: "caf\\u00e9"\n')
    assert doc.data == {"a": "café"}


def test_literal_block_scalar() -> None:
    doc = parse_yaml("text: |\n  line one\n  line two\n")
    assert doc.data["text"] == "line one\nline two\n"


def test_literal_block_scalar_strip() -> None:
    doc = parse_yaml("text: |-\n  line one\n")
    assert doc.data["text"] == "line one"


def test_folded_block_scalar() -> None:
    doc = parse_yaml("text: >\n  one\n  two\n")
    assert doc.data["text"] == "one two\n"


def test_flow_sequence_and_mapping() -> None:
    doc = parse_yaml("a: [1, two, {x: 3}]\nb: {k: v, n: 2}\n")
    assert doc.data["a"] == [1, "two", {"x": 3}]
    assert doc.data["b"] == {"k": "v", "n": 2}


def test_comments_are_ignored() -> None:
    doc = parse_yaml("# header\na: 1  # trailing\n\n# footer\n")
    assert doc.data == {"a": 1}


def test_hash_inside_string_is_not_a_comment() -> None:
    doc = parse_yaml('a: "keep # this"\nb: keep#too\n')
    assert doc.data == {"a": "keep # this", "b": "keep#too"}


def test_document_marker() -> None:
    doc = parse_yaml("---\na: 1\n")
    assert doc.data == {"a": 1}


def test_line_numbers_are_recorded() -> None:
    doc = parse_yaml("title: x\nlines:\n  - text: hi\n")
    assert doc.line_of(("title",)) == 1
    assert doc.line_of(("lines",)) == 2
    assert doc.line_of(("lines", 0, "text")) == 3


def test_line_of_falls_back_to_parent() -> None:
    doc = parse_yaml("lines:\n  - text: hi\n")
    assert doc.line_of(("lines", 0, "missing")) == 2


def test_tabs_for_indentation_are_rejected() -> None:
    with pytest.raises(YamlError) as info:
        parse_yaml("a:\n\tb: 1\n")
    assert "tabs are not allowed" in str(info.value)
    assert info.value.line == 2


def test_unterminated_quote_is_rejected() -> None:
    with pytest.raises(YamlError) as info:
        parse_yaml('a: "oops\n')
    assert "unterminated" in str(info.value)


def test_missing_colon_is_rejected() -> None:
    with pytest.raises(YamlError) as info:
        parse_yaml("just a scalar line\n")
    assert "expected 'key: value'" in str(info.value)


def test_anchor_is_rejected_explicitly() -> None:
    with pytest.raises(YamlError) as info:
        parse_yaml("a: &anchor value\n")
    assert "anchors" in str(info.value)


def test_empty_document_is_none() -> None:
    doc = parse_yaml("# only comments\n")
    assert doc.data is None


def test_nul_byte_is_rejected() -> None:
    with pytest.raises(YamlError):
        parse_yaml("a: b\x00c\n")


def test_bad_hex_escape_is_rejected() -> None:
    with pytest.raises(YamlError) as info:
        parse_yaml('a: "\\xZZ"\n')
    assert "\\x" in str(info.value)


def test_dump_roundtrip() -> None:
    data = {"title": "hello", "width": 80, "flag": False, "lines": [{"out": "text: with colon"}]}
    text = dump_yaml(data)
    assert parse_yaml(text).data == data


def test_dump_escapes_control_characters() -> None:
    text = dump_yaml({"out": "\x1b[31mred\x1b[0m"})
    assert "\\x1b" in text
    assert parse_yaml(text).data["out"] == "\x1b[31mred\x1b[0m"


def test_dump_quotes_risky_scalars() -> None:
    assert dump_yaml({"a": "x: y"}).startswith('a: "')


def test_document_dataclass_defaults() -> None:
    doc = Document({"a": 1})
    assert doc.line_of(("a",)) == 0
