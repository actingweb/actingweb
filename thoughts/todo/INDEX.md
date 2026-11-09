# todo/ — prioritised index

Every file in this directory, ordered by what to do next. **Last full re-rank:
2026-11-01.** Rows, files and the todos the 3.16 roll-up touched were
re-checked on 2026-11-05, after it merged; the order still stands. Rows marked
**Planned for 3.16** have an owner-chosen approach and a proposed plan
(2026-11-06); the order they are taken in is the first section below.

**This directory holds only what is *not* done.** When work lands, its file is
deleted — the plan and the verification are the record, and they are where the
decisions and the implementation history live. Nothing here should say what
shipped, when, or in which release, except as a pointer to the plan that says
it properly.

**This file is a table of contents, not a source of truth.** Each row says what
implementing it buys and why it is worth doing — one line each, deliberately.
Everything else lives in the linked file. If a row and its file disagree, the
file wins.

**Maintaining it:** add a row when you add a todo, delete the row when you
delete the todo. Re-rank when something lands or a trigger fires. Don't copy
detail up here — a duplicated fact is a fact that will drift. Rows are
identified by their file, not by a number: numbering a living queue means either
renumbering (which silently changes what an old reference means) or freezing the
numbers (which turns the index into a record of what used to be here).

Ordering is by *impact ÷ effort*, not by severity alone: a cheap fix to a
moderate problem outranks an expensive fix to a slightly worse one.

---

## Planned for 3.16: order, dependencies and gates

Six plans (2026-11-06): `peer-authorisation-fixes` implemented and
verified (2026-11-08, issues open, below); the other five `status:
proposed`. **This section is the one
copy of the order, of what depends on what between the plans, and of the
gates between them.** Each plan keeps a pointer here and its own "This plan"
paragraph, which says what that plan uses from the others and wins on that
detail. One PR per plan, one commit per phase; a plan starts when the one
before it has merged and its gates are met, because the checks allow one
test run at a time. The 3.16 tag stays held until all six have merged.
Proposed is not approved: `attribute-list-v2-port` and `spec-1-5` say in
their "Readiness" paragraph that they need another draft first;
`subscription-wire-baseline` was redrafted on 2026-11-07 after the spike and
the research pass and awaits approval (its "What Already Exists" now points
at `rows.toml`).

