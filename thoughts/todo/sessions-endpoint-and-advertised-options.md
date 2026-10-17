# `/sessions` has no library support, and the advertised option tags do not match what is implemented

## What happens

`/meta/actingweb/supported` returns a fixed list for every application
(`base_supported` in `actingweb/config.py`, extended only for `mcp`,
`trustpermissions` and the peer-permission tags by `update_supported_options()`).
The list includes `sessions`, but the library has nothing behind it:

- no route: neither `flask_integration.py` nor `fastapi_integration.py` registers
  `/<actor_id>/sessions`, so a request gets the framework's 404;
- no handler in `actingweb/handlers/`;
- no hook: `ActingWebApp` offers `action_hook` and `method_hook`
  (`actingweb/interface/app.py`), and `/resources` dispatches to callback hooks,
  but there is no `session_hook`.

The other optional endpoints split the work this way: the **library** owns the
route, authentication, the permission check (`permission_evaluator.py`) and
dispatch, and the **application** supplies the behaviour through a hook.
`examples/demo/shared_hooks/app/` (deployed by `actingwebdemo`) does exactly
that for actions and methods. For `/sessions` an application has no extension
point. Its only option is a raw framework route that redoes authentication with
`check_and_verify_auth()`, and that route gets no permission evaluator and no
MCP mapping.

A peer that reads `sessions` from `/meta` and tries to open a session
(spec, `/sessions (OPTIONAL)`: `POST` returns `201 Created` with a `Location`)
gets a 404.

## History

- `sessions`, `actions` and `methods` were in the default supported string by
  2017 (532ae98). None of the three had a handler then.
- `ACTINGWEB_SPEC_VALIDATION.md` (added in 10e6f5b, July 2025) listed all three
  as not implemented and recommended implementing them or removing the tags.
- cba1a6f (five days later) implemented `/actions` and `/methods` and deleted
  the audit file. `/sessions` was never implemented and its tag stayed.

## The wider tag mismatch (audit before fixing)

The supported list is written once for every app, so it describes neither what
the library implements nor what the application uses:

| Tag | State |
| --- | --- |
| `sessions` | Advertised, not implemented (above) |
| `actions`, `methods` | Advertised for every app, including apps that register no hook of that kind |
| `onewaytrust` | Advertised; the only reference in `actingweb/` is `config.py`. Spec: "A can have trust to B without implying the reverse". The library tracks `approved` and `peer_approved` separately, so it may be partly true. Not verified either way |
| `listproperties` | **Not** advertised, although list properties are implemented (spec 1.4 defines the tag) |
| `callbackcompression` | Read from peers (`peer_capabilities.py`), never advertised. Check whether the library accepts compressed callbacks before advertising it |

## Options

1. **Implement `/sessions` following the `/actions` pattern.** A
   `session_hook` decorator, routes in both integrations, auth and permission
   checks (a `sessions` category in the evaluator), hook dispatch for
   `POST /sessions/<type>` (create, `201` + `Location`), and `GET`/`PUT`/`DELETE`
   on `/sessions/<peerid>/<sessionid>`. Open questions the spec leaves to the
   implementation: callback URI vs. the "mirrored URL" model, whether WebSocket
   is in scope, and whether sessions map to anything in MCP.
2. **Advertise what is enabled.** Derive `actions`, `methods`, `resources` and
   `sessions` from the registered hooks, and fix the rows in the table above.
   Doable on its own, and pairs naturally with option 1.
3. **Only drop `sessions` from the list.** Smallest change; leaves the other
   mismatches.

Preferred (2026-10-17): 1 and 2 together.

## Release impact

Option 1 adds a route and a hook name: a **minor** with a migration guide
(CLAUDE.md, Release). Option 2 changes what `/meta/actingweb/supported` returns,
which peers read: a **Behavior change** entry in the changelog at minimum.
Option 3 alone is a patch with a behaviour note.

## Related

- `docs/protocol/actingweb-spec.rst`: "Option tags", "/sessions (OPTIONAL)"
- `.oss-scanner/threat_model.md` lists `/sessions` as having no library route
