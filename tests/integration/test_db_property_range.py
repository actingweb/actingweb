"""DbProperty.get_range() / create_if_not_exists() (both backends).

These back the v2 fractional-rank-key list storage format (Phase 4 of
thoughts/plans/2026-08-08-property-list-index-integrity.md): get_range()
reads a list's item rows in one query instead of one per item;
create_if_not_exists() gives collision-free conditional inserts for
generated rank keys. Lives under tests/integration/ because PostgreSQL
needs the migrated schema the session fixtures below provision.
"""

import os
import uuid

import pytest

from actingweb.db import get_property
from actingweb.interface.app import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")


@pytest.fixture
def aw_app(docker_services, setup_database, worker_info):  # noqa: ARG001
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    return ActingWebApp(
        aw_type="urn:actingweb:test:db_property_range",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    )


@pytest.fixture
def config(aw_app):
    return aw_app.get_config()


@pytest.fixture
def actor_id():
    return f"range-test-{uuid.uuid4()}"


class TestGetRange:
    def test_range_returns_only_rows_in_bounds(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:foo-#a0", value='"first"')
        assert db.set(actor_id=actor_id, name="list:foo-#a1", value='"second"')
        # Outside the range: v1 item row, meta row, unrelated property.
        assert db.set(actor_id=actor_id, name="list:foo-0", value='"v1-item"')
        assert db.set(actor_id=actor_id, name="list:foo-meta", value="{}")
        assert db.set(actor_id=actor_id, name="unrelated", value="x")

        result = get_property(config).get_range(
            actor_id=actor_id, lower="list:foo-#", upper="list:foo-$"
        )

        assert result == {
            "list:foo-#a0": '"first"',
            "list:foo-#a1": '"second"',
        }

    def test_range_excludes_sibling_list_with_shared_prefix(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:foo-#a0", value='"foo-item"')
        assert db.set(actor_id=actor_id, name="list:foo-x-#a0", value='"sibling"')

        result = get_property(config).get_range(
            actor_id=actor_id, lower="list:foo-#", upper="list:foo-$"
        )

        assert result == {"list:foo-#a0": '"foo-item"'}

    def test_keys_only_returns_empty_values(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:bar-#a0", value='"x"')
        assert db.set(actor_id=actor_id, name="list:bar-#a1", value='"y"')

        result = get_property(config).get_range(
            actor_id=actor_id, lower="list:bar-#", upper="list:bar-$", keys_only=True
        )

        assert result == {"list:bar-#a0": "", "list:bar-#a1": ""}

    def test_empty_range_returns_empty_dict(self, config, actor_id):
        result = get_property(config).get_range(
            actor_id=actor_id, lower="list:nothere-#", upper="list:nothere-$"
        )
        assert result == {}


class TestCreateIfNotExists:
    def test_create_succeeds_on_absent_row(self, config, actor_id):
        db = get_property(config)
        assert db.create_if_not_exists(
            actor_id=actor_id, name="list:cine-#a0", value='"item"'
        )
        assert (
            get_property(config).get(actor_id=actor_id, name="list:cine-#a0")
            == '"item"'
        )

    def test_create_fails_on_existing_row_without_overwriting(self, config, actor_id):
        db = get_property(config)
        assert db.create_if_not_exists(
            actor_id=actor_id, name="list:cine-#a0", value='"original"'
        )
        collided = get_property(config).create_if_not_exists(
            actor_id=actor_id, name="list:cine-#a0", value='"colliding"'
        )
        assert collided is False
        assert (
            get_property(config).get(actor_id=actor_id, name="list:cine-#a0")
            == '"original"'
        )


class TestConditionalDelete:
    """delete_if_value_equals() against the real backend (both, via
    DATABASE_BACKEND) -- the primitive pop()/remove() rely on to guarantee
    they act on the value they read."""

    def test_deletes_only_on_an_exact_value_match(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:cd-#a0", value='"original"')

        refused = get_property(config).delete_if_value_equals(
            actor_id=actor_id, name="list:cd-#a0", value='"something-else"'
        )
        assert refused is False
        assert (
            get_property(config).get(actor_id=actor_id, name="list:cd-#a0")
            == '"original"'
        )

        deleted = get_property(config).delete_if_value_equals(
            actor_id=actor_id, name="list:cd-#a0", value='"original"'
        )
        assert deleted is True
        assert get_property(config).get(actor_id=actor_id, name="list:cd-#a0") is None

    def test_missing_row_reports_false_not_an_error(self, config, actor_id):
        assert (
            get_property(config).delete_if_value_equals(
                actor_id=actor_id, name="list:cd-#never", value='"x"'
            )
            is False
        )

    def test_overwritten_row_is_not_deleted(self, config, actor_id):
        assert get_property(config).set(
            actor_id=actor_id, name="list:cd-#b0", value='"v1"'
        )
        read = get_property(config).get(actor_id=actor_id, name="list:cd-#b0")
        assert read == '"v1"'

        # Another writer replaces it before our conditional delete lands.
        assert get_property(config).set(
            actor_id=actor_id, name="list:cd-#b0", value='"v2"'
        )

        assert (
            get_property(config).delete_if_value_equals(
                actor_id=actor_id, name="list:cd-#b0", value=read
            )
            is False
        )
        assert get_property(config).get(actor_id=actor_id, name="list:cd-#b0") == '"v2"'


class TestConditionalSet:
    """set_if_value_equals() against the real backend (both, via
    DATABASE_BACKEND) -- Phase 8 of thoughts/plans/2026-08-20-v2-
    positional-access-cost.md. Compare-and-swap, the write-side
    counterpart to TestConditionalDelete above."""

    def test_sets_only_on_an_exact_value_match(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:cs-#a0", value='"original"')

        refused = get_property(config).set_if_value_equals(
            actor_id=actor_id,
            name="list:cs-#a0",
            expected='"something-else"',
            value='"new"',
        )
        assert refused is False
        assert (
            get_property(config).get(actor_id=actor_id, name="list:cs-#a0")
            == '"original"'
        )

        updated = get_property(config).set_if_value_equals(
            actor_id=actor_id,
            name="list:cs-#a0",
            expected='"original"',
            value='"new"',
        )
        assert updated is True
        assert (
            get_property(config).get(actor_id=actor_id, name="list:cs-#a0") == '"new"'
        )

    def test_missing_row_reports_false_not_an_error(self, config, actor_id):
        assert (
            get_property(config).set_if_value_equals(
                actor_id=actor_id,
                name="list:cs-#never",
                expected='"x"',
                value='"y"',
            )
            is False
        )

    def test_overwritten_row_is_not_set(self, config, actor_id):
        assert get_property(config).set(
            actor_id=actor_id, name="list:cs-#b0", value='"v1"'
        )
        read = get_property(config).get(actor_id=actor_id, name="list:cs-#b0")
        assert read == '"v1"'

        # Another writer replaces it before our conditional set lands.
        assert get_property(config).set(
            actor_id=actor_id, name="list:cs-#b0", value='"v2"'
        )

        assert (
            get_property(config).set_if_value_equals(
                actor_id=actor_id, name="list:cs-#b0", expected=read, value='"v3"'
            )
            is False
        )
        assert get_property(config).get(actor_id=actor_id, name="list:cs-#b0") == '"v2"'

    def test_condition_failure_returns_false_not_dberror(self, config, actor_id):
        """The distinction the whole retry design rests on: a condition
        miss is a normal outcome, not a fault."""
        assert get_property(config).set(
            actor_id=actor_id, name="list:cs-#c0", value='"v1"'
        )
        result = get_property(config).set_if_value_equals(
            actor_id=actor_id, name="list:cs-#c0", expected='"wrong"', value='"v2"'
        )
        assert result is False  # no exception raised


class TestGetLastInRange:
    """get_last_in_range() against the real backend -- Phase 9B's
    append() reads a list's highest rank key from this instead of the
    whole-list range read."""

    def test_returns_the_bytewise_greatest_name(self, config, actor_id):
        db = get_property(config)
        for rank in ["a0", "a1", "a2"]:
            assert db.set(actor_id=actor_id, name=f"list:gl-#{rank}", value='"x"')

        result = get_property(config).get_last_in_range(
            actor_id=actor_id, lower="list:gl-#", upper="list:gl-$"
        )
        assert result == "list:gl-#a2"

    def test_empty_range_returns_none(self, config, actor_id):
        result = get_property(config).get_last_in_range(
            actor_id=actor_id, lower="list:glempty-#", upper="list:glempty-$"
        )
        assert result is None

    def test_case_boundary_is_byte_order_not_locale_order(self, config, actor_id):
        """The regression a locale collation fails: max("Z", "a") is "a"
        bytewise (0x5A < 0x61) but "Z" under en_US-style locale collation.
        A wrong answer here becomes a mid-list append."""
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:glcase-#Z", value='"upper"')
        assert db.set(actor_id=actor_id, name="list:glcase-#a", value='"lower"')

        result = get_property(config).get_last_in_range(
            actor_id=actor_id, lower="list:glcase-#", upper="list:glcase-$"
        )
        assert result == "list:glcase-#a"  # bytewise-greatest, not locale-greatest


class TestGetPrefix:
    """``get_prefix()`` -- the sibling ``get_range()`` cannot express, because
    a prefix has no exact inclusive upper bound. Every synthesised sentinel
    (``prefix + "~"``, ``prefix + "\\uffff"``) is a guess about which byte
    sorts last, and byte ordering does not even agree across PostgreSQL
    collations. These run against real storage on both backends precisely
    because a fake would agree with whatever the implementation does.
    """

    def test_prefix_returns_exactly_the_rows_under_it(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:memory_a-meta", value="{}")
        assert db.set(actor_id=actor_id, name="list:memory_a-#a0", value='"one"')
        assert db.set(actor_id=actor_id, name="list:memory_b-meta", value="{}")
        # Outside: a different family, and a plain property.
        assert db.set(actor_id=actor_id, name="list:notes-meta", value="{}")
        assert db.set(actor_id=actor_id, name="memory_a", value="scalar")

        result = get_property(config).get_prefix(
            actor_id=actor_id, prefix="list:memory_"
        )

        assert result == {
            "list:memory_a-meta": "{}",
            "list:memory_a-#a0": '"one"',
            "list:memory_b-meta": "{}",
        }

    def test_a_prefix_includes_the_list_named_exactly_that(self, config, actor_id):
        """The documented semantics, and the reason the public wrapper tells
        callers to pass the delimiter: ``"memory"`` means "and everything
        beginning with it", not "the memory namespace"."""
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:memory-meta", value="{}")
        assert db.set(actor_id=actor_id, name="list:memory_a-meta", value="{}")
        assert db.set(actor_id=actor_id, name="list:memory-old-meta", value="{}")

        broad = get_property(config).get_prefix(actor_id=actor_id, prefix="list:memory")
        narrow = get_property(config).get_prefix(
            actor_id=actor_id, prefix="list:memory_"
        )

        assert set(broad) == {
            "list:memory-meta",
            "list:memory_a-meta",
            "list:memory-old-meta",
        }
        assert set(narrow) == {"list:memory_a-meta"}

    def test_non_ascii_prefix_and_row_names(self, config, actor_id):
        """The case a ``~``-style sentinel gets wrong: ``é`` (U+00E9) encodes
        to bytes above ``~`` (0x7E), so a synthesised upper bound of
        ``list:étag~`` excludes rows a prefix read must return."""
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:étag-meta", value="{}")
        assert db.set(actor_id=actor_id, name="list:étag-#a0", value='"é-item"')
        assert db.set(actor_id=actor_id, name="list:étagère-meta", value="{}")
        assert db.set(actor_id=actor_id, name="list:etag-meta", value="{}")

        result = get_property(config).get_prefix(actor_id=actor_id, prefix="list:éta")

        assert set(result) == {
            "list:étag-meta",
            "list:étag-#a0",
            "list:étagère-meta",
        }

    def test_no_unicode_normalization_on_either_backend(self, config, actor_id):
        """An NFD prefix must not match an NFC name, nor the reverse. Both
        ``begins_with`` and ``starts_with()`` compare bytes; this pins that
        they agree, since a backend that normalized would return the row."""
        nfc = "list:café-meta"  # café, precomposed
        nfd_prefix = "list:café"  # cafe + combining acute
        assert nfc != "list:café-meta"

        assert get_property(config).set(actor_id=actor_id, name=nfc, value="{}")

        assert (
            get_property(config).get_prefix(actor_id=actor_id, prefix=nfd_prefix) == {}
        )
        assert set(
            get_property(config).get_prefix(actor_id=actor_id, prefix="list:café")
        ) == {nfc}

    def test_adversarial_names_are_matched_byte_for_byte(self, config, actor_id):
        """``_`` and ``%`` are LIKE metacharacters; this method uses neither
        ``LIKE`` nor a pattern language, so both are literal. ``#`` and ``$``
        are the v2 rank sentinel and its successor byte."""
        db = get_property(config)
        names = [
            "list:foo-#a0",
            "list:foo-$weird",
            "list:foo%pct-meta",
            "list:foo_und-meta",
            "list:fooX-meta",
            "list:foo-meta",
        ]
        for n in names:
            assert db.set(actor_id=actor_id, name=n, value="v")

        # "_" is literal: it must NOT act as LIKE's single-character wildcard.
        assert set(
            get_property(config).get_prefix(actor_id=actor_id, prefix="list:foo_")
        ) == {"list:foo_und-meta"}
        # "%" likewise.
        assert set(
            get_property(config).get_prefix(actor_id=actor_id, prefix="list:foo%")
        ) == {"list:foo%pct-meta"}
        # And a name that is a prefix of another is included, not excluded.
        assert set(
            get_property(config).get_prefix(actor_id=actor_id, prefix="list:foo-")
        ) == {"list:foo-#a0", "list:foo-$weird", "list:foo-meta"}

    def test_empty_prefix_returns_empty_and_raises_nothing(self, config, actor_id):
        """PostgreSQL's ``starts_with(x, '')`` is true for every row and
        DynamoDB's ``begins_with(name, "")`` is a ValidationException — so
        the guard is what makes the two backends agree, and stops a method
        named for a prefix silently becoming a partition dump."""
        assert get_property(config).set(
            actor_id=actor_id, name="list:anything-meta", value="{}"
        )

        assert get_property(config).get_prefix(actor_id=actor_id, prefix="") == {}
        assert get_property(config).get_prefix(actor_id=actor_id, prefix=None) == {}
        assert get_property(config).get_prefix(actor_id=None, prefix="list:") == {}

    def test_no_match_returns_empty_dict(self, config, actor_id):
        assert (
            get_property(config).get_prefix(actor_id=actor_id, prefix="list:nothere")
            == {}
        )

    def test_keys_only_returns_empty_values(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:ko_a-meta", value="{}")
        assert db.set(actor_id=actor_id, name="list:ko_b-meta", value="{}")

        result = get_property(config).get_prefix(
            actor_id=actor_id, prefix="list:ko_", keys_only=True
        )

        assert result == {"list:ko_a-meta": "", "list:ko_b-meta": ""}

    def test_eventual_and_strong_reads_return_the_same_rows(self, config, actor_id):
        """``consistent_read`` is forwarded, not dropped. PostgreSQL ignores
        it by construction; on DynamoDB Local both modes read the same store,
        so this asserts the parameter is accepted and the result unchanged —
        the cost difference is not observable from here."""
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:cr_a-meta", value="{}")

        strong = get_property(config).get_prefix(
            actor_id=actor_id, prefix="list:cr_", consistent_read=True
        )
        eventual = get_property(config).get_prefix(
            actor_id=actor_id, prefix="list:cr_", consistent_read=False
        )

        assert strong == eventual == {"list:cr_a-meta": "{}"}
