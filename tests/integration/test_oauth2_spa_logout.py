"""``/oauth/logout`` and ``/oauth/revoke`` end the refresh chain, end to end.

Runs against the live test server on DynamoDB and PostgreSQL. Each test logs
in with the passphrase grant, so it owns its chain; a second login shows that
another device (another chain) of the same actor survives.
"""

import requests


def _login(test_app: str, actor: dict) -> dict:
    response = requests.post(
        f"{test_app}/oauth/spa/token",
        json={
            "grant_type": "passphrase",
            "actor_id": actor["id"],
            "passphrase": actor["passphrase"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _refresh(test_app: str, refresh_token: str) -> requests.Response:
    return requests.post(
        f"{test_app}/oauth/spa/token",
        json={"grant_type": "refresh_token", "refresh_token": refresh_token},
    )


class TestSpaLogoutEndsTheChain:
    def test_logout_with_the_access_token_kills_the_refresh_token(
        self, test_app, actor_factory
    ):
        actor = actor_factory.create("spa_logout_access@example.com")
        session = _login(test_app, actor)
        other = _login(test_app, actor)

        response = requests.post(
            f"{test_app}/oauth/logout",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )

        assert response.status_code == 200, response.text
        assert _refresh(test_app, session["refresh_token"]).status_code == 401
        # Another device of the same actor is another chain and still works.
        assert _refresh(test_app, other["refresh_token"]).status_code == 200

    def test_revoke_with_the_refresh_token_ends_the_chain(
        self, test_app, actor_factory
    ):
        actor = actor_factory.create("spa_revoke_refresh@example.com")
        session = _login(test_app, actor)

        response = requests.post(
            f"{test_app}/oauth/revoke",
            json={
                "token": session["refresh_token"],
                "token_type_hint": "refresh_token",
            },
        )

        assert response.status_code == 200, response.text
        assert _refresh(test_app, session["refresh_token"]).status_code == 401

    def test_revoking_a_used_refresh_token_kills_its_successor(
        self, test_app, actor_factory
    ):
        actor = actor_factory.create("spa_revoke_used@example.com")
        session = _login(test_app, actor)
        rotated = _refresh(test_app, session["refresh_token"])
        assert rotated.status_code == 200, rotated.text
        newest = rotated.json()["refresh_token"]

        response = requests.post(
            f"{test_app}/oauth/revoke",
            json={
                "token": session["refresh_token"],
                "token_type_hint": "refresh_token",
            },
        )

        assert response.status_code == 200, response.text
        assert _refresh(test_app, newest).status_code == 401

    def test_logout_with_only_a_refresh_token_in_the_body_ends_the_chain(
        self, test_app, actor_factory
    ):
        actor = actor_factory.create("spa_logout_refresh_only@example.com")
        session = _login(test_app, actor)

        response = requests.post(
            f"{test_app}/oauth/logout",
            json={"refresh_token": session["refresh_token"]},
        )

        assert response.status_code == 200, response.text
        assert _refresh(test_app, session["refresh_token"]).status_code == 401

    def test_logout_with_the_refresh_cookie_alone_ends_the_chain(
        self, test_app, actor_factory
    ):
        actor = actor_factory.create("spa_logout_cookie_only@example.com")
        session = _login(test_app, actor)

        response = requests.post(
            f"{test_app}/oauth/logout",
            cookies={"refresh_token": session["refresh_token"]},
        )

        assert response.status_code == 200, response.text
        assert _refresh(test_app, session["refresh_token"]).status_code == 401

    def test_an_unknown_token_is_still_a_200_on_revoke(self, test_app):
        response = requests.post(
            f"{test_app}/oauth/revoke", json={"token": "no-such-token"}
        )
        assert response.status_code == 200
