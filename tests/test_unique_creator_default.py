"""Creator uniqueness is on by default (4.0).

A deployment with duplicate creators refuses to start until it has run
``actingweb-unique-creators`` or opts out with ``with_unique_creator(False)``;
the duplicate-tolerant adoption code survives for the opt-out. See
``thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md`` (D4).
"""

from actingweb.config import Config
from actingweb.interface import ActingWebApp


def test_config_defaults_unique_creator_on() -> None:
    assert Config().unique_creator is True


def test_app_defaults_unique_creator_on() -> None:
    app = ActingWebApp(aw_type="urn:actingweb:test:default", fqdn="x.example.com")
    assert app.get_config().unique_creator is True


def test_opting_out_turns_it_off() -> None:
    app = ActingWebApp(
        aw_type="urn:actingweb:test:default", fqdn="x.example.com"
    ).with_unique_creator(False)
    assert app.get_config().unique_creator is False


# -- the readiness check under the default ------------------------------------

import os  # noqa: E402
from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from actingweb.interface import UniqueCreatorNotReady  # noqa: E402


def _app() -> ActingWebApp:
    return ActingWebApp(aw_type="urn:actingweb:test:default", fqdn="x.example.com")


def _check(app: ActingWebApp) -> None:
    with mock.patch.object(ActingWebApp, "_prewarm_dynamodb_tables"):
        app.check_ready()


@pytest.mark.usefixtures("real_unique_probe")
class TestDefaultReadiness:
    def test_opting_out_reads_nothing(self) -> None:
        app = _app().with_unique_creator(False)
        with mock.patch(
            "actingweb.maintenance.unique_creators.missing_enforcement"
        ) as spy:
            _check(app)
        spy.assert_not_called()

    def test_the_default_refuses_with_the_commands_and_the_opt_out(self) -> None:
        with (
            mock.patch(
                "actingweb.maintenance.unique_creators.missing_enforcement",
                return_value="the DynamoDB table x_creators is not backfilled",
            ),
            mock.patch(
                "actingweb.maintenance.unique_creators.no_actors", return_value=False
            ),
        ):
            with pytest.raises(UniqueCreatorNotReady) as raised:
                _check(_app())
        message = str(raised.value)
        for needle in (
            "report",
            "resolve --apply",
            "enable --apply",
            "with_unique_creator(False)",
        ):
            assert needle in message

    def test_an_empty_store_enables_itself(self) -> None:
        """AC-13 (4.0): no user actors, so nothing to resolve; the enable
        step is patched (the shared unit store holds deliberate duplicates)."""
        answers = iter(["the DynamoDB table x_creators does not exist", None])
        with (
            mock.patch(
                "actingweb.maintenance.unique_creators.missing_enforcement",
                side_effect=lambda config: next(answers),
            ),
            mock.patch(
                "actingweb.maintenance.unique_creators.no_actors", return_value=True
            ),
            mock.patch(
                "actingweb.maintenance.unique_creators.enable_empty_store"
            ) as enable,
        ):
            _check(_app())
        enable.assert_called_once()

    def test_a_store_with_a_user_actor_still_refuses(self) -> None:
        """AC-15."""
        with (
            mock.patch(
                "actingweb.maintenance.unique_creators.missing_enforcement",
                return_value="the DynamoDB table x_creators does not exist",
            ),
            mock.patch(
                "actingweb.maintenance.unique_creators.no_actors", return_value=False
            ),
            mock.patch(
                "actingweb.maintenance.unique_creators.enable_empty_store"
            ) as enable,
        ):
            with pytest.raises(UniqueCreatorNotReady) as raised:
                _check(_app())
        enable.assert_not_called()
        assert "resolve --apply" in str(raised.value)

    def test_the_default_prefix_does_not_self_enable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-48: a wrong prefix with table auto-creation must not start an
        empty store."""
        monkeypatch.delenv("AWS_DB_PREFIX", raising=False)
        with mock.patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(
                aw_type="urn:actingweb:test:default",
                fqdn="x.example.com",
                database="dynamodb",
            )
        with (
            mock.patch(
                "actingweb.maintenance.unique_creators.missing_enforcement",
                return_value="the DynamoDB table x_creators does not exist",
            ),
            mock.patch(
                "actingweb.maintenance.unique_creators.no_actors", return_value=True
            ),
            mock.patch(
                "actingweb.maintenance.unique_creators.enable_empty_store"
            ) as enable,
        ):
            with pytest.raises(UniqueCreatorNotReady) as raised:
                _check(app)
        enable.assert_not_called()
        message = str(raised.value)
        assert "AWS_DB_PREFIX" in message and "demo_actingweb" in message
        assert "enable --apply" in message

    def test_a_failed_index_build_refuses(self) -> None:
        """AC-14: a role that may not create the index, or a build that
        fails, refuses with the command."""
        with mock.patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(
                aw_type="urn:actingweb:test:default",
                fqdn="x.example.com",
                database="postgresql",
            )
        with (
            mock.patch(
                "actingweb.maintenance.unique_creators.missing_enforcement",
                return_value="the PostgreSQL index ux_actors_creator does not exist",
            ),
            mock.patch(
                "actingweb.maintenance.unique_creators.no_actors", return_value=True
            ),
            mock.patch(
                "actingweb.maintenance.unique_creators.enable_empty_store",
                side_effect=RuntimeError("permission denied for schema public"),
            ),
            mock.patch.object(ActingWebApp, "_check_property_lookup_ready"),
            mock.patch.object(ActingWebApp, "_check_attribute_schema_ready"),
            mock.patch.object(ActingWebApp, "_check_email_as_creator_ready"),
        ):
            with pytest.raises(UniqueCreatorNotReady) as raised:
                _check(app)
        assert "actingweb-unique-creators enable --apply" in str(raised.value)


@pytest.mark.skipif(
    os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb", reason="DynamoDB"
)
class TestNoDescribeTable:
    def test_the_probe_makes_no_describe_table_call(self) -> None:
        from actingweb.maintenance import unique_creators

        with mock.patch("pynamodb.models.Model.exists") as exists:
            outcome = unique_creators.missing_enforcement(Config(database="dynamodb"))
            assert unique_creators.backfill_complete() in (True, False)
        exists.assert_not_called()
        # Absent or not backfilled on the shared test store, never a crash.
        assert outcome is None or "creators" in outcome

    def test_a_missing_table_is_still_reported_as_absence(self) -> None:
        from pynamodb.exceptions import GetError

        from actingweb.db.dynamodb.creator import Creator
        from actingweb.maintenance import unique_creators

        class _Cause(Exception):
            response = {"Error": {"Code": "ResourceNotFoundException"}}

        err = GetError("Failed to get item")
        err.cause = _Cause()  # type: ignore[attr-defined]
        with mock.patch.object(Creator, "get", side_effect=err):
            assert "does not exist" in (
                unique_creators.missing_enforcement(Config(database="dynamodb")) or ""
            )
            assert unique_creators.backfill_complete() is False
