"""The pure envelope codec for spanned property-list items
(``actingweb.property_list_span``). No fake, no backend: table-driven.

Phase 2 of thoughts/plans/2026-10-30-spanned-list-items.md.
"""

import json
from typing import Any

import pytest

from actingweb.property_list_span import (
    GEN_RE,
    KEY_ROW_RE,
    SPAN_ROW_RE,
    EnvelopeError,
    SpanInfo,
    aux_partition,
    encode_item,
    encoded_size,
    gen_age_seconds,
    looks_like_envelope,
    new_gen,
    parse,
    part_names,
    span_prefix,
    split_parts,
    wrap,
)

GEN = "1793393684000-0123456789abcdef"


class TestSplitParts:
    def test_exactly_part_bytes_is_one_part(self) -> None:
        assert split_parts("x" * 10, 10) == ["x" * 10]

    def test_one_more_is_two_parts(self) -> None:
        assert split_parts("x" * 11, 10) == ["x" * 10, "x"]

    def test_multibyte_split_on_character_boundaries(self) -> None:
        value = "é" * 7 + "a"  # é is 2 bytes in UTF-8
        parts = split_parts(value, 5)
        assert "".join(parts) == value
        assert all(len(p.encode("utf-8")) <= 5 for p in parts)
        assert all(parts)

    def test_parts_are_never_empty_and_join_back(self) -> None:
        for size in (1, 4, 5, 9, 100):
            value = "ab" * size
            parts = split_parts(value, 7)
            assert "".join(parts) == value
            assert all(parts)

    def test_too_small_part_size_raises(self) -> None:
        with pytest.raises(ValueError):
            split_parts("abc", 3)

    def test_empty_value_raises(self) -> None:
        with pytest.raises(ValueError):
            split_parts("", 10)


class TestEncodeItem:
    def test_json_item(self) -> None:
        assert encode_item({"a": 1}) == json.dumps({"a": 1})

    def test_lone_surrogate_is_sanitised_before_measuring(self) -> None:
        class Odd:
            def __str__(self) -> str:
                return "bad\udc80tail"

        from actingweb.db.utils import sanitize_json_data

        encoded = encode_item(Odd())
        assert "\udc80" not in encoded
        # Exactly what the backend stores for that string.
        assert encoded == sanitize_json_data("bad\udc80tail")
        assert encoded_size(encoded) == len(encoded.encode("utf-8"))

    def test_reserved_dict_key_refused(self) -> None:
        with pytest.raises(ValueError, match="__aw_env"):
            encode_item({"__aw_env": 1})
        with pytest.raises(ValueError, match="__aw_env"):
            encode_item({"other": 1, "__aw_env": 2})

    def test_str_fallback_that_looks_like_an_envelope_refused(self) -> None:
        class Sneaky:
            def __str__(self) -> str:
                return '{"__aw_env": 1, "v": "x"}'

        with pytest.raises(ValueError, match="envelope"):
            encode_item(Sneaky())

    def test_nested_marker_is_an_ordinary_item(self) -> None:
        assert encode_item({"x": {"__aw_env": 1}})


