"""``actingweb.single_use``: the primitives both token stores share.

``consume_once`` is exercised through both stores
(``test_oauth2_spa_refresh_rotation.py``, ``test_mcp_refresh_rotation.py``,
``test_mcp_auth_code_single_use.py``); the throttle is pinned here.
"""

import time

from actingweb.single_use import PurgeThrottle


def test_first_claim_runs_then_throttles() -> None:
    throttle = PurgeThrottle()
    assert throttle.claim(3600) is True
    assert throttle.claim(3600) is False


def test_claim_runs_again_after_the_interval() -> None:
    throttle = PurgeThrottle()
    throttle.last_attempt = time.time() - 3601
    assert throttle.claim(3600) is True
    assert throttle.claim(3600) is False


def test_throttles_are_independent() -> None:
    import actingweb.oauth2_server.token_manager as mcp
    import actingweb.oauth_session as spa

    assert spa._purge_throttle is not mcp._mcp_purge_throttle
