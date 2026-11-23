# Research: a consumer's production report on 4.0.0rc2, triaged

**Date:** 2026-11-22
**Source:** two reports in `thoughts/inbound/`, both filed 2026-11-22 by the
Emm AI repository (`actingweb_mcp`):
`emm-4-0-rc2-production-observations.md`, out of its production upgrade from
3.15.1 to 4.0.0rc2 and the planning of its next change (`actingweb_mcp`:
`thoughts/plans/2026-11-22-actingweb-4-0-improvements.md`), and
`emm-plan-assumes-rc3.md`, its reply to the first version of this note.
Both are deleted; this note and the todos it names are the record.
**Checked against:** `master` at `bee0eb5`, which is the commit `v4.0.0rc2`
tags.

## The upgrade (reported, not re-checked here)

- 3.15.1 to 4.0.0rc2 from the TestPyPI wheel, deployed 2026-11-22 11:10 UTC
  on AWS Lambda and DynamoDB, 55 actors.
- The store preparation ran as documented: the vouched marking (`marked=0
  skipped=53 system=2`), `actingweb-unique-creators enable` (55 creator
  records and the backfill-complete item), the lookup backfill
  (`collisions=0 faults=0`), no legacy rows to move, four readiness gates
  ready.
- After the deploy: no `ACTINGWEB_STORE_NOT_READY`, `DbError`,
  `AccessDenied` or traceback in the app, WebSocket or OAuth paths; sign-in
  with Google, Apple and GitHub; an MCP client connected before the upgrade
  refreshed its token and worked without a new authorization.
- On a local stage before the release: Stripe subscribe and cancel, a
  ChatGPT connector connected, used, deleted and connected again.

The reporter says nothing blocks rc2, and that its items 1 and 2 decide
which released version it pins.

## What each check found

Item numbers are the report's.

| # | Claim | Verdict | What the check changed | Filed in |
| --- | --- | --- | --- | --- |
| 1 | A `DbError` in a tool hook answers a JSON-RPC error with 503 | True, sync and async | The neighbouring branch answers any other tool exception as JSON-RPC `-32603` with the exception's own text; the shared mapping gives five different answers, so the fixed texts cover more than the two the report names | `todo/mcp-tool-fault-answer-and-public-classifier.md` |
| 2 | `db_error_answer` and `is_permanent` are private | True | Nothing in `docs/` or a public module names them | same |
| 3 | `AttributeKeyCollision` has no branch in `db_error_answer` | True | Reachable from any application `set_attr` or conditional create that is not one of the three library paths catching it | same |
| 4 | Which release carries 1 to 3 and 5 | A question | Answered by the cut below | this note |
| 5 | `complete_client_authorization` joins with a bare `?` | True | Registration accepts a redirect URI with a query (exact-match validation), so it is reachable today; no third join of this kind in the OAuth2 server | `todo/authorization-redirect-second-question-mark.md` |
| 6 | No public query for the MCP token cache | True | The migration guide's text is as quoted | `todo/mcp-token-cache-public-query.md` |
| 7 | A deletion finished elsewhere gives the application's two hooks nothing to share | True | `hook_kwargs` is the only tombstone field `actor_deleted_complete` receives, and only the library writes it | `todo/deletion-cleanup-across-processes.md` |
| 8 | `PropertyListStore.exists` and `list_all` fold a non-`DbError` exception | True, narrower than it reads | A store fault already propagates (`except DbError: raise`); what is folded is everything else, which is a programming error | `todo/fault-folds-left-in-store-reads.md` |
| 9 | `InternalStore` reads a fault as "not set" | True, and decided | A decision in force (`plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md`): the store folds so `actor.store.x` never raises, and `actor.store.loaded` is the fail-closed signal. The report does not mention `loaded`; `docs/reference/database-backends.rst` names it in one sentence of the backend reference, not where a hook author reads (corrected 2026-11-23: the first version of this note said `docs/` did not name it) | same |
| 10 | `read_tombstone` is exported, not documented | True | `finished_at` is not in `docs/` either | `todo/deletion-cleanup-across-processes.md` |
| 11 | `conditional_update_attr` answers `False` on a fault | True on both backends, and decided | Raising was rejected as D10 of `plans/2026-11-01-single-mode-and-consumer-primitives.md` ("it would rework `consume_once`"). Eleven of the twelve library call sites follow a `False` with their own check to tell a fault from a lost race; one raises on any `False` | `todo/fault-folds-left-in-store-reads.md` |
| — | `GET /mcp` polled about once a second, answered 200 | Not confirmed | Header casing is ruled out for both integrations. The report's own timing (first minutes after the deploy, three 405s in all) also fits 200s written by the previous version during the rollover | `todo/mcp-get-polled-after-the-405.md` |
| — | `Gap timeout exceeded`, `Fetched 7 diffs but processed 0`, both sides in step | Log lines exist; cause not examined | Not compared with 3.15.1 or rc1 by anyone | `todo/subscriber-gap-timeout-logged-while-in-step.md` |

