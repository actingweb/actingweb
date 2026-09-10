"""
Regression test for 3.14.5: ``Actor.create_verified_trust`` read
``data["verification_token"]`` from the peer's callback response, which
raised an uncaught ``KeyError`` (past the surrounding ``except ValueError``)
when the peer's JSON body omitted the key. Switched to ``data.get(...)`` and
routed through ``secret_digest_equals``, so a missing key is simply "not
verified", not a crash.
"""

from unittest.mock import MagicMock, patch

from actingweb.actor import Actor


def _actor_for_verify() -> Actor:
    actor = Actor.__new__(Actor)
    actor.id = "actor-1"
    actor.config = MagicMock()
    return actor


class TestVerificationTokenMissingFromPeerResponse:
    def test_missing_key_in_peer_response_does_not_raise_and_is_not_verified(self):
        actor = _actor_for_verify()

        peer_response = MagicMock()
        peer_response.status_code = 200
        # No "verification_token" key at all — the historical KeyError case.
        peer_response.content = b'{"verified": true, "approved": true}'

        mock_trust = MagicMock()
        mock_trust.create.return_value = True

        with (
            patch("actingweb.actor.requests.get", return_value=peer_response),
            patch("actingweb.actor.trust.Trust", return_value=mock_trust),
        ):
            result = actor.create_verified_trust(
                baseuri="https://peer.example.com/peeractor",
                peerid="peer-1",
                secret="s3cr3t",
                verification_token="expected-token",
                relationship="friend",
            )

        assert result is not False  # no exception propagated, flow completed
        _args, kwargs = mock_trust.create.call_args
        assert kwargs["verified"] is False

    def test_matching_token_is_verified(self):
        actor = _actor_for_verify()

        peer_response = MagicMock()
        peer_response.status_code = 200
        peer_response.content = b'{"verification_token": "expected-token"}'

        mock_trust = MagicMock()
        mock_trust.create.return_value = True

        with (
            patch("actingweb.actor.requests.get", return_value=peer_response),
            patch("actingweb.actor.trust.Trust", return_value=mock_trust),
        ):
            actor.create_verified_trust(
                baseuri="https://peer.example.com/peeractor",
                peerid="peer-1",
                secret="s3cr3t",
                verification_token="expected-token",
                relationship="friend",
            )

        _args, kwargs = mock_trust.create.call_args
        assert kwargs["verified"] is True

    def test_mismatched_token_is_not_verified(self):
        actor = _actor_for_verify()

        peer_response = MagicMock()
        peer_response.status_code = 200
        peer_response.content = b'{"verification_token": "wrong-token"}'

        mock_trust = MagicMock()
        mock_trust.create.return_value = True

        with (
            patch("actingweb.actor.requests.get", return_value=peer_response),
            patch("actingweb.actor.trust.Trust", return_value=mock_trust),
        ):
            actor.create_verified_trust(
                baseuri="https://peer.example.com/peeractor",
                peerid="peer-1",
                secret="s3cr3t",
                verification_token="expected-token",
                relationship="friend",
            )

        _args, kwargs = mock_trust.create.call_args
        assert kwargs["verified"] is False
