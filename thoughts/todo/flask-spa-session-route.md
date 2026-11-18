# The Flask integration cannot hand a browser its SPA sign-in session

**Filed:** 2026-11-18, from the 4.0 release validation
(`thoughts/research/2026-11-18-3-16-release-validation.md`, Phase 2).
Checked against `241a67a` and `v3.15.1`.

## What is wrong

After a redirect-based SPA sign-in the callback sends the browser to the
SPA's `redirect_uri` with `?session=<id>` on both integrations
(`actingweb/handlers/oauth2_callback.py:1352-1353`). The SPA then reads the
pending session at `GET /oauth/spa/session/<session_id>`. The FastAPI
integration registers that route
(`actingweb/interface/integrations/fastapi_integration.py:932-944`); the
Flask integration registers only `/oauth/spa/session`
(`actingweb/interface/integrations/flask_integration.py:319`). A Flask SPA
that follows the redirect has no route to fetch its tokens from.

Not new in this release: `v3.15.1` has the same two registrations
(`v3.15.1:actingweb/interface/integrations/flask_integration.py:254`). The
SPA guide now says the route is FastAPI's.

## What closing it takes

The route on Flask, with the handler FastAPI's already calls, and one test
that walks the redirect on each integration. A patch (an additive route).

## Needs first

Nothing. No consumer has reported it; the demo's SPA mode is not exercised
on Flask.
