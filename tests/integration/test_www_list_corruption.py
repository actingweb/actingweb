"""
A holed list property must render an inline corruption notice on the www
property page, not a 500 (Phase 3 of
thoughts/plans/2026-08-08-property-list-index-integrity.md).

Uses www_test_app (basic auth, no OAuth) -- same fixture as
test_www_templates.py.
"""

import requests

from actingweb.config import Config
from actingweb.db import get_property


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
            response = requests.post(
                f"{actor_url}/properties",
                json={"corrupt_list": {"_type": "list"}},
                auth=auth,
            )
            assert response.status_code == 201

            for i in range(3):
                response = requests.put(
                    f"{actor_url}/properties/corrupt_list?index={i}",
                    json=f"item-{i}",
                    auth=auth,
                )
                assert response.status_code == 204

            _punch_hole(actor_id, "corrupt_list", 1)

            response = requests.get(
                f"{actor_url}/www/properties/corrupt_list", auth=auth
            )
            assert response.status_code == 200
            assert "corrupted" in response.text.lower()
        finally:
            requests.delete(actor_url, auth=auth)
