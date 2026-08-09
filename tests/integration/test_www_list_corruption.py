"""
A holed list property must render an inline corruption notice on the www
property page, not a 500 (Phase 3 of
thoughts/plans/2026-08-08-property-list-index-integrity.md).

Uses www_test_app (basic auth, no OAuth) -- same fixture as
test_www_templates.py.
"""

import datetime
import json

import requests

from actingweb.config import Config
from actingweb.db import get_property


def _seed_v1_list(actor_id, list_name, items):
    """Directly write a v1-format list (meta + dense-integer item rows).
    ListProperty.append()/PUT-index-append now create v2 (fractional rank
    key) lists by default (Phase 4); this test needs an actual v1 list to
    punch a hole into (dense-integer rows a v2 list doesn't have)."""
    config = Config()
    db = get_property(config)
    now = datetime.datetime.now().isoformat()
    meta = {
        "length": len(items),
        "created_at": now,
        "updated_at": now,
        "item_type": "json",
        "chunk_size": 1,
        "version": "1.0",
        "description": "",
        "explanation": "",
    }
    assert db.set(
        actor_id=actor_id, name=f"list:{list_name}-meta", value=json.dumps(meta)
    )
    for i, item in enumerate(items):
        assert db.set(
            actor_id=actor_id, name=f"list:{list_name}-{i}", value=json.dumps(item)
        )


def _punch_hole(actor_id, list_name, index):
    config = Config()
    db = get_property(config)
    assert db.set(actor_id=actor_id, name=f"list:{list_name}-{index}", value=None)


class TestWwwHoledListRendersNotice:
    def test_holed_list_page_is_200_with_notice_not_500(self, www_test_app):
        response = requests.post(
            f"{www_test_app}/",
            json={"creator": "www-corruption-test@actingweb.net"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor_data = response.json()
        actor_id = actor_data["id"]
        passphrase = actor_data["passphrase"]
        auth = (actor_data["creator"], passphrase)
        actor_url = f"{www_test_app}/{actor_id}"

        try:
            _seed_v1_list(actor_id, "corrupt_list", ["item-0", "item-1", "item-2"])
            _punch_hole(actor_id, "corrupt_list", 1)

            response = requests.get(
                f"{actor_url}/www/properties/corrupt_list", auth=auth
            )
            assert response.status_code == 200
            assert "corrupted" in response.text.lower()
        finally:
            requests.delete(actor_url, auth=auth)
