#!/usr/bin/env python3
"""Repo-relative wrapper. The implementation lives in the package
(``actingweb.maintenance.mark_actors_vouched``) so it ships in the wheel; see
``actingweb/maintenance/__init__.py``.

Equivalent console entry point: ``actingweb-mark-actors-vouched``.
"""

import sys

from actingweb.maintenance.mark_actors_vouched import *  # noqa: F403
from actingweb.maintenance.mark_actors_vouched import main

if __name__ == "__main__":
    sys.exit(main())
