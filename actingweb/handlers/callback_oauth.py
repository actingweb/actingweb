"""Removed in 4.0.

``CallbackOauthHandler`` redirected ``?code=...&state=<actor id>`` to a
per-actor ``/<actor id>/oauth`` path. Neither integration routed it, and
specification 1.5 no longer defines that path: the OAuth2 callback is served
at ``/oauth/callback``. Importing this module raises with the migration
pointer; it is removed at the next major release.
"""

from actingweb.config import CALLBACK_OAUTH_REMOVED

raise ImportError(CALLBACK_OAUTH_REMOVED)
