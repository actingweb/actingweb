"""Removed in 4.0.

``FanOutManager`` and ``FanOutResult`` were never on the publish path: the
library sends subscription callbacks with ``actingweb.callback_sender``,
bounded by ``max_concurrent_callbacks``. Importing this module raises with
the migration pointer; it is removed at the next major release.
"""

from actingweb.config import FANOUT_REMOVED

raise ImportError(FANOUT_REMOVED.format(what="actingweb.fanout"))