| Order | Plan | Todo it closes | Needs first |
| --- | --- | --- | --- |
| Before 0 | [Emm's suite against `master`](emm-suite-against-master.md): the consumer's tests run on the library as it is, so what 3.16 already changes for Emm is known before more lands. **The `master` run is done (2026-11-07, `research/2026-11-07-emm-suite-against-master.md`): no library regression, five Emm-side adoption failures as the baseline.** The file stays for the per-plan runs | Itself | Nothing now; the worktrees exist |
| 0 | [`peer-authorisation-fixes`](../plans/2026-11-06-peer-authorisation-fixes.md): unauthenticated callers refused on `/callbacks`, a callback's URL fetched only from the peer, a peer limited to its own permissions and subscriptions; first, the fourteen legitimate flows the fix must leave unchanged, recorded on the harness the baseline spike builds | None; found by the reviews of the other plans and confirmed by a run | Nothing. Security first. **Implemented and verified 2026-11-08** on `fix/3.16.0-peer-authorisation` (local; the PR carries the records branch, which stays local until then). Gate 2 met (Emm's run). The verification (`verifications/2026-11-08-peer-authorisation-fixes.md`) found four issues the PR must not open with: an `admin` peer's secret read turns into a takeover through the re-pair, the re-pair's swap races the usage write on DynamoDB, a lost answer splits a pairing, a verified squat is permanent, a sender with a slow clock has its revocation dropped. **Iterated 2026-11-08** (`d836bd0`, owner decisions on the secret redaction and the `/meta` binding): Emm's suite re-run clean. **Re-verified 2026-11-08** (`verifications/2026-11-08-peer-authorisation-fixes-reverify-1.md`): Issues 2, 5 to 11 closed; still open before the PR: the `/meta` check is answered by the squatter and auto-accept approves an unverified creation, an `admin` peer can delete and re-create another peer, a lost 202 re-pair splits. **Iterated again 2026-11-08** (plan iterations 11-17): auto-accept only for a verified request and the self-asserted id documented (owner), the admin DELETE accepted and documented (owner), Issues 3 to 8 fixed; Full tier green, no recording changed. Emm's suite re-run on `a8007e5`: the baseline. **Re-verified 2026-11-08** (`verifications/2026-11-08-peer-authorisation-fixes-reverify-2.md`): reverify-1's issues closed or accepted; open before the PR: the permission-callback race is closed only between callbacks (a 503 is never resent, revoked data deleted before the write wins, query writers unconditional), plus five small items. **Iterated 2026-11-08** (plan iterations 18-24): the sender resends a 503 and the `/meta` check is two short tries (owner), every writer of the copy conditional, what a losing callback deleted fetched again, the rebuild per copy, the probe and docs fixed. **Re-verified 2026-11-08** (`verifications/2026-11-08-peer-authorisation-fixes-reverify-3.md`, `dca966f`): reverify-2's issues closed; Emm's suite on `dca966f` the baseline. Open before the PR: the restore filters by the last diff not the stored grant, the sync sender logs a final 503 as success, a fault in the rebuild's fetch escapes `prune`, a query copy drops the sender timestamp; three low. **Iterated 2026-11-08** (plan iterations 25-31): reverify-3's seven issues fixed; owner decision: one whole-branch review (`/security-review`, `/code-review` high, codex) before the PR. **Whole-branch review 2026-11-08** (`verifications/2026-11-08-peer-authorisation-fixes-reverify-4.md`, `7fc2f48`): security review no finding; no provider found a cross-peer path. Open before the PR: owner-initiated trust no longer approves a pending inbound row, the initiator's create is unconditional, a multi-instance sender's revocation can drop silently; owner decisions on the inert `owner` rows and FanOutManager's downgrade; ten low. **Iterated 2026-11-08** (plan iterations 32-37): owner decisions (the `owner` rows bind to the path's peer, so no adoption rows; `FanOutManager` sends large payloads in full) and all fifteen issues fixed; three `.subscriber` wire rows re-recorded. Emm's suite on `376b71c`: the baseline (PostgreSQL 2 failed / 7406 passed, DynamoDB 3 failed / 54 passed). **Re-verified 2026-11-09** (`verifications/2026-11-09-peer-authorisation-fixes-reverify-5.md`, `376b71c`): reverify-4's issues closed, but two of the fixes opened holes: creating a trust approves an unverified pending row with its requester's secret, and the `owner` rows now let any approved peer create a subscription and pull unfiltered diffs; a peer's base-URI move skips the `/meta` check. Open before the PR: those three (owner decision on the subscription admission), the reconcile's delete-before-store, the approve hook, eight low; then Emm's suite and a verification with the security review. **Iterated 2026-11-09** (plan iterations 38-43, `325370f`): owner decisions (an unverified pending request is replaced by the owner's own; the `owner` row admits a peer's GET/PUT/DELETE on its own subscription only, and pulled `properties` diffs are filtered; a peer's base-URI move must name it on `/meta`), the reconcile and eight low fixed; Full tier green, no recording changed; Emm's suite on `325370f`: the baseline. **Re-verified 2026-11-09** (`verifications/2026-11-09-peer-authorisation-fixes-reverify-6.md`, `5f33163`; security review, code review, codex, browser walk): reverify-5's holes closed on their routes, security review no finding. Open before the PR: an owner's explicit approval (web UI, `PUT /trust`, `TrustManager`) still approves an unverified request (pre-existing; owner decision), replacing an honest unverified request strands both sides, the narrowed `owner` row refuses a peer's own subscription listing, the pull filter ignores the resource and filters an object under a subtarget per key; six low. Then Emm's suite and a verification with the security review. **Trust-boundary audit 2026-11-09** (`verifications/2026-11-09-peer-authorisation-fixes-audit.md`, whole branch at `18a9bb5`, owner's request): three High (an unapproved row passes the permission evaluator, on `master` too; a re-pair in flight lands its secret on a replaced row, introduced; every approval route approves an unverified row), eight Medium (grant enforcement per route and level, revocation deletes too little, the revocation probe strands a pair, open client registration chooses `admin`), nine Low. Owner decision (2026-11-09): this PR closes A1, A2, A3 with reverify-6 Issues 1-2, A9 and reverify-6 Issues 3-11, each checked against the protocol spec; A4-A8, A10, A11 and the Lows go to a second local security plan before anything is pushed. **Iterated 2026-11-09** (plan iterations 45-55, `d3fd713`): A1 (an unapproved row is granted nothing), A3 and Issues 1-2 (approval only on a verified row, after a second verification), A2 (re-pair only on a verified or approved row, conditioned on the bearer), A9 (the probe), reverify-6 Issues 3-11 (one push/pull filter closing A4 too, the listing row, the reconcile, 503, the hook flag), docs and spec; Full tier green, no recording changed; Emm's suite on `d3fd713`: the baseline. **Re-verified 2026-11-09** (`verifications/2026-11-09-peer-authorisation-fixes-reverify-7.md`, `d3fd713`; security review, code review, codex, browser walk; Full tier green): A1, A2, A9 closed. Open before the PR: a critical hole the branch opened (two mirrored pending rows answer each other's verification, so a third party becomes a peer, reproduced live; the approval gate's re-check rests on it), a subtarget subscription receives an excluded resource (introduced by iteration 50), the approval notify after a failed write, rows approved before 3.16 but unverified refuse `approved=true`, the web UI's blank 403 on Approve; seven low. **Iterated 2026-11-09** (plan iterations 56-68, owner: "include all"): a verification is answered only by a row its host approved, and a pending row's peer gets no token (the mirror closed; two-actor test through the real handlers); exclusions under a subtarget dropped; the approval write conditioned on the row read and the peer told only when it landed; re-approving an approved row is a no-op; the 403 says why and the trust page marks unverified requests (browser walk); `modify_trust` re-verifies; the create's relationship/URL condition; 404/400 on the PUT; no row, no grant; a bounded second check; the bulk filter; Issue 12 documented; docs and spec. Full tier green, no recording changed. Emm's suite on `244ccb9`: the baseline (PostgreSQL 2 failed / 7406 passed, DynamoDB 3 failed / 54 passed). **Re-verified 2026-11-09** (`verifications/2026-11-09-peer-authorisation-fixes-reverify-8.md`, `244ccb9`; security review, code review, outside voice; Full tier green): reverify-7's issues fixed or accepted, the mirror closed on two counts. Open before the PR: the second check's deadline does not hold, `as_client(client_id)` views are now denied (undocumented), the anonymous first verification is unbounded (pre-existing); six low. **Iterated 2026-11-09** (plan iterations 69-75, owner: all nine; a client view resolves to its trust row): both verifications bounded to 15 s on a pool of their own (the first one too), `as_client` evaluated as its OAuth trust row, `modify_trust` tied to the row it re-verified, flags as text are flags, the PUT's relationship and base URI checked first, no token in a 202 answer (WT3 re-recorded), one evaluation per subtarget diff. Full tier green; Emm's suite on `20abc3a`: the baseline. **Re-verified 2026-11-09** (`verifications/2026-11-09-peer-authorisation-fixes-reverify-9.md`, `20abc3a`; security review, code review, codex and Claude; Full tier green): reverify-8's fixes land; security review no finding. Open before the PR: the `/meta` step of both verifications is unbounded (the changelog says otherwise), a slow peer pins a verification worker (pairing cheap to deny, shutdown can hang), text flags other than true/false now revoke an approval; four low. **Iterated 2026-11-09** (plan iterations 76-80, owner: all seven; other flag values raise `ValueError`): a verification's deadline reaches the socket and covers its `/meta` (real-socket tests), strict flags, one answer body for creation and re-pair, a client view is its own trust row resolved on first use with its subscriptions kept there, the subtarget filter logs denials and checks lists by bare name. Full tier green, no recording changed; Emm's suite on `16f5972`: the baseline. Before the PR: `/verify_implementation` |
| 1 | [`subscription-wire-baseline`](../plans/2026-11-06-subscription-wire-baseline.md): what a publisher sends and a subscriber holds today, recorded per flow, so every later change to it is a file diff; the existing subscription tests made to assert one outcome | None; found by the review of the other plans | Its spike, before plan 0 is redrafted; plan 0 merged, which lands the harness |
| 2 | [`subs-list-cache-lifetime`](../plans/2026-11-06-subs-list-cache-lifetime.md): per-request actors on the MCP path, a subscription list that caches empty | [`subs_list` cache asymmetry](subs-list-cache-asymmetry.md) | Plan 0, for the view filter its new accessor inherits; plan 1 |
| 3 | [`attribute-list-v2-port`](../plans/2026-11-06-attribute-list-v2-port.md): replica lists on the rank format, list diffs from REST and web-UI edits, diffs filtered before they are stored | [`ListAttribute` shift-loop design](attribute-list-shift-design.md) | Plan 1; ahead of plan 4 because the specification plan waits on it |
| 4 | [`email-as-creator-at-write-time`](../plans/2026-11-06-email-as-creator-at-write-time.md): one read per actor load under the email flag, the vouched rename as one transaction | [The vouched SDK rename](vouched-rename-one-transaction.md) | Plan 2 (it removes a keyword that plan adds) |
| 5 | [`spec-1-5`](../plans/2026-11-06-spec-1-5.md): specification 1.5 and a library that conforms to it, concurrent callback delivery, `FanOutManager` removed | None; it files `outbound-callback-backpressure.md` | Plans 0, 1 and 3 |

