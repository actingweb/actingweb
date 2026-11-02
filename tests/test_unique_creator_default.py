"""Creator uniqueness is on by default (3.16).

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

    def test_a_store_with_no_actors_gets_the_short_form(self) -> None:
        with (
            mock.patch(
                "actingweb.maintenance.unique_creators.missing_enforcement",
                return_value="the DynamoDB table x_creators does not exist",
            ),
            mock.patch(
                "actingweb.maintenance.unique_creators.no_actors", return_value=True
            ),
        ):
            with pytest.raises(UniqueCreatorNotReady) as raised:
                _check(_app())
        message = str(raised.value)
        assert "no actors yet" in message
        assert "enable --apply" in message
        assert "resolve --apply" not in message


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
