# `/sessions` has no library support

## What happens

`/meta/actingweb/supported` no longer advertises `sessions` (3.16: the list is
computed from the configuration and only names what exists; the tag table, the
`onewaytrust`, `listproperties` and `callbackcompression` audit are recorded in
`thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md`, D14), but the
library still has nothing behind the spec's optional `/sessions` endpoint:

- no route: neither `flask_integration.py` nor `fastapi_integration.py` registers
  `/<actor_id>/sessions`, so a request gets the framework's 404;
- no handler in `actingweb/handlers/`;
- no hook: `ActingWebApp` offers `action_hook` and `method_hook`
  (`actingweb/interface/app.py`), and `/resources` dispatches to callback hooks,
  but there is no `session_hook`.

The other optional endpoints split the work this way: the **library** owns the
route, authentication, the permission check (`permission_evaluator.py`) and
dispatch, and the **application** supplies the behaviour through a hook. For
`/sessions` an application has no extension point; its only option is a raw
framework route that redoes authentication with `check_and_verify_auth()`.

## What a fix needs

Implement `/sessions` following the `/actions` pattern: a `session_hook`
decorator, routes in both integrations, auth and permission checks (a `sessions`
category in the evaluator), hook dispatch for `POST /sessions/<type>` (create,
`201` + `Location`), and `GET`/`PUT`/`DELETE` on `/sessions/<peerid>/<sessionid>`;
then advertise `sessions` again. Open questions the spec leaves to the
implementation: callback URI vs. the "mirrored URL" model, whether WebSocket is in
scope, and whether sessions map to anything in MCP. A new route and hook name make
it a **minor** with a migration guide.

## Related

- `docs/protocol/actingweb-spec.rst`: "Option tags", "/sessions (OPTIONAL)"
- `.oss-scanner/threat_model.md` lists `/sessions` as having no library route
