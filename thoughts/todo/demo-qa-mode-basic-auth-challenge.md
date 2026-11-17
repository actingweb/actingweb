# The demo's local QA mode never prompts a browser for basic auth

Found 2026-11-16 by the browser walk of
`thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md`, Phase 3.

With `DEMO_QA_BASIC_AUTH=true` a request to `/<id>/www` without an
`Authorization` header is answered 401 with `WWW-Authenticate: Bearer
realm="ActingWeb"`. A browser shows no credential prompt for a Bearer
challenge, and Playwright's `httpCredentials` gets the 401 too: only a
client that sends the Basic header unasked gets in. `CLAUDE.md` ("Test
account") and `examples/demo/README.md` ("Local QA account") say to sign in
to `/<id>/www` with the creator and the passphrase.

## What to do

Either answer the web UI's 401 with a `Basic` challenge when QA basic auth
is on (the demo only, localhost only), or say in both documents that the
header must be sent preemptively. Check which challenge the library itself
sends for `/www` without OAuth configured before deciding it is the demo's.
