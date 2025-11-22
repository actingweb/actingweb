from typing import Any

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
        self.store: dict[str, Any] = FakeStore()
        self._trusts: dict[str, dict[str, Any]] = {}

    # Minimal API used by TrustManager
    def get_trust_relationships(
        self, peerid: str = "", relationship: str = "", trust_type: str = ""
    ):
        if peerid:
            if peerid in self._trusts:
                return [self._trusts[peerid]]
            return []
        return list(self._trusts.values())

    def get_trust_relationship(self, peerid: str):
        return self._trusts.get(peerid)


def canonical_via(via: str | None) -> str | None:
    if via is None:
        return None
    lowered = via.lower()
    if lowered.startswith("oauth"):
        return "oauth"
    if lowered in {"trust", "subscription", "mcp"}:
        return lowered
    return via


def test_create_or_update_oauth_trust_creates_and_stores_tokens(monkeypatch):
    actor = FakeCoreActor()
    tm = TrustManager(actor)  # type: ignore[arg-type]

    # Stub DbTrust.create/get/modify used inside TrustManager
    class FakeDbTrust:
        def __init__(self) -> None:
            self._db: dict[tuple[str, str], dict[str, Any]] = {}
            self.handle = None

        def get(self, actor_id: str, peerid: str):
            record = self._db.get((actor_id, peerid))
            if record is None:
                self.handle = None
                return None
            self.handle = type("Handle", (), {})()
            for key, value in record.items():
                setattr(self.handle, key, value)
            return record

        def create(self, **kwargs):
            key = (kwargs["actor_id"], kwargs["peerid"])  # type: ignore[index]
            kwargs.setdefault("last_connected_at", kwargs.get("last_accessed"))
            established = kwargs.get("established_via")
            if established and not kwargs.get("last_connected_via"):
                kwargs["last_connected_via"] = canonical_via(established)
            self._db[key] = kwargs  # type: ignore[assignment]
            # also reflect in the actor cache for subsequent reads
            actor._trusts[kwargs["peerid"]] = kwargs  # type: ignore[index]
            self.get(kwargs["actor_id"], kwargs["peerid"])  # type: ignore[index]
            return True

        def modify(self, **kwargs):
            if not self.handle:
                return True
            db_key = (self.handle.id, self.handle.peerid)  # type: ignore[arg-type,union-attr,attr-defined,return-value]
            for key, value in kwargs.items():
                if key == "last_connected_via":
                    value = canonical_via(value)
                    kwargs[key] = value
                setattr(self.handle, key, value)
            if db_key in self._db:
                self._db[db_key].update(kwargs)
                actor._trusts[self._db[db_key]["peerid"]].update(kwargs)  # type: ignore[index]
            return True

    monkeypatch.setitem(
        __import__("sys").modules,
        "actingweb.db_dynamodb.db_trust",
        type("M", (), {"DbTrust": FakeDbTrust}),
    )

    oauth_tokens = {
        "access_token": "at",
        "refresh_token": "rt",
        "expires_at": 1234,
        "token_type": "Bearer",
    }
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
    assert rel.created_at is not None
    assert rel.last_connected_at is not None
    assert rel.established_via == "oauth2"
    assert rel.last_connected_via == "oauth"
    # token stored
    token_key = f"oauth_tokens:{peer_id}"
    assert actor.store[token_key]["access_token"] == "at"
