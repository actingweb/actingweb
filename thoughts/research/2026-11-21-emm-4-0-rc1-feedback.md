# Research: triage of a consumer's 4.0.0rc1 migration observations

**Date:** 2026-11-21
**Source:** `thoughts/inbound/emm-4-0-rc1-migration-observations.md`, filed
2026-11-21 by the Emm AI repository (`actingweb_mcp`) after its migration
from 3.15.1 to 4.0.0rc1 (the TestPyPI wheel, a full suite run on PostgreSQL
and DynamoDB Local, two browser walks, a store-preparation rehearsal on a
copy of six production actors). The report is deleted with this triage; its
attribution is carried here.
**Plan:** [`plans/2026-11-21-trust-request-answer-secret.md`](../plans/2026-11-21-trust-request-answer-secret.md) (4.0.0rc2 scope, owner 2026-11-21)
**Checked against:** `master` at `add5a4d` and `v3.15.1`.

## The release candidate against a real consumer

The consumer reports no defect in rc1 that blocks a release. The store
preparation commands behaved as documented on the rehearsal store, the four
readiness gates reported ready, and the app started. This is the run that
`todo/rc-pass-against-real-consumers.md` was waiting on, so that todo is
deleted. The report does not compare its suite against the five-name baseline
in `research/2026-11-18-3-16-release-validation.md`; it reports the outcome
only.

## Items, each checked against the tree

| # | Claim | Check | Outcome |
| --- | --- | --- | --- |
| 1 | A permission change logs one `Cannot notify peer oauth2_client:… no baseuri in trust` warning per MCP client (about 70 on one account) | `actingweb/trust_permissions.py:524-530` warns for any peer whose trust has no base URI; an OAuth2 client's trust has none by construction. Same text at `v3.15.1` `trust_permissions.py:362` | **Confirmed, not new in 4.0.** rc2: skip OAuth2-client peers at DEBUG; any other trust without a base URI keeps the WARNING (owner, 2026-11-21) |
| 2a | An MCP client's registration outlives its revoked trust | An anonymous registration lives on the OAuth2 system actor (`actingweb/oauth2_server/oauth2_server.py:140-147`). `Trust.delete` disables a client only when the deleting actor owns it, and otherwise revokes that actor's connection tokens (`actingweb/trust.py:51-63` of `delete`) | **Confirmed, by design**: one registration can serve several users; deleting it would disconnect the others |
| 2b | Can that client start a new authorization without the user seeing a consent step? | Not answered by reading; see "Re-authorization after a revoke" below | rc2: settled by a test, fixed if it fails (owner, 2026-11-21) |
| 3 | No supported way to write or re-point one actor's creator record | `actingweb/maintenance/unique_creators.py:69`: `enable` refuses `--creator`; the single-record helpers (`_repair_record`, `_settle_record`, `_release_losers_record`) are private | **Confirmed.** rc2: a public function and an `actingweb-unique-creators record --actor ID [--apply]` subcommand on both backends (owner, 2026-11-21); see "A single actor's creator record" below |
| 4 | MCP `serverInfo.version` is always the library's version | `actingweb/handlers/mcp.py:1207` `"serverInfo": {"name": server_name, "version": __version__}`; `with_mcp(server_name=…)` (`actingweb/interface/app.py:675`) takes no version | **Confirmed, not new in 4.0.** rc2: an optional `server_version` on `with_mcp`, defaulting to the library's version (owner, 2026-11-21) |
| — | A memory type set back to "No Access" stays readable from the subscriber's cached copy | The consumer attributes it to its own configuration (`auto_delete_on_revocation` off) | Not a library issue; nothing filed |

## Re-authorization after a revoke

**Verdict: no silent re-authorization.** A client whose connection was
deleted gets a new code only after the user acts on an ActingWeb page. This
was traced in the code; no test shows it yet.

- **GET `/oauth/authorize`:** always answers the sign-in form with a fresh
  `form_nonce` (`oauth2_server.py:285-298`). It reads no session cookie and
  no existing trust. The nonce cookie is HttpOnly and `__Host-` over https
  (`oauth2_endpoints.py:606-622`). The JSON form is served with
  `Access-Control-Allow-Origin: *` and no credentials, so another site
  cannot plant the cookie (`flask_integration.py:1600-1605`).