Todos these plans edit without closing: [MCP cache lifecycle](mcp-cache-lifecycle-and-revocation.md)
and [DynamoDB known-next](dynamodb-known-next.md) (plan 2);
[whole-list rewrite atomicity](whole-list-rewrite-atomicity.md),
[subscriber fault hardening](subscription-subscriber-fault-hardening.md) and
[the key-prefix scheme](prop-list-key-prefix-scheme.md) (plan 3);
[subscriber fault hardening](subscription-subscriber-fault-hardening.md) again
(plan 5).

### Dependencies between the plans

| Later plan | Needs | Kind | Why |
| --- | --- | --- | --- |
| `spec-1-5` | `attribute-list-v2-port` | Hard | It documents the list diffs that plan creates and edits the same functions after it |
| `email-as-creator-at-write-time` | `subs-list-cache-lifetime` | Hard as written | It removes the `rewrite_email` keyword that plan adds. Open: whether that plan needs the keyword at all |
| `subs-list-cache-lifetime`, `attribute-list-v2-port`, `spec-1-5` | `subscription-wire-baseline` | Hard, for regression safety | Their phases name the recordings they re-record and the ones that must stay identical |
| `subs-list-cache-lifetime` | `peer-authorisation-fixes` | Soft | One verification case (the accessor through a peer view) needs that plan's filter |
| `attribute-list-v2-port` | `peer-authorisation-fixes` | Hard | Its `remote:<peer>$aux` side bucket must be added to `actingweb-peer-state`'s whitelist (`maintenance/peer_state.py`, `_remote_peer`), or the command reports it as `remote-unknown` |
| `email-as-creator-at-write-time` | `subscription-wire-baseline` | Soft | It re-records nothing; the recordings confirm it changed nothing between two actors |

