# `CallbackOauthHandler` is exported, documented and routed nowhere

Filed 2026-11-15 by `spec-1-5` Phase 5 (sweep row O5). `actingweb/handlers/callback_oauth.py`
defines `CallbackOauthHandler`, which `docs/reference/handlers.rst` documents
and the package exports, but neither the Flask nor the FastAPI integration
routes it: the OAuth2 flow is served at `/oauth`. Specification 1.5 no
longer describes a per-actor OAuth binding.

## What to decide

Removing an exported class is a public-surface change: deprecate it in a
minor with a tombstone (as 3.16 did for `FanOutManager`), or route it if an
application needs a per-actor callback. Nothing in the library or the two
consumers imports it.
