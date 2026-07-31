"""Config-bound module singletons must rebind when handed a different config.

Regression tests for a defect found via PR #117's CI: every one of these
getters takes a ``config`` argument but, once built, ignored it forever --
they bound to the *first* config the process ever passed and returned that
instance to every later caller.

That is wrong whenever more than one ActingWeb application exists in one
interpreter, which the test suite does routinely and which a host process
embedding two ActingWeb apps would do too. The concrete failure it produced:
``get_actingweb_oauth2_server()`` handed a PostgreSQL-configured application
an OAuth2 server still bound to an earlier DynamoDB-configured one, so MCP
dynamic client registration wrote its trust row to one database backend while
trust resolution read the other. The read came back empty, and once missing
trust became fail-closed that surfaced as ``-32003`` on every request from a
freshly registered client.
"""

import actingweb.peer_capabilities as peer_capabilities
import actingweb.peer_permissions as peer_permissions
import actingweb.permission_evaluator as permission_evaluator
import actingweb.trust_permissions as trust_permissions
import actingweb.trust_type_registry as trust_type_registry
from actingweb import config as config_class
from actingweb.oauth2_server import oauth2_server


def _make_config(fqdn: str) -> config_class.Config:
    return config_class.Config(fqdn=fqdn, proto="https://", database="dynamodb")


class TestSingletonsRebindOnDifferentConfig:
    """Each getter must return an instance built from the config it was given."""

    def test_oauth2_server_rebinds(self) -> None:
        oauth2_server._oauth2_server = None
        oauth2_server._oauth2_server_config = None

        cfg_a = _make_config("a.example.com")
        cfg_b = _make_config("b.example.com")

        server_a = oauth2_server.get_actingweb_oauth2_server(cfg_a)
        assert server_a.config is cfg_a

        server_b = oauth2_server.get_actingweb_oauth2_server(cfg_b)
        assert server_b.config is cfg_b, (
            "second application was served the first application's OAuth2 server"
        )
        assert server_b is not server_a

        # Same config again must NOT rebuild -- these are singletons for a reason.
        assert oauth2_server.get_actingweb_oauth2_server(cfg_b) is server_b

    def test_permission_evaluator_rebinds(self) -> None:
        permission_evaluator._permission_evaluator = None
        permission_evaluator._permission_evaluator_config = None

        cfg_a = _make_config("a.example.com")
        cfg_b = _make_config("b.example.com")

        # PermissionEvaluator builds on the trust permission store, which
        # refuses to lazily initialize.
        trust_permissions.initialize_trust_permission_store(cfg_a)

        ev_a = permission_evaluator.get_permission_evaluator(cfg_a)
        ev_b = permission_evaluator.get_permission_evaluator(cfg_b)

        assert ev_b is not ev_a
        assert permission_evaluator.get_permission_evaluator(cfg_b) is ev_b

    def test_trust_permission_store_rebinds(self) -> None:
        trust_permissions._permission_store = None
        trust_permissions._permission_store_config = None

        cfg_a = _make_config("a.example.com")
        cfg_b = _make_config("b.example.com")

        trust_permissions.initialize_trust_permission_store(cfg_a)
        store_a = trust_permissions.get_trust_permission_store(cfg_a)
        store_b = trust_permissions.get_trust_permission_store(cfg_b)

        assert store_b is not store_a, (
            "second application was served the first application's permission store"
        )
        assert trust_permissions.get_trust_permission_store(cfg_b) is store_b

    def test_trust_type_registry_rebinds(self) -> None:
        trust_type_registry._registry = None
        trust_type_registry._registry_config = None

        cfg_a = _make_config("a.example.com")
        cfg_b = _make_config("b.example.com")

        reg_a = trust_type_registry.get_registry(cfg_a)
        reg_b = trust_type_registry.get_registry(cfg_b)

        assert reg_b is not reg_a
        assert trust_type_registry.get_registry(cfg_b) is reg_b

    def test_peer_permission_store_rebinds(self) -> None:
        peer_permissions._permission_store = None
        peer_permissions._permission_store_config = None

        cfg_a = _make_config("a.example.com")
        cfg_b = _make_config("b.example.com")

        store_a = peer_permissions.get_peer_permission_store(cfg_a)
        store_b = peer_permissions.get_peer_permission_store(cfg_b)

        assert store_b is not store_a
        assert peer_permissions.get_peer_permission_store(cfg_b) is store_b

    def test_capabilities_store_rebinds(self) -> None:
        peer_capabilities._capabilities_store = None
        peer_capabilities._capabilities_store_config = None

        cfg_a = _make_config("a.example.com")
        cfg_b = _make_config("b.example.com")

        store_a = peer_capabilities.get_cached_capabilities_store(cfg_a)
        store_b = peer_capabilities.get_cached_capabilities_store(cfg_b)

        assert store_b is not store_a
        assert peer_capabilities.get_cached_capabilities_store(cfg_b) is store_b


class TestBackendCrossoverIsTheRealRisk:
    """The failure mode that motivated the fix, asserted directly."""

    def test_oauth2_server_does_not_keep_an_earlier_apps_database_backend(
        self,
    ) -> None:
        oauth2_server._oauth2_server = None
        oauth2_server._oauth2_server_config = None

        dynamo_cfg = config_class.Config(
            fqdn="dynamo.example.com", proto="https://", database="dynamodb"
        )
        postgres_cfg = config_class.Config(
            fqdn="postgres.example.com", proto="https://", database="postgresql"
        )

        oauth2_server.get_actingweb_oauth2_server(dynamo_cfg)
        server = oauth2_server.get_actingweb_oauth2_server(postgres_cfg)

        # Before the fix this was the DynamoDB config, so client registration
        # wrote trust rows to a different store than trust resolution read.
        assert server.config is postgres_cfg
        assert server.config.DbTrust is postgres_cfg.DbTrust
        assert server.config.DbTrust is not dynamo_cfg.DbTrust