- **The callback skips the confirmation page only** when the state's nonce
  equals the browser's cookie (`oauth2_server.py:587-594`). Otherwise it
  shows "Confirm access" and waits for Approve (`:1128-1144`;
  `oauth2_endpoints.py:707-781`). Google is always sent `prompt=consent`;
  other providers may pass a signed-in user through, but only after the
  user's click on the ActingWeb form.
- **A reconnect creates a new row** (`trust_manager.py:754-864`). It first
  deletes any stored permission override for that peer id (`:817-830`), so
  old permissions do not come back. The type is re-checked against the
  client list and the `oauth2_trust_requested` hook.
- **The disconnect** revokes this actor's access and refresh tokens for the
  client (`token_manager.py:1766-1896`) and the provider tokens
  (`trust.py:236-249`). `client_credentials` is refused for a client on the
  system actor (`oauth2_server.py:806-810`).
- **The exception:** a consumer's own route calling
  `complete_client_authorization` (`oauth2_server.py:1246-1317`) shows no
  ActingWeb page; the consumer asks the user itself.

**Gap found by the trace:**

- The sweep covers tokens, not authorization codes or pending confirmations
  (`token_manager.py:1845-1847`).
- A code issued before the disconnect (TTL 600 s) can still be exchanged
  afterwards: `exchange_authorization_code` (`token_manager.py:231-384`)
  checks no trust row.
- Its tokens are refused at the MCP endpoint while no trust resolves
  (`handlers/mcp.py:1226-1247`). Whether they come alive if the user
  reconnects the same client, and whether `refresh_access_token` checks the
  trust row, was not traced.

**Tests:**

- Existing, in `tests/integration/test_oauth2_trust_binding.py` (`Flow`,
  `wire_oauth`): the flow in one browser, a form the client posted itself,
  declining, a replayed state. Wire rows WG14-WG16 record the same.
- None reconnects after a disconnect.

## A single actor's creator record

What a single-actor operation has to work with:

- **DynamoDB records.** Each lives in `<prefix>_creators`, keyed by the
  normalised creator, naming `actor_id` (`db/dynamodb/creator.py:20-31`). The
  table has **no index by actor id**.
  - A create writes the record in the actor's transaction (`does_not_exist`;
    `dynamodb/actor.py:584-605`).
  - A rename puts the new record, then releases the old one; a fault there
    is logged, which is one source of orphans (`:322-347`, `:753-776`).
  - Shared helpers commit only while the actor row is as read:
    `release_stale_record`, `record_for_actor_as_read`, `move_stale_record`
    (`dynamodb/actor.py:1006-1104`).
- **What the consumer's restore produces.** An actor renamed from *older* to
  *newer*, then restored with *older*, leaves:
  - an orphan record *newer* → actor (a mismatch);
  - no record for *older* (released at the rename).

  `enable` refuses on any orphan before writing (`unique_creators.py:1059`).
  Today the fix is `resolve --apply` (removes the orphan) then
  `enable --apply` (records *older*): two full scans.
- **Finding the orphan without a scan.** It is possible only when the caller
  names the newer address. The `_internal` bucket's `email`/`vouched_creator`
  hold it only if the restore did not overwrite them. A creators-table scan
  or a new GSI are the other routes.
- **PostgreSQL** has no records. `ux_actors_creator` is a unique index on the
  raw creator, partial over exempt values (`creator_rules.py:31`). A single
  actor's check there is the index state plus no other row with the same
  `lower(creator)`. Nothing is written.
- **Rules a record writer must respect** (`creator_rules.py:48-86`):
  - lowercase `@` values;
  - exempt values (`trustee`, `creator`, `""`) and `#dup-` are never
    recorded;
  - `#…` values are reserved;
  - `system`/`oauth2-system` belong to the system actors.
  - `make_config()` runs with `unique_creator=False`, so the module-level
    helpers are the ones to use (`dynamodb/actor.py:671-696`).
- **Race.** A sign-in with *older* before the record exists creates a second
  actor for it, and only `resolve` settles that. The restore and the record
  should run with sign-ins for that address quiet.
- **CLI and tests.**
  - `pyproject.toml:41` entry; `main`'s argparse at
    `unique_creators.py:1365-1449`.
  - A `record` subcommand must branch in `_run` before `collect`, which
    scans.
  - Integration tests: `tests/integration/test_unique_creators_command.py`
    (xdist group `unique_creator`; `_raw_actor` seeds a restore-shaped row on
    both backends). Unit tests: `tests/test_unique_creators_command.py`.
