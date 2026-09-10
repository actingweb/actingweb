"""
Tests for the duplicate-creator WARNING added to ``Actor.get_from_creator``
in 3.14.5: when more than one actor shares a creator (possible with
``unique_creator`` disabled), a WARNING is logged with the lookup creator
and the sorted candidate ids before falling back to the existing
lowest-id-wins selection. No new DB cost — the candidates are already in
memory from the ``get_by_creator`` call.
"""

import logging
from unittest.mock import MagicMock, patch

from actingweb.actor import Actor


def _mock_db(candidates: list[dict]) -> MagicMock:
    db = MagicMock()
    db.get_by_creator.return_value = candidates

    def _get(actor_id=None):
        for c in candidates:
            if c["id"] == actor_id:
                return c
        return None

    db.get.side_effect = _get
    return db


class TestDuplicateCreatorWarning:
    def test_multiple_candidates_logs_warning_with_ids(self, caplog):
        candidates = [
            {"id": "actor-b", "creator": "dup@example.com", "passphrase": "x"},
            {"id": "actor-a", "creator": "dup@example.com", "passphrase": "y"},
        ]
        db = _mock_db(candidates)
        config = MagicMock()
        config.force_email_prop_as_creator = False

        with (
            patch("actingweb.actor.get_actor", return_value=db),
            caplog.at_level(logging.WARNING, logger="actingweb.actor"),
        ):
            actor = Actor(config=config)
            result = actor.get_from_creator("dup@example.com")

        assert result is True
        # Lowest id wins, deterministically, same as before this change.
        assert actor.id == "actor-a"

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "dup@example.com" in message
        assert "actor-a" in message
        assert "actor-b" in message

    def test_single_candidate_no_warning(self, caplog):
        candidates = [
            {"id": "actor-only", "creator": "solo@example.com", "passphrase": "x"},
        ]
        db = _mock_db(candidates)
        config = MagicMock()
        config.force_email_prop_as_creator = False

        with (
            patch("actingweb.actor.get_actor", return_value=db),
            caplog.at_level(logging.WARNING, logger="actingweb.actor"),
        ):
            actor = Actor(config=config)
            result = actor.get_from_creator("solo@example.com")

        assert result is True
        assert actor.id == "actor-only"
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == []

    def test_no_candidates_no_warning(self, caplog):
        db = _mock_db([])
        config = MagicMock()
        config.force_email_prop_as_creator = False

        with (
            patch("actingweb.actor.get_actor", return_value=db),
            caplog.at_level(logging.WARNING, logger="actingweb.actor"),
        ):
            actor = Actor(config=config)
            result = actor.get_from_creator("nobody@example.com")

        assert result is False
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == []
