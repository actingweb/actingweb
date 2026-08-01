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

import ast
import pathlib

import actingweb.peer_capabilities as peer_capabilities
import actingweb.peer_permissions as peer_permissions
import actingweb.peer_profile as peer_profile
import actingweb.permission_evaluator as permission_evaluator
import actingweb.trust_permissions as trust_permissions
import actingweb.trust_type_registry as trust_type_registry
from actingweb import config as config_class
from actingweb.oauth2_server import client_registry, oauth2_server, state_manager
from actingweb.oauth2_server import token_manager as token_manager_mod


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

    def test_mcp_client_registry_rebinds(self) -> None:
        client_registry._client_registry = None
        client_registry._client_registry_config = None

        cfg_a = _make_config("a.example.com")
        cfg_b = _make_config("b.example.com")

        reg_a = client_registry.get_mcp_client_registry(cfg_a)
        reg_b = client_registry.get_mcp_client_registry(cfg_b)

        assert reg_b is not reg_a, (
            "client registration would write trust rows to the first "
            "application's database backend"
        )
        assert client_registry.get_mcp_client_registry(cfg_b) is reg_b

    def test_token_manager_rebinds(self) -> None:
        token_manager_mod._token_manager = None
        token_manager_mod._token_manager_config = None

        cfg_a = _make_config("a.example.com")
        cfg_b = _make_config("b.example.com")

        tm_a = token_manager_mod.get_actingweb_token_manager(cfg_a)
        tm_b = token_manager_mod.get_actingweb_token_manager(cfg_b)

        assert tm_b is not tm_a
        assert token_manager_mod.get_actingweb_token_manager(cfg_b) is tm_b

    def test_peer_profile_store_rebinds(self) -> None:
        peer_profile._profile_store = None
        peer_profile._profile_store_config = None

        cfg_a = _make_config("a.example.com")
        cfg_b = _make_config("b.example.com")

        store_a = peer_profile.get_peer_profile_store(cfg_a)
        store_b = peer_profile.get_peer_profile_store(cfg_b)

        assert store_b is not store_a
        assert peer_profile.get_peer_profile_store(cfg_b) is store_b

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

    def test_registration_and_tokens_do_not_keep_an_earlier_apps_backend(
        self,
    ) -> None:
        """Registration must write where the second application reads.

        ``get_mcp_client_registry`` is the *write* side of the crossover:
        it is what dynamic client registration uses to create the trust row
        that MCP request authorization later looks for.
        """
        client_registry._client_registry = None
        client_registry._client_registry_config = None
        token_manager_mod._token_manager = None
        token_manager_mod._token_manager_config = None

        dynamo_cfg = config_class.Config(
            fqdn="dynamo.example.com", proto="https://", database="dynamodb"
        )
        postgres_cfg = config_class.Config(
            fqdn="postgres.example.com", proto="https://", database="postgresql"
        )

        client_registry.get_mcp_client_registry(dynamo_cfg)
        registry = client_registry.get_mcp_client_registry(postgres_cfg)

        # Before the fix this was the DynamoDB trust module, so registration
        # wrote the trust row to a different store than resolution read.
        assert registry.config.DbTrust is postgres_cfg.DbTrust
        assert registry.config.DbTrust is not dynamo_cfg.DbTrust

        token_manager_mod.get_actingweb_token_manager(dynamo_cfg)
        manager = token_manager_mod.get_actingweb_token_manager(postgres_cfg)
        assert manager.config.DbTrust is postgres_cfg.DbTrust

    def test_oauth2_server_rebinds_everything_it_composes(self) -> None:
        """Rebinding the wrapper is not enough -- its children must rebind too.

        ``ActingWebOAuth2Server.__init__`` pulls three further singletons.
        Checking only ``server.config`` passed for the entire time those
        three stayed bound to the first application, which is how the
        crossover survived the first round of fixes.
        """
        oauth2_server._oauth2_server = None
        oauth2_server._oauth2_server_config = None
        client_registry._client_registry = None
        client_registry._client_registry_config = None
        token_manager_mod._token_manager = None
        token_manager_mod._token_manager_config = None
        state_manager._state_manager = None
        state_manager._state_manager_config = None

        cfg_a = _make_config("a.example.com")
        cfg_b = _make_config("b.example.com")

        oauth2_server.get_actingweb_oauth2_server(cfg_a)
        server = oauth2_server.get_actingweb_oauth2_server(cfg_b)

        assert server.config is cfg_b
        assert server.client_registry.config is cfg_b
        assert server.token_manager.config is cfg_b
        assert server.state_manager.config is cfg_b


