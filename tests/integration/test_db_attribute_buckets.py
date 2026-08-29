"""Attribute bucket isolation (both backends).

``Attribute.bucket_name`` on DynamoDB is ``bucket + ":" + name``, and
``get_bucket()``/``delete_bucket()`` matched it with a bare
``begins_with(bucket)`` — so a bucket saw, and deleted, the rows of every
bucket having its name as a prefix. PostgreSQL compares ``bucket`` exactly and
was never affected; these tests assert the two backends now agree, which is
the point of running them here rather than as mocked units.

Lives under tests/integration/ because PostgreSQL needs the migrated schema
the session fixtures below provision.
"""

import os
import uuid

import pytest

from actingweb.db import get_attribute
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
        aw_type="urn:actingweb:test:db_attribute_buckets",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    )


@pytest.fixture
def config(aw_app):
    return aw_app.get_config()


@pytest.fixture
def actor_id():
    return f"bucket-test-{uuid.uuid4()}"


def _names(bucket_contents):
    return set(bucket_contents or {})


def _bucket(config, actor_id, bucket):
    """get_bucket() narrowed to a dict.

    Both backends return ``None`` on a backend fault (and PostgreSQL also for
    a genuinely empty bucket), so a test that subscripts the result has to say
    it expected content.
    """
    result = get_attribute(config).get_bucket(actor_id=actor_id, bucket=bucket)
    assert result is not None
    return result


class TestBucketPrefixIsolation:
    def test_get_bucket_excludes_prefix_sibling(self, config, actor_id):
        db = get_attribute(config)
        assert db.set_attr(actor_id=actor_id, bucket="b", name="x", data="b-value")
        assert db.set_attr(actor_id=actor_id, bucket="bb", name="y", data="bb-value")

        result = _bucket(config, actor_id, "b")

        assert _names(result) == {"x"}
        assert result["x"]["data"] == "b-value"

    def test_delete_bucket_spares_prefix_sibling(self, config, actor_id):
        db = get_attribute(config)
        assert db.set_attr(actor_id=actor_id, bucket="b", name="x", data="b-value")
        assert db.set_attr(actor_id=actor_id, bucket="bb", name="y", data="bb-value")

        assert get_attribute(config).delete_bucket(actor_id=actor_id, bucket="b")

        assert (
            _names(get_attribute(config).get_bucket(actor_id=actor_id, bucket="b"))
            == set()
        )
        sibling = _bucket(config, actor_id, "bb")
        assert _names(sibling) == {"y"}
        assert sibling["y"]["data"] == "bb-value"

    def test_remote_peer_prefix_siblings_stay_separate(self, config, actor_id):
        """``remote:abc`` and ``remote:abcd`` — the reachable production case.

        ``RemotePeerStore.delete_all()`` deletes bucket ``remote:{peer_id}``,
        and most call sites build that id with ``validate_peer_id=False``, so
        the ids are remote-party-chosen and prefix relationships are reachable.
        """
        db = get_attribute(config)
        assert db.set_attr(
            actor_id=actor_id, bucket="remote:abc", name="x", data="abc-value"
        )
        assert db.set_attr(
            actor_id=actor_id, bucket="remote:abcd", name="x", data="abcd-value"
        )

        short = _bucket(config, actor_id, "remote:abc")
        assert _names(short) == {"x"}
        assert short["x"]["data"] == "abc-value"

        assert get_attribute(config).delete_bucket(
            actor_id=actor_id, bucket="remote:abc"
        )

        survivor = _bucket(config, actor_id, "remote:abcd")
        assert _names(survivor) == {"x"}
        assert survivor["x"]["data"] == "abcd-value"

    def test_colliding_composite_key_belongs_to_one_bucket_only(self, config, actor_id):
        """Bucket ``remote:abc``/name ``x`` vs bucket ``remote``/name ``abc:x``.

        Both produce the range key ``remote:abc:x``, and both backends key on
        ``(id, bucket_name)`` — so these are the *same row*, not two rows, and
        the delimiter cannot say who owns it. The stored ``bucket`` says, and
        only an exact compare reads it. DynamoDB had no such compare, so the
        row answered to both buckets; PostgreSQL always had one. This asserts
        they now agree, in both directions.
        """
        db = get_attribute(config)
        assert db.set_attr(
            actor_id=actor_id, bucket="remote", name="abc:x", data="flat-bucket"
        )

        assert (
            _names(
                get_attribute(config).get_bucket(actor_id=actor_id, bucket="remote:abc")
            )
            == set()
        )
        flat = _bucket(config, actor_id, "remote")
        assert _names(flat) == {"abc:x"}
        assert flat["abc:x"]["data"] == "flat-bucket"

        # And the delete side: tearing down "remote:abc" must not touch it.
        assert get_attribute(config).delete_bucket(
            actor_id=actor_id, bucket="remote:abc"
        )
        survivor = get_attribute(config).get_bucket(actor_id=actor_id, bucket="remote")
        assert _names(survivor) == {"abc:x"}

    def test_colliding_composite_key_answers_to_exactly_one_bucket(
        self, config, actor_id
    ):
        """Both buckets write the colliding key; exactly one may own the row.

        *Which* one is a backend difference this phase does not touch, and
        deliberately does not assert: DynamoDB's ``save()`` is a PutItem that
        replaces ``bucket`` wholesale, while PostgreSQL's ``ON CONFLICT DO
        UPDATE`` refreshes only ``data``/``timestamp`` and keeps the original
        attribution. Filed as thoughts/todo/attribute-upsert-bucket-drift.md.
        What both backends must agree on — and what only the exact ``bucket``
        compare delivers on DynamoDB — is that the single stored row never
        answers to *both*.
        """
        db = get_attribute(config)
        assert db.set_attr(
            actor_id=actor_id, bucket="remote", name="abc:x", data="flat-bucket"
        )
        assert db.set_attr(
            actor_id=actor_id, bucket="remote:abc", name="x", data="nested-bucket"
        )

        nested = _names(
            get_attribute(config).get_bucket(actor_id=actor_id, bucket="remote:abc")
        )
        flat = _names(
            get_attribute(config).get_bucket(actor_id=actor_id, bucket="remote")
        )

        assert (nested, flat) in (({"x"}, set()), (set(), {"abc:x"}))


class TestRemotePeerStoreIsolation:
    def test_delete_all_leaves_prefix_sibling_peer_intact(self, config, actor_id):
        """The regression the fix exists for: ending trust with peer ``abc``
        must not destroy peer ``abcd``'s dataset."""
        from actingweb.attribute import Attributes
        from actingweb.remote_storage import get_remote_bucket

        short_bucket = get_remote_bucket("abc", validate=False)
        long_bucket = get_remote_bucket("abcd", validate=False)

        db = get_attribute(config)
        assert db.set_attr(
            actor_id=actor_id, bucket=short_bucket, name="note", data={"v": 1}
        )
        assert db.set_attr(
            actor_id=actor_id, bucket=long_bucket, name="note", data={"v": 2}
        )

        Attributes(
            actor_id=actor_id, bucket=short_bucket, config=config
        ).delete_bucket()

        assert (
            _names(
                get_attribute(config).get_bucket(actor_id=actor_id, bucket=short_bucket)
            )
            == set()
        )
        survivor = _bucket(config, actor_id, long_bucket)
        assert _names(survivor) == {"note"}
        assert survivor["note"]["data"] == {"v": 2}
