"""``actingweb.maintenance.mark_actors_vouched``: the operator's opt-out of the 3.16
clean-slate adoption for actors known to be legitimate."""

from actingweb.actor import Actor
from actingweb.maintenance import mark_actors_vouched as script
from tests._adoption_helpers import (
    aid,
    create_core_actor,
    istore,
    make_config,
    uuid_email,
)


def _marker(config, actor_id: str):
    return istore(Actor(actor_id=actor_id, config=config)).auth_method


class TestMarkActors:
    def test_dry_run_writes_nothing(self) -> None:
        config = make_config()
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        counts = script.mark_actors(config, creator=creator, dry_run=True)
        assert counts["marked"] == 1
        assert _marker(config, aid(legacy)) is None

    def test_marks_unmarked_and_skips_vouched_and_factory(self) -> None:
        config = make_config()
        legacy_creator = uuid_email()
        legacy = create_core_actor(config, legacy_creator, auth_method=None)
        script.mark_actors(config, creator=legacy_creator, marker="operator")
        assert _marker(config, aid(legacy)) == "operator"

        for method in ("app", "factory"):
            creator = uuid_email()
            actor = create_core_actor(config, creator, auth_method=method)
            counts = script.mark_actors(config, creator=creator)
            assert counts["marked"] == 0 and counts["skipped"] == 1
            assert _marker(config, aid(actor)) == method

    def test_include_factory_remarks_factory_actors(self) -> None:
        config = make_config()
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="factory")
        script.mark_actors(config, creator=creator, include_factory=True)
        assert _marker(config, aid(actor)) == "operator"

    def test_creator_filter_restricts_the_run(self) -> None:
        config = make_config()
        mine, other = uuid_email(), uuid_email()
        a = create_core_actor(config, mine, auth_method=None)
        b = create_core_actor(config, other, auth_method=None)
        script.mark_actors(config, creator=mine)
        assert _marker(config, aid(a)) == "operator"
        assert _marker(config, aid(b)) is None

    def test_start_after_skips_earlier_ids(self) -> None:
        config = make_config()
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method=None)
        counts = script.mark_actors(config, creator=creator, start_after="z" * 40)
        assert counts["scanned"] == 0
        assert _marker(config, aid(actor)) is None