class TestNoUnguardedConfigBoundSingletons:
    """A structural guard, so batch four cannot happen quietly.

    Three separate rounds of this defect were found by tripping over its
    symptoms. The shape is mechanical and so is the check: a function that
    takes a ``config`` and caches into a module global must consult that
    ``config`` before returning the cached value.
    """

    @staticmethod
    def _module_globals(tree: ast.Module) -> set[str]:
        names: set[str] = set()
        for node in tree.body:
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign)
                else []
            )
            names.update(t.id for t in targets if isinstance(t, ast.Name))
        return names

    @staticmethod
    def _compares_against_the_config_argument(fn: ast.AST) -> bool:
        """True if the body contains ``<something> is/is not config``.

        Deliberately narrow: it must compare against the parameter named
        ``config`` itself. A bare ``if self.config is not None`` does not
        count, because it does not distinguish one application's config
        from another's.
        """
        for node in ast.walk(fn):
            if not isinstance(node, ast.Compare):
                continue
            if not any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
                continue
            if any(
                isinstance(c, ast.Name) and c.id == "config" for c in node.comparators
            ):
                return True
        return False

    def test_every_config_taking_singleton_getter_guards_on_its_config(self) -> None:
        package = pathlib.Path(__file__).resolve().parent.parent / "actingweb"
        offenders: list[str] = []

        for path in sorted(package.rglob("*.py")):
            tree = ast.parse(path.read_text())
            module_globals = self._module_globals(tree)

            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
                if "config" not in params:
                    continue
                declared = {
                    name
                    for node in ast.walk(fn)
                    if isinstance(node, ast.Global)
                    for name in node.names
                }
                if not declared & module_globals:
                    continue
                if not self._compares_against_the_config_argument(fn):
                    offenders.append(
                        f"{path.relative_to(package.parent)}:{fn.lineno} {fn.name} "
                        f"caches into {sorted(declared & module_globals)}"
                    )

        assert not offenders, (
            "These functions cache a module-global built from `config` but never "
            "check whether they were handed a different one, so a second "
            "ActingWeb application in the same interpreter is served the first "
            "application's instance -- and, if the two use different database "
            "backends, writes and reads land in different stores:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_detector_itself_still_has_teeth(self) -> None:
        """A tripwire that silently stops tripping is worse than none.

        The check above passing is only meaningful if it would still fail on
        the shape it is meant to catch, so feed it that shape directly.
        """
        bad = ast.parse(
            "_thing = None\n"
            "def get_thing(config):\n"
            "    global _thing\n"
            "    if _thing is None:\n"
            "        _thing = Thing(config)\n"
            "    return _thing\n"
        )
        fn = next(n for n in ast.walk(bad) if isinstance(n, ast.FunctionDef))
        assert "_thing" in self._module_globals(bad)
        assert not self._compares_against_the_config_argument(fn)

        good = ast.parse(
            "_thing = None\n"
            "_thing_config = None\n"
            "def get_thing(config):\n"
            "    global _thing, _thing_config\n"
            "    if _thing is None or _thing_config is not config:\n"
            "        _thing = Thing(config)\n"
            "        _thing_config = config\n"
            "    return _thing\n"
        )
        fn = next(n for n in ast.walk(good) if isinstance(n, ast.FunctionDef))
        assert self._compares_against_the_config_argument(fn)