`attribute-list-v2-port` and `email-as-creator-at-write-time` need nothing
from each other and could swap places. Three plans in a row
(`subs-list-cache-lifetime`, `attribute-list-v2-port`, `spec-1-5`) edit the
same publisher and receiver code (`register_diffs`, `callback_subscription`,
`apply_callback_data`, `handlers/subscription.py`); a fault one introduces
and the next exposes is the case the gates below are for.

**The wire harness is built by the baseline plan's spike** (owner,
2026-11-07), not designed on paper in the security plan: the spike builds
the recorder and the two consumer-shaped apps, records a handful of rows on
both backends, repeats the runs, and writes a research note. The security
plan's Phase 0 then lands that harness as its test-only first commit and
records the fourteen flows its fix must leave unchanged; the baseline plan
stays its own PR after the fix. Both plans are redrafted after the spike.

**Before the first PR, in this order:** the Emm run on `master`
(`emm-suite-against-master.md`; done 2026-11-07); the wire spike (done
2026-11-07, `research/2026-11-07-subscription-wire-spike.md`, harness on
`spike/subscription-wire-harness`); the security plan's
research pass (done 2026-11-07,
`research/2026-11-07-peer-authorisation-research-pass.md`) (trust replacement, the access table with application rows,
what forged state survives on each backend); then `/update_plan` on the
baseline plan and on the security plan. The runs are sequential because
they share Docker and the local ports.

### Gates

