from typing import Any, Dict

from actingweb.interface.trust_manager import TrustManager


class FakeConfig:
    def __init__(self) -> None:
        self.root = "https://example.com/"

    def new_token(self) -> str:
        return "secret-token"


class FakeStore(dict):
    pass


class FakeCoreActor:
    def __init__(self) -> None:
        self.id = "actor_1"
        self.config = FakeConfig()
        self.store: Dict[str, Any] = FakeStore()
        self._trusts: Dict[str, Dict[str, Any]] = {}

    # Minimal API used by TrustManager
    def get_trust_relationships(self, peerid: str = "", relationship: str = "", trust_type: str = ""):
        if peerid:
            if peerid in self._trusts:
                return [self._trusts[peerid]]
            return []
        return list(self._trusts.values())

    def get_trust_relationship(self, peerid: str):
        return self._trusts.get(peerid)


def test_create_or_update_oauth_trust_creates_and_stores_tokens(monkeypatch):
    actor = FakeCoreActor()
    tm = TrustManager(actor)

    # Stub DbTrust.create/get/modify used inside TrustManager
    class FakeDbTrust:
        def __init__(self) -> None:
            self._db: Dict[str, Dict[str, Any]] = {}

        def get(self, actor_id: str, peerid: str):
            return self._db.get((actor_id, peerid))

        def create(self, **kwargs):
            key = (kwargs["actor_id"], kwargs["peerid"])  # type: ignore[index]
            self._db[key] = kwargs  # type: ignore[assignment]
            # also reflect in the actor cache for subsequent reads
            actor._trusts[kwargs["peerid"]] = kwargs  # type: ignore[index]
            return True

        def modify(self, **kwargs):
            return True

    monkeypatch.setitem(__import__("sys").modules, "actingweb.db_dynamodb.db_trust", type("M", (), {"DbTrust": FakeDbTrust}))

    oauth_tokens = {"access_token": "at", "refresh_token": "rt", "expires_at": 1234, "token_type": "Bearer"}
    ok = tm.create_or_update_oauth_trust(
        email="user@example.com",
        trust_type="mcp_client",
        oauth_tokens=oauth_tokens,
        established_via="oauth2",
    )
    assert ok is True

    # Unified behavior: OAuth2-established trusts are prefixed with 'oauth2:'
    peer_id = "oauth2:user_at_example_dot_com"
    rel = tm.get_relationship(peer_id)
    assert rel is not None
    assert rel.relationship == "mcp_client"
    # token stored
    token_key = f"oauth_tokens:{peer_id}"
    assert actor.store[token_key]["access_token"] == "at"