class TestParse:
    def test_plain_items_are_not_envelopes(self) -> None:
        for raw in ('"text"', "1", "[1, 2]", '{"a": 1}', '{"a": 1, "__aw_env": 1}'):
            assert parse(raw) is None
        assert not looks_like_envelope('{"a": 1}')

    @pytest.mark.parametrize(
        "obj",
        [
            {"__aw_env": 1, "span": {"gen": GEN, "parts": 0, "bytes": 5}},
            {"__aw_env": 1, "span": {"gen": GEN, "parts": "3", "bytes": 5}},
            {"__aw_env": 1, "span": {"gen": GEN, "parts": True, "bytes": 5}},
            {"__aw_env": 1, "span": {"gen": "../x", "parts": 1, "bytes": 5}},
            {"__aw_env": 1, "span": {"gen": GEN, "parts": 1}},
            {"__aw_env": 1, "span": {"gen": GEN, "parts": 1, "bytes": -1}},
            {"__aw_env": 1, "span": "nope"},
            {"__aw_env": 1},
            {"__aw_env": 1, "key": 5, "v": 1},
            {
                "__aw_env": 1,
                "span": {"gen": GEN, "parts": 1, "bytes": 5, "sha256": "x"},
            },
        ],
    )
    def test_malformed_envelopes_raise(self, obj: dict[str, Any]) -> None:
        with pytest.raises(EnvelopeError):
            parse(json.dumps(obj))

    @pytest.mark.parametrize(
        "obj",
        [
            {"__aw_env": 2, "v": 1},
            {"__aw_env": True, "v": 1},
            {"__aw_env": "x", "title": "a pre-3.16 user item"},
        ],
    )
    def test_marker_other_than_exactly_1_is_a_plain_item(
        self, obj: dict[str, Any]
    ) -> None:
        assert parse(json.dumps(obj)) is None

    def test_marker_not_first_is_a_plain_item_not_an_envelope(self) -> None:
        raw = json.dumps({"v": 1, "__aw_env": 1})
        assert parse(raw) is None

    def test_invalid_json_after_the_marker_is_a_plain_item(self) -> None:
        # It cannot be shown to be the library's: read it as the raw value.
        assert parse('{"__aw_env": 1, ') is None

    def test_round_trip_with_span_preserves_extra(self) -> None:
        span = SpanInfo(gen=GEN, parts=3, bytes=1000, sha256="ab" * 32)
        raw = wrap(span=span, key="k" * 64, tok="t1", extra={"later": [1, 2]})
        assert raw.startswith('{"__aw_env": 1')
        env = parse(raw)
        assert env is not None
        assert env.span == span
        assert env.key == "k" * 64
        assert env.tok == "t1"
        assert env.extra == {"later": [1, 2]}
        assert not env.has_value

    def test_round_trip_with_value(self) -> None:
        raw = wrap(value={"a": [1, None]}, tok="t")
        env = parse(raw)
        assert env is not None
        assert env.span is None
        assert env.value == {"a": [1, None]}
        assert env.has_value

    def test_wrap_needs_exactly_one_of_value_and_span(self) -> None:
        with pytest.raises(ValueError):
            wrap()
        with pytest.raises(ValueError):
            wrap(value=1, span=SpanInfo(gen=GEN, parts=1, bytes=1))


class TestShapes:
    @pytest.mark.parametrize(
        "suffix, matches",
        [
            (f"{GEN}-p0003", True),
            (f"{GEN}-0003", False),
            ("1000", False),
            (f"{GEN}-p003", False),
            (f"{GEN}-p0003-x", False),
            ("1793393684000-0123456789ABCDEF-p0000", False),
        ],
    )
    def test_span_row_shape(self, suffix: str, matches: bool) -> None:
        assert bool(SPAN_ROW_RE.match(suffix)) is matches

    def test_key_row_shape(self) -> None:
        assert KEY_ROW_RE.match("a" * 64)
        assert not KEY_ROW_RE.match("a" * 63)
        assert not KEY_ROW_RE.match("A" * 64)

    def test_names(self) -> None:
        assert span_prefix("notes") == "list:notes-$span-"
        assert part_names("notes", GEN, 2) == [
            f"list:notes-$span-{GEN}-p0000",
            f"list:notes-$span-{GEN}-p0001",
        ]

    def test_new_gen_shape_and_age(self) -> None:
        gen = new_gen()
        assert GEN_RE.match(gen)
        assert 0 <= gen_age_seconds(gen) < 60
        assert gen_age_seconds(f"{0:013d}-{'0' * 16}") > 10**9


class TestAuxPartition:
    def test_hex_actor_id(self) -> None:
        assert aux_partition("0123abcd") == "0123abcd$aux"

    def test_dollar_actor_id_refused(self) -> None:
        with pytest.raises(ValueError):
            aux_partition("a$b")
