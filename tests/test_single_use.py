"""``actingweb.single_use``: the primitives both token stores share.

``consume_once`` is exercised through both stores
(``test_oauth2_spa_refresh_rotation.py``, ``test_mcp_refresh_rotation.py``,
``test_mcp_auth_code_single_use.py``); the throttle is pinned here.
"""

import time

import pytest

from actingweb.single_use import PurgeThrottle


def test_first_claim_runs_then_throttles() -> None:
    throttle = PurgeThrottle()
    assert throttle.claim(3600) is True
    assert throttle.claim(3600) is False


def test_claim_runs_again_after_the_interval() -> None:
    throttle = PurgeThrottle()
    throttle.last_attempt = time.monotonic() - 3601
    assert throttle.claim(3600) is True
    assert throttle.claim(3600) is False


def test_a_wall_clock_step_back_does_not_stop_the_purge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    throttle = PurgeThrottle()
    assert throttle.claim(3600) is True
    real = time.monotonic
    monkeypatch.setattr(time, "time", lambda: 0.0)  # the wall clock jumps back
    monkeypatch.setattr(time, "monotonic", lambda: real() + 3601)
    assert throttle.claim(3600) is True


def test_throttles_are_independent() -> None:
    import actingweb.oauth2_server.token_manager as mcp
    import actingweb.oauth_session as spa

    assert spa._purge_throttle is not mcp._mcp_purge_throttle


# ---------------------------------------------------------------------------
# revoke_chain_confirmed: the chain-revocation core both stores share
# ---------------------------------------------------------------------------

from actingweb.single_use import StoreFault, revoke_chain_confirmed  # noqa: E402
from tests.mcp_token_double import make_config  # noqa: E402

_PARTITION = "_partition"
_ACCESS = "access_bucket"
_REFRESH = "refresh_bucket"


def _seed_chain():  # type: ignore[no-untyped-def]
    config, store = make_config()
    store.bucket(_PARTITION, _ACCESS)["access-1"] = {"data": {"chain_id": "c1"}}
    store.bucket(_PARTITION, _REFRESH)["refresh-1"] = {"data": {"chain_id": "c1"}}
    store.bucket(_PARTITION, _REFRESH)["other-1"] = {"data": {"chain_id": "c2"}}
    return config, store


def _revoke(config, anchor):  # type: ignore[no-untyped-def]
    return revoke_chain_confirmed(
        config, _PARTITION, [_ACCESS, _REFRESH], "c1", anchor=anchor
    )


def test_revoke_chain_confirmed_deletes_the_chain_and_only_the_chain() -> None:
    config, store = _seed_chain()
    assert _revoke(config, (_REFRESH, "refresh-1")) == 2
    assert store.names(_PARTITION, _ACCESS) == set()
    assert store.names(_PARTITION, _REFRESH) == {"other-1"}


def test_revoke_chain_confirmed_zero_with_the_anchor_present_is_a_fault() -> None:
    config, store = _seed_chain()
    store.chain_delete_fault = "zero"
    with pytest.raises(StoreFault):
        _revoke(config, (_REFRESH, "refresh-1"))
    assert "refresh-1" in store.names(_PARTITION, _REFRESH)


def test_revoke_chain_confirmed_zero_with_the_anchor_gone_is_done() -> None:
    config, store = _seed_chain()
    store.chain_delete_fault = "zero"
    store.chain_delete_hook = lambda: store.bucket(_PARTITION, _REFRESH).pop(
        "refresh-1"
    )
    assert _revoke(config, (_REFRESH, "refresh-1")) == 0


def test_revoke_chain_confirmed_zero_with_an_unreadable_anchor_is_a_fault() -> None:
    config, store = _seed_chain()
    store.chain_delete_fault = "zero"
    store.chain_delete_hook = lambda: store.faulty_buckets.add(_REFRESH)
    with pytest.raises(StoreFault):
        _revoke(config, (_REFRESH, "refresh-1"))


@pytest.mark.parametrize("fault", ["raise", "partial"])
def test_revoke_chain_confirmed_a_raising_delete_is_a_fault(fault: str) -> None:
    config, store = _seed_chain()
    store.chain_delete_fault = fault
    with pytest.raises(StoreFault):
        _revoke(config, (_REFRESH, "refresh-1"))
    # The anchor is deleted last, so it is what survives a partial delete.
    assert "refresh-1" in store.names(_PARTITION, _REFRESH)


def test_revoke_chain_confirmed_without_an_anchor_returns_zero_on_a_zero() -> None:
    config, store = _seed_chain()
    store.chain_delete_fault = "zero"
    assert _revoke(config, None) == 0
