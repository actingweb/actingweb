#!/usr/bin/env python3
"""Repo-relative wrapper. The implementation now lives in the package
(``actingweb.maintenance.verify_orphans``) so it ships in the wheel; see
``actingweb/maintenance/__init__.py``.

Equivalent console entry point: ``actingweb-verify-orphans``.
"""

import sys

from actingweb.maintenance.verify_orphans import *  # noqa: F403
from actingweb.maintenance.verify_orphans import main

if __name__ == "__main__":
    sys.exit(main())
