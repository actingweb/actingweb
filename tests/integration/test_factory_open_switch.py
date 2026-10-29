"""``with_open_factory(False)`` over HTTP (3.16)."""

import requests


class TestClosedFactoryOverHttp:
    def test_json_post_is_403_with_the_house_body(self, closed_factory_app) -> None:
        response = requests.post(
            f"{closed_factory_app}/",
            json={"creator": "closed-json@example.com"},
        )
        assert response.status_code == 403
        body = response.json()
        assert body["error"] is True and body["status_code"] == 403
        assert "with_open_factory" in body["message"]

    def test_form_post_is_403(self, closed_factory_app) -> None:
        response = requests.post(
            f"{closed_factory_app}/",
            data={"creator": "closed-form@example.com"},
        )
        assert response.status_code == 403

    def test_factory_page_and_login_still_answer(self, closed_factory_app) -> None:
        assert requests.get(f"{closed_factory_app}/").status_code == 200
        assert requests.get(f"{closed_factory_app}/login").status_code in (200, 302)


class TestDefaultServerStaysOpen:
    def test_json_post_creates(self, test_app, actor_factory) -> None:
        actor = actor_factory.create("still-open@example.com")
        assert actor["id"]
