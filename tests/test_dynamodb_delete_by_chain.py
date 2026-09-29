"""``DbAttribute.delete_by_chain`` on DynamoDB, with the query stubbed.

The scan is routine now (every SPA logout and revoke), so its shape is
pinned: the bucket delimiter, raising instead of skipping, the row-count
WARNING and the deferred anchor. The real backend is covered by
``tests/integration/test_spa_chain_revocation_backend.py``.
"""

import logging
from typing import Any

import pytest

from actingweb.db.dynamodb import attribute as ddb

PARTITION = "_actingweb_oauth2"


class _Row:
    def __init__(self, bucket: str, name: str, chain: str | None, log: list[str]):
        self.bucket = bucket
        self.name = name
        self.data = {"chain_id": chain} if chain else {}
        self._log = log

    def delete(self) -> None:
        self._log.append(self.name)


def _stub_query(
    monkeypatch: pytest.MonkeyPatch, rows_by_prefix: dict[str, list[_Row]]
) -> list[str]:
    """Replace ``Attribute.query``; returns the begins-with values it saw."""
    seen: list[str] = []

    def query(_actor: str, condition: Any, **_kw: Any) -> list[_Row]:
        prefix = condition.values[1].value["S"]
        seen.append(prefix)
        # Emulate DynamoDB: only rows whose key starts with the prefix.
        return [
            r
            for rows in rows_by_prefix.values()
            for r in rows
            if f"{r.bucket}:{r.name}".startswith(prefix)
        ]

    monkeypatch.setattr(ddb.Attribute, "query", staticmethod(query))
    return seen


def test_the_query_uses_the_bucket_delimiter_so_a_sibling_bucket_is_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deleted: list[str] = []
    sibling = _Row("spa_access_tokens_x", "sib", "c1", deleted)
    mine = _Row("spa_access_tokens", "mine", "c1", deleted)
    seen = _stub_query(monkeypatch, {"a": [mine, sibling]})

    count = ddb.DbAttribute.delete_by_chain(PARTITION, ["spa_access_tokens"], "c1")

    assert seen == ["spa_access_tokens:"]
    assert count == 1
    assert deleted == ["mine"]


def test_the_anchor_is_deleted_last(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []
    rows = [
        _Row("spa_refresh_tokens", "anchor", "c1", deleted),
        _Row("spa_refresh_tokens", "other", "c1", deleted),
        _Row("spa_access_tokens", "acc", "c1", deleted),
        _Row("spa_access_tokens", "unrelated", "c2", deleted),
    ]
    _stub_query(monkeypatch, {"a": rows})

    count = ddb.DbAttribute.delete_by_chain(
        PARTITION,
        ["spa_refresh_tokens", "spa_access_tokens"],
        "c1",
        defer_name="anchor",
    )

    assert count == 3
    assert deleted[-1] == "anchor"
    assert "unrelated" not in deleted


def test_a_failing_query_raises_instead_of_skipping_the_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_a: Any, **_k: Any) -> list[Any]:
        raise RuntimeError("cannot build the query")

    monkeypatch.setattr(ddb.Attribute, "query", staticmethod(boom))
    with pytest.raises(RuntimeError):
        ddb.DbAttribute.delete_by_chain(PARTITION, ["spa_access_tokens"], "c1")


def test_a_bucket_past_the_row_budget_logs_one_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    deleted: list[str] = []
    rows = [
        _Row("spa_access_tokens", f"t{i}", None, deleted)
        for i in range(ddb.CHAIN_SCAN_WARN_ROWS + 1)
    ]
    _stub_query(monkeypatch, {"a": rows})

    with caplog.at_level(logging.WARNING, logger=ddb.logger.name):
        ddb.DbAttribute.delete_by_chain(PARTITION, ["spa_access_tokens"], "c1")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "spa_access_tokens" in warnings[0].getMessage()
    assert "GSI" in warnings[0].getMessage()


def test_a_bucket_within_the_budget_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    deleted: list[str] = []
    rows = [_Row("spa_access_tokens", f"t{i}", None, deleted) for i in range(10)]
    _stub_query(monkeypatch, {"a": rows})

    with caplog.at_level(logging.WARNING, logger=ddb.logger.name):
        ddb.DbAttribute.delete_by_chain(PARTITION, ["spa_access_tokens"], "c1")

    assert not caplog.records


def test_ttl_deadline_adds_the_clock_skew_buffer() -> None:
    import time

    from actingweb.constants import TTL_CLOCK_SKEW_BUFFER

    before = int(time.time())
    stamp = ddb.ttl_deadline(100)
    assert (
        before + 100 + TTL_CLOCK_SKEW_BUFFER
        <= stamp
        <= before + 102 + TTL_CLOCK_SKEW_BUFFER
    )
