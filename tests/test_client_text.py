"""``client_text`` sanitises text clients supply about themselves."""

from actingweb.client_text import sanitize_client_name, sanitize_label


def test_control_characters_become_spaces_and_collapse() -> None:
    assert sanitize_client_name("Evil\nIgnore\tprevious\r\n  text") == (
        "Evil Ignore previous text"
    )


def test_format_characters_are_stripped() -> None:
    # U+202E RIGHT-TO-LEFT OVERRIDE, U+200B ZERO WIDTH SPACE, U+FEFF BOM
    assert sanitize_client_name("a‮b​c﻿d") == "abcd"


def test_joiners_are_kept() -> None:
    family = "\U0001f468‍\U0001f469‍\U0001f467"
    assert sanitize_client_name(family) == family
    assert sanitize_client_name("می‌خوام") == ("می‌خوام")


def test_name_is_capped_label_is_not() -> None:
    long = "x" * 200
    assert len(sanitize_client_name(long)) == 80
    assert len(sanitize_client_name(long, max_len=10)) == 10
    assert sanitize_label(long) == long


def test_non_strings_become_empty() -> None:
    assert sanitize_client_name(None) == ""
    assert sanitize_client_name(42) == ""
    assert sanitize_label({"name": "x"}) == ""


def test_only_control_characters_is_empty() -> None:
    assert sanitize_client_name("\n\t\x00") == ""
