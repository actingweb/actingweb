#!/usr/bin/env python3
"""Repo-relative wrapper. The implementation lives in the package
(``actingweb.maintenance.unique_creators``) so it ships in the wheel; see
``actingweb/maintenance/__init__.py``.

Equivalent console entry point: ``actingweb-unique-creators``.
"""

import sys

from actingweb.maintenance.unique_creators import *  # noqa: F403
from actingweb.maintenance.unique_creators import main

if __name__ == "__main__":
    sys.exit(main())
