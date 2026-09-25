"""``Attributes.loaded`` tells an empty bucket from a faulted read."""

from actingweb.attribute import Attributes
from tests.mcp_token_double import make_config


def test_loaded_before_and_after_reads() -> None:
    config, store = make_config()
    empty = Attributes(actor_id="a1", bucket="b", config=config)
    assert empty.loaded is False
    assert empty.get_bucket() == {}
    assert empty.loaded is True

    store.bucket("a1", "full")["x"] = {"data": 1}
    full = Attributes(actor_id="a1", bucket="full", config=config)
    assert full.get_bucket()
    assert full.loaded is True


def test_faulted_read_is_not_loaded() -> None:
    config, store = make_config()
    store.faulty_buckets.add("b")
    attrs = Attributes(actor_id="a1", bucket="b", config=config)
    assert attrs.get_bucket() == {}
    assert attrs.loaded is False