1. **Before plan 0 starts:** [Emm's suite on `master`](emm-suite-against-master.md)
   has run and every failure is triaged. What is left is the baseline for
   the runs below. **Met 2026-11-07**; the baseline is the five tests in
   the research note.
2. **Before the PR opens, for each plan that changes library code:** Emm's
   suite on that plan's branch shows no failure the baseline did not have;
   the result is in the plan's verification document. Each such plan's last
   phase carries the checkbox; the baseline plan changes only tests and has
   none. **Met for plan 0 on 2026-11-08** (both backends, the baseline's
   failures only; `verifications/2026-11-07-peer-authorisation-fixes.md`,
   "Emm's suite on this branch"); `/iterate_plan` changes re-run it before
   the PR.
3. **Before any plan re-records a wire recording:** that recording has been
   shown byte-identical over repeated runs on both backends. One that is not
   cannot tell a regression from noise and stays out of the regression set.
4. **Before plan 2 starts:** the recordings shaped like Emm's use exist,
   the import flow (one subtarget suspended and resumed around list writes)
   included (`WD10.import`, from the security plan's Phase 0). Every row is
   in the regression set (one tier, owner 2026-11-07).
5. **In every commit of plans 2 to 5:** the only changed recordings are the
   ones `tests/integration/wire/rows.toml` assigns to that plan and phase
   (the only copy of that list, owner 2026-11-07; `verify_groups.py` checks
   it); any other is a regression to explain before the next phase.

## 1. High leverage

Bigger, designed, and each buys more than it costs. Both now have an
owner-chosen approach and a proposed plan (2026-11-06).

| Item | Impact of doing it | What it needs first |
| --- | --- | --- |
| [`subs_list` cache asymmetry](subs-list-cache-asymmetry.md) | Drops one **strongly-consistent Query per property write** for every actor with no subscribers, and `4 x peers` per page load on a consumer endpoint measured at p50 689 ms | **Planned for 3.16**: `thoughts/plans/2026-11-06-subs-list-cache-lifetime.md` (proposed). The cache-lifetime question is settled there: the MCP path builds its actor per request, and then the guard |
| [`ListAttribute` shift-loop design](attribute-list-shift-design.md) | Removes the **last instance** of the design that caused the production list corruption — `ListAttribute` still has, verbatim, what `ListProperty` had before the v2 format, and every peer replica's `insert`/`remove` diff is applied through it (`RemotePeerStore`), so it is on the subscription path, not a side class | **Planned for 3.16**: `thoughts/plans/2026-11-06-attribute-list-v2-port.md` (proposed). Sequenced before whole-list rewrite atomicity, with the documented window |

## 2. Real, not urgent

| Item | Impact of doing it | Why now |
| --- | --- | --- |
| [Grant enforcement per route and level](grant-enforcement-per-route.md) (**security, local only**) | A granted peer reads and writes only what its grant allows on every route (resources, lists, parents, push and pull alike) and a revocation deletes what it revokes | Owner decision 2026-11-09 after the trust-boundary audit: the second security plan, after the peer-authorisation PR's identity and approval fixes and before anything is pushed |
| [The web UI's trust page gaps](web-ui-trust-page-gaps.md) | The trust list shows whether the peer approved, the new-trust form is linked, and its errors and no-op redirects say what happened | Found 2026-11-09 by the browser walk of the peer-authorisation re-verification; library templates and `handlers/www.py`, none on the security path |
| [Deleting a client leaves other local actors' connections](client-deletion-leaves-other-actors-connections.md) | Ends the up-to-an-hour of access other actors keep after an SDK client's owner deletes it, and the inert rows it leaves | Found by the 2026-11-04 client-deletion audit (D2); server-local only. Needs a choice between a client check at token validation and a client-to-actors index |
| [Dynamic client registrations and their trust rows never expire](dcr-registrations-and-client-trust-rows-never-expire.md) | Stops the `mcp_clients` bucket, the global client index and the system-actor trust rows growing by one per connect forever (the per-registration trust-list walk is gone in 3.16; the retention design is the whole item) | Found 2026-09-21 by the consumer's connector audit; verified in code 2026-09-25. Needs a retention decision (never-authorized registrations can expire early; ones with live tokens cannot) before the sweep is designed |
| [MCP OAuth connector conformance follow-ups](mcp-oauth-connector-conformance-followups.md) | Nine audit items with no live failure behind them: loopback redirect URIs, RFC 8707 audience, CIMD, `openid-configuration`, the protected-resource `resources` flag, `resources/templates/list`, the never-sent `listChanged`, shared-registration name flips, a post-auth hook for app middleware | Same audit, verified 2026-09-25. Each is small; none is blocking a client today. Pick the ones a connector-directory submission requires when that is next attempted. CIMD moved up: claude.ai's connector dialog now recommends it (DCR fallback works, seen on rc1 2026-09-28) |
| [A conditional write retried by the SDK can report False for a write that landed](conditional-write-ambiguous-after-sdk-retry.md) | Closes the last documented way an unkeyed v2 list operation can silently duplicate (`append`, `extend`, `insert`) or double-remove (`pop`) under sustained backend trouble alone, no concurrent writer needed; keyed `append_once` and spanned heads already read their own write back | Traced, not reproduced, during the 2026-09-14 touch-fault triage; a strict `xfail` test pins the `append` duplicate. Needs a way to recognise an unkeyed plain write (its bytes are not unique to the call), plus whether PostgreSQL has an equivalent |
| [`set_description()`/`set_explanation()` still create the meta row unconditionally](meta-row-create-unconditional-for-description-writers.md) | Makes every v2 meta-row creation conditional, one creation path — closes the narrower last-writer-wins race the 2026-09-14 first-mutation fix left on `count_hint` (never on the description itself, and self-repaired by the next rank-counting mutation) | Found while implementing that fix; explicitly out of scope for the 3.14.7 patch. Needs a decision on whether the shared `_save_metadata()` creation branch (also used by v1's `create_if_absent=False` writers and `clear()`'s replace) routes through `_v2_create_meta_row()` or grows its own conditional create |
| [The full-state fallback corrupts a subscriber's replica](full-state-fallback-replica.md) | A subscriber whose publisher thinks it lacks resync stops getting list items twice and objects stored as JSON strings after a `resume()` | Recorded by wire row `WD12` (2026-11-07). Reached only for an older peer or a stale capability cache, since every 3.16 library advertises resync. The `ListAttribute` plan is the natural owner of the list half |
| [Subscription subscriber: recover cleanly from a store fault](subscription-subscriber-fault-hardening.md) | A subscriber that faulted mid-callback re-applies only what it has not applied, records the callbacks that finished, and a quiet subscription recovers without waiting for its next change | Filed 2026-10-29 when 3.16 made the publisher side spec-conformant (plan entry 32). Beyond the spec's minimum; a re-applied `append` can use 3.16's `ListProperty.append_once()` once each diff carries a stable key |
| [The vouched SDK rename is several writes, not one transaction](vouched-rename-one-transaction.md) | Concurrent renames of one actor, a fault past the commit point and a provider-id rename racing a sign-in all end coherently today, but not atomically; one cross-table write would make the rename all-or-nothing | **Planned for 3.16**: `thoughts/plans/2026-11-06-email-as-creator-at-write-time.md` (proposed), whose first phase is the one-transaction rename |
| [Promote `chain_id` to a top-level attribute with a GSI on DynamoDB](dynamodb-chain-id-gsi.md) | Makes SPA logout and revoke a query by chain instead of a scan of the two shared token buckets, so their cost stops growing with the number of live sessions | Raised by the PR #153 review; 3.15.1 accepted the scan (42 rows, about 3 RCU per call) with a WARNING at 1,000 rows per bucket. Trigger: that WARNING firing, or a partition projected past about 2,000 rows |
| [`output_schema` on `action_hook` never reaches MCP](action-hook-output-schema-not-visible-to-mcp.md) | Closes an ergonomic trap: an author who declares `output_schema=` or annotates a `TypedDict` return reasonably believes their MCP tool advertises `outputSchema`, and it does not | Merging the two metadata paths **by default** would newly advertise `outputSchema` for every TypedDict-annotated tool and break the ones that return no `structuredContent`, so it is not an independent decision. Decide it with the structuredContent research (`thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`, option C), not on its own |
| [Whole-list rewrite atomicity](whole-list-rewrite-atomicity.md) | An interrupted `compact()` stops leaving a double of the list that `--repair` will not itself remove | Two designs died under adversarial review and the file carries the constraints they established — chiefly that `fetch_all_including_lists` is a paginated Query, not a snapshot. Do not propose a third without reading them. Reachability is low (`compact()` is an operator action) and the current failure is loud, which is what makes the wait defensible |
| [v2 list access follow-ups](v2-list-access-verification-followups.md) | The bulk response counts for duplicate deletes of a batch-created index credit each request entry | Noise-level; revisit only if a consumer reads these counts strictly |
| [Postgres parallel CI flakiness](ci-postgres-parallel-flakiness.md) | Removes the instability the hang watchdog only bounds — a fixed-`creator` test racing two process-global singletons, a full alembic chain per xdist worker, and an unexamined `--dist loadgroup` requirement | Test-infrastructure reliability only, not correctness. Nothing has been instrumented for it |
| [NFC and NFD spellings of one name are distinct keys](unicode-normalisation-of-names.md) | Records that Unicode normalisation of names is a separate question from the (landed) glob escapes: a rule that visibly covers a namespace does not cover a byte-different spelling | A normalisation at the permission choke points and the name write path, plus a migration of stored names |
| [MCP batches are declined; 2025-03-26 requires receiving them](mcp-batch-receive.md) | Full conformance with a protocol revision the server still advertises and assumes for header-less requests | No client we serve is known to batch. Choose between implementing receive (status semantics for mixed results are open) and dropping 2025-03-26 from the supported versions, which is a compatibility decision |
| [`/sessions` has no library support](sessions-endpoint-and-advertised-options.md) | Gives applications a hook to implement `/sessions` like `/actions` and `/methods`; the advertised-tag audit landed in 3.16 | A session-model decision (callback URI vs mirrored URL, WebSocket, MCP mapping) |

## 3. Blocked or waiting on someone else

Nothing to do until the named thing happens. Listed so they aren't mistaken for
neglected work.

| Item | Waiting on |
| --- | --- |
| [A `prop#`/`list#` key-prefix scheme](prop-list-key-prefix-scheme.md) | Also the **next major version bump**. Raises or removes the 1 MB per-partition DynamoDB Query ceiling — the consumer's largest list measured at 964 KB in one page, 94% of the limit — and is the only place the remaining out-of-band payload problem and the attribute composite-key collision can be fixed. The legacy GSI is gone (3.16), so the scheme is designed against the lookup-table-only shape |
| [Dual-era MCP support](mcp-2026-07-28-dual-era-support.md) | A client we serve going **modern-only**. A dual-era client needs nothing from us, so "supports 2026-07-28" is not the signal — a *sustained* stream of 400/`-32600` from one origin is, and the library now fires that criterion itself. Also blocked-adjacent: `actingweb_mcp`'s `require_mcp_auth_for_init` middleware silently becomes a no-op under the modern revision |
| [Drop Python 3.11 after its end of life](drop-python-3-11-after-eol.md) | **October 2027**, CPython 3.11's end of life (owner's policy, 2026-11-04: support what upstream maintains). Then the first minor raises the minimum to 3.12, renaming the required CI contexts in the same change |
| [AI agent discoverability follow-ups](ai-agent-discoverability-followups.md) | Resources this environment does not have: a Context7 account, a real OAuth2 provider and MCP client, a throwaway consumer repo |

## 4. Registers — deferred items, not schedulable work

Each holds items that were deliberately cut, with the rationale and the trigger
that would justify pulling one forward. **A trigger that hasn't fired means the
register is working**, not that it's stale. Their value is stopping decisions
being re-litigated.

| Item | What it holds |
| --- | --- |
| [DynamoDB known-next](dynamodb-known-next.md) | Six items deferred from the v3.13 scalability plan — the remaining unbatched delete loops, the `consistent_read` audit's ~36 surviving sites, `SubscriptionDiff` seqnr ordering, import-time table-name freezing, GSI-based secret uniqueness, lookup-table write amplification |
| [MCP cache lifecycle and revocation](mcp-cache-lifecycle-and-revocation.md) | Cross-process invalidation (the large one), trust-freshness policy, `_mcp_client_info_cache`'s client-supplied key, registration not hard-failing on trust-creation failure, module-global cache keys assuming one app per interpreter, and the trust permission cache having no TTL (sections 1-3, 5, 6 and 8; 4 and 7 were closed by the 3.16 roll-up) |

---

## Conventions

`thoughts/README.md` is authoritative for the directory. One thing worth
repeating because it is easy to get wrong here:

- **`mcp-2026-07-28-dual-era-support.md` is not a dated file.** `2026-07-28` is
  the MCP **spec revision** the todo is about, part of the slug. Don't "fix" it
  to an undated name and don't read it as a write date.
