"""``unique_creator`` stays off by default until the next major.

Flipping the default forces every deployment with duplicate creators through
``actingweb-unique-creators`` before it can start, and the flip deletes the
duplicate-tolerant adoption code with it. Both are in
``thoughts/todo/unique-creator-default-on-next-major.md``: change this test
together with that work, never on its own.
"""

from actingweb.config import Config
from actingweb.interface import ActingWebApp


def test_config_defaults_unique_creator_off() -> None:
    assert Config().unique_creator is False


def test_app_defaults_unique_creator_off() -> None:
    app = ActingWebApp(aw_type="urn:actingweb:test:default", fqdn="x.example.com")
    assert app.get_config().unique_creator is False