## The reporter's reply

After reading the table above, the reporter's owner decided that its plan
assumes an rc3 carrying the asks. What the reply changes:

- **The pin waits on items 1 and 5 only.** The reporter's rc3 phase opens
  with a check of those two against the rc3 source and stops if one does
  not hold. Its test for item 1, through the sync and async handlers: HTTP
  200, a result with `isError: true`, fixed text, no fault text;
  `initialize` and `tools/list` unchanged.
- **Items 2, 3 and 8 are not used by its plan** (its webhooks answer 500 for
  any `DbError`), so the first report's "items 1 and 2 decide the pin" no
  longer holds for item 2.
- **The fixed texts matter early.** The reporter's skill tells the model
  what to do with each failure: "try again" needs nothing from it, a code
  or a "do not retry" text needs a skill release.
- **The neighbouring branch** (`Tool execution failed: {str(e)}`) may change
  in the same release: its tools catch their own exceptions.
- **Item 9** is accepted as documented behaviour (`store.loaded`).
- **Item 11:** either answer works for it.
- **Item 7:** a field passed between the two hooks would not replace its
  own record by itself; the reasons are in the todo.
- **The `GET /mcp` headers are not captured yet.**

Checked: the tombstone retention it cites is 30 days
(`constants.DELETION_TOMBSTONE_TTL`), and `complete_client_authorization`
asks the application's `oauth2_trust_requested` hooks unless `decide_trust`
is passed, so registering none is a supported use.

## The cut for rc3

The rule: an item belongs before 4.0.0 when landing it afterwards would cost
a minor or a major under `CONTRIBUTING.rst` ("Which number a release
gets"), or when the reporter's pin waits on it. A bug fix that changes no
contract is cheap either way and rides along. An additive name can follow in
a 4.0.x or 4.1.

**Recommended for rc3:**

- Item 1: a wire change (503 to 200 with `isError: true`), and the pin
  waits on it. The neighbouring branch goes with it: the same misuse of the
  protocol error, a wire change later, and the one reporting consumer does
  not depend on today's answer.
- Item 5: a bug fix, one line and a test; the pin waits on it.
- Item 3: a bug fix inside the mapping item 1 reuses.
- Item 8: a bug fix, small.
- Item 9, as documentation of `store.loaded` only.

**Decide before 4.0.0, the owner's call:**

- Item 2, in or out. It is additive and no pin waits on it, so it can
  follow in a 4.0.x. It is cheap once item 1 has named the classes for its
  fixed texts, and designing the two together avoids two vocabularies.
- Item 11. The decision in force is not to raise (D10), and the reporter
  works with either answer. The report is a
  consumer asking for the rejected option; eleven of the library's own
  twelve call sites carry the second check the consumer objects to. Reopening
  it is only possible in 4.0.0: raising by default changes what an
  unchanged application sees. Left as decided, a keyword-only `strict=`
  that defaults to today's answer is additive and can land at any time.
- The `GET /mcp` loop, if it is one. The first question to the reporter is
  whether it reproduces on rc2 now and which version wrote the 200s. If it
  does, any fix is a wire change (it would rewrite MCP-3 in
  `specs/mcp-server.md`) and needs its answer before 4.0.0. If it does
  not, the item closes.

**After 4.0.0 (additive):** items 6, 7 and 10, and the subscription log
lines.

rc3 as recommended changes the `tools/call` answer for a failing tool (a
store fault, and any other exception if the neighbouring branch goes with
it), and has no operator step.
