"""``BaseHandler`` has no import-time ``Config()`` default (3.16).

With creator uniqueness on by default, a handler built from a default
``Config()`` would be an enforced handler on a store that never ran
``check_ready()``.
"""

import pytest

from actingweb.config import Config
from actingweb.handlers.base_handler import BaseHandler


def test_a_handler_without_config_raises_naming_it() -> None:
    with pytest.raises(ValueError, match="config"):
        BaseHandler()


def test_a_handler_with_config_keeps_it() -> None:
    config = Config(unique_creator=False)
    assert BaseHandler(config=config).config is config
