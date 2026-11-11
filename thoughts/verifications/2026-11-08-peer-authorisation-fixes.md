# Verification: callers reach only what is theirs on `/callbacks`, `/permissions` and `/subscriptions`

**Date:** 2026-11-08
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md,
thoughts/research/2026-11-07-peer-authorisation-research-pass.md
**Branch:** fix/3.16.0-peer-authorisation (local; not pushed, owner rule)
**Commit:** 7a43466

The whole plan, Phases 0 to 5 and the four commits folding the per-phase
outside-voice reviews. The record written during implementation,
`thoughts/verifications/2026-11-07-peer-authorisation-fixes.md`, holds the
pre-fix runs, the changed tests, every per-phase review and Emm's suite run;
this document does not repeat it. No feature document; no phase changes a
page a user sees (a demo docstring only).

## Automated Check Results

- **Browser QA:** N/A, no UI phase.
- **Second opinion (outside voice):** codex (`codex exec -s read-only`,
  outside the sandbox) and a fresh-context reviewer, on `d1bf09d..7a43466 --
  actingweb`, briefed to attack across phases. Six findings; see Issues
  Found 1 to 6.
- **Built-in security review** (the `/security-review` flow, one pass and a
  confidence filter): no finding at confidence 8 or above. Noted below the
  bar: a "verifying" creation proves only control of the requester's base
  URI, not the peer id it names (Issue 4 takes it further).
- **Built-in code review (high,** `master...fix/3.16.0-peer-authorisation`**):**
  ten findings; two repeat Issues 3 and 4, one is the plan's decided
  behaviour, the rest are Issues 7 to 11. See "Code review".
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (530 files).
- `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
- `poetry run python tests/integration/verify_groups.py`: 54 groups
  documented; the wire rows registry consistent.
- `make test-all-parallel`, DynamoDB: **6006 passed**, 60 skipped, 1
  xfailed (exit 0).
- `make test-all-parallel`, PostgreSQL: **5803 passed**, 263 skipped, 1
  xfailed (exit 0).
- `sphinx-build -W ...`: build succeeded.
- Emm's suite on this branch (2026-11-08, previous record): PostgreSQL 2
  failed / 7406 passed, DynamoDB 3 failed / 54 passed, the `master`
  baseline's failures by name.

## Phase Verification

### Phase 0: the wire harness and the flows the fix must not change - VERIFIED

- `tests/integration/_wire.py`, `conftest.py` (`wire_app`, `wire_peer_app`,
  `wire_other_app`, `wire_pair` with `add_peer`/`add_actor`),
  `test_harness.py` (`subscriber` and `subscriber_adopted` types),
  `test_wire_peer_paths.py`, `wire/rows.toml`, `verify_groups.py`, the CI
  step: present as planned, with the deviations the plan records
  (`topologies` key, `WIRE_RECORD` taking row ids, trust rows and
  permissions in the snapshot from Phase 0).
- Every later phase changed only the recordings `rows.toml` assigns to it:
  `WA17` (Phase 1 fold), the three `.subscriber` rows (Phase 2), `WT4`
  (Phase 3 fold); the `.subscriber_adopted` rows and all others are
  byte-identical (git history of `tests/integration/wire/`).

### Phase 1: `/callbacks` - VERIFIED

The security properties, each pinned by a test and its assertion:

- Unauthenticated callbacks refused: `tests/test_peer_binding.py:279`
  (`status_code == 401`, `"WWW-Authenticate" in headers`, replica empty);
  wire `WA1`-`WA3` (401).
- The peer branches admit only the named peer, before any lookup:
  `tests/test_peer_binding.py:325` (C, an admin peer, the creator: 403 on a
  real and an unknown subscription, the permission callback and the DELETE;
  nothing stored or deleted); wire `WA5`, `WA6`, `WA9`.
- The low-granularity fetch goes to the stored base URI:
  `tests/test_peer_binding.py:464` (the HTTP client fails the test on any
  other URL; `fetched == [expected]`); wire `WA8` (`wire_other_app`
  receives nothing).
- A subscriber cannot post to its publisher: `tests/test_peer_binding.py:410`;
  wire `WA10`.
- Reserved names 403 with no hook, a `*` hook included:
  `tests/test_peer_binding.py:575`; wire `WA11`.
- Timestamps beyond the skew window 400: `tests/test_peer_binding.py:508`;
  wire `WA17`.

Deviations, accepted and recorded in the plan: 401 for any request without
an `Authorization` header (not only a redirect); 403 for an unknown
subscription id; the skew window replacing the clamp (owner).

### Phase 2: `/subscriptions`, `/permissions`, `/trust/<type>/<id>`; the method rule - VERIFIED

- Another peer refused on every subscription handler, nothing changed:
  `tests/test_peer_paths_binding.py:161`; wire `WA12`.
- A GET-only row refuses PUT, DELETE and their `?_method=` forms:
  `tests/test_peer_paths_binding.py:227`; wire `.subscriber` rows.
- Trust sites bound (a row admits C, only the binding refuses):
  `tests/test_peer_paths_binding.py:376`; a peer cannot approve its own row:
  `:519`; wire `WA16`.
- The root listing shows a peer its own: `tests/test_peer_paths_binding.py:283`;
  wire `WA18`.

### Phase 3: a trust request for an existing peer - VERIFIED, with Issues 1 to 4

- An unproven request changes nothing: `tests/test_trust_re_pair.py:162`
  (no bearer, a bearer nobody holds, another peer's: 403, state unchanged).
- The initiator sends nothing to a URL other than the stored base URI:
  `tests/test_trust_re_pair.py:415` (`post.assert_not_called()`).
- A squatter cannot promote its own row: `tests/test_trust_re_pair.py:594`.
- A creation never replaces a row: `tests/test_trust_re_pair.py:548`.
- The creator's local delete contacts nobody: `tests/test_trust_re_pair.py:387`.
- Wire `WT1`-`WT5`.

The property holds for a caller that does not hold the trust's secret. It
does not hold against an `admin` peer, which can read another peer's
secret (Issue 1), and the swap is not atomic on DynamoDB (Issue 2).

### Phase 4: `actingweb-peer-state` - VERIFIED, with Issue 5

`actingweb/maintenance/peer_state.py`, the script entry, the guide section,
`tests/test_peer_state_command.py`, `tests/integration/test_peer_state_flow.py`
as planned (kinds, strict reads, `--rps`, exit codes, whole-name
comparisons).

### Phase 5: documentation, records, Emm - VERIFIED

The changelog's `SECURITY`, `CHANGED` (**Breaking:**), `ADDED`, `FIXED`;
the migration guide's item 18 and section; the specification notes; both
access-control guides (`grep -rln '"subscriptions/<id>/<subid>", "DELETE"'`
lists both); the trust and reference pages; the demo docstring; spec-1-5's
T6; the baseline plan's "What Already Exists".

**The consumer message** (Emm's adoption items, verification of
2026-11-07, "Phase 5") is still accurate after implementation; its items:
the two rows on `subscriber`; the re-pair recipes; a fixed preview domain;
`actingweb-peer-state` after every instance runs 3.16; the reserved
`permissions` name and the `status` hook answering any authenticated caller;
the second subscription Emm's connect flow creates after a re-pair answering
201. Issue 1 adds one line to it if fixed (an admin peer no longer reads
another peer's secret).

## Code review

The built-in review's findings, against the code:

- A lost re-pair answer splits the secrets (`actor.py:1725`): Issue 3.
- A verified squat is permanent (`actor.py:2086`): Issue 4.
- "The callback DELETE was not limited to subscriptions the actor made"
  (`interface/subscription_manager.py:657`): **not an issue.** On the
  DELETE the row is the publisher's and the subscriber is the rightful
  sender (plan, "A subscription callback is accepted only for a
  subscription this actor made … not on the callback DELETE"); `WC3`
  records it. The peer binding applies first (`tests/test_peer_binding.py:325`).
- The permission ordering mixes clocks, and old rows compare as strings
  (`handlers/callbacks.py:362`): Issue 7.
- The demo's `sms_webhook` and `payment_webhook` docstrings still tell the
  reader to register them with a provider (`examples/demo/shared_hooks/app/callback_hooks.py:103`): Issue 8.
- `prune` removes a trusted peer's data when the actor holds no
  subscription to it (`maintenance/peer_state.py:214`): the rule the plan
  specified; the library itself removes `remote:<peer>` when the last
  subscription to the peer goes (`actor.py`, `delete_subscription`), so
  data without a subscription is already transient. Accepted; Issue 11
  asks the guide to say so.
- The permission hook is told `POST` for a PUT (`handlers/callbacks.py:451`),
  and a permission body that is not an object answers 500
  (`handlers/callbacks.py:328`): Issue 9.
- `_match_access_row` has untyped parameters (`auth.py:795`), against the
  project's rule that every function is typed: Issue 10.

Todos: the plan closes none; its one deferral, the full-state fallback that
`WD12` recorded, is `thoughts/todo/full-state-fallback-replica.md` with an
`INDEX.md` row.

## Remaining Tasks

- [ ] Address Issues 1 to 3 (`/iterate_plan`) before the PR opens: they are
      holes in what this PR claims.
- [ ] Decide Issue 4 (owner): a verified squat now blocks the real peer for
      good.
- [ ] Issue 7 (`/iterate_plan`): a revocation can be dropped.
- [ ] Issues 5, 6, 8 to 11: fold or accept.

## Issues Found

### Issue 1: an `admin` peer reads another peer's secret and becomes that peer
**Severity:** High
**Description:** The per-peer trust GET returns `secret` and
`verification_token` to an `admin` peer (`handlers/trust.py:690-693`, "this
response keeps `secret` and `verification_token`"; `config.py`
`("admin", "trust", "", "a")`; the admin exemption from `path_peer` in
`auth.py`). With X's secret, admin peer D authenticates as X: it passes the
binding on `/callbacks/subscriptions/<X>/…` (the owner's "no admin on
`/callbacks`" rule does nothing), and a `POST /trust/<rel>` with `id=X` is a
proven re-pair, so `replace_trust_secret` swaps in D's secret and X is
locked out for good. D can also `PUT /trust/<rel>/<X>` a new `baseuri`.
Reading the secret was decided as unchanged in Phase 2 ("exempt by
decision"); the lockout through the re-pair is new with Phase 3.
**Location:** `actingweb/handlers/trust.py:690-693`, `actingweb/auth.py`
(`check_authorisation`, the admin exemption)
**Recommendation:** Redact `secret` and `verification_token` from the
per-peer GET for every peer caller other than the path peer (admin
included); refuse a `baseuri` change on another peer's row from a peer
caller. Owner decision, since it narrows the Phase 2 admin exemption.

### Issue 2: the re-pair's write is not atomic on DynamoDB
**Severity:** High
**Description:** `Trust.modify` on DynamoDB loads the row and saves the
whole item (`db/dynamodb/trust.py:314-315`, `self.handle.save()`, no
condition). `_record_trust_usage` does it on every authenticated bearer
request (`auth.py:198-201`). A request authenticated with the old secret
that loads before the swap and saves after it writes the old secret back:
the initiator holds the new one, the two sides disagree, and every later
call answers 403, with nothing logged. A swap racing the owner's delete
recreates the row on DynamoDB; on PostgreSQL the `UPDATE` touches no row,
returns True, and the read-back answers 403. The whole-row write and the
usage race are older than this plan; the secret swap makes them a split
pairing.
**Location:** `actingweb/actor.py` (`replace_trust_secret`,
`_finish_re_pair`), `actingweb/db/dynamodb/trust.py:314-315`,
`actingweb/auth.py:198-201`
**Recommendation:** A conditional swap: DynamoDB `UpdateItem` of the secret
and token only, conditioned on `attribute_exists(id)` and `secret =
:current`; PostgreSQL `UPDATE … WHERE secret = %s` with a rowcount check;
the usage write as an update of its own fields only.

### Issue 3: a lost re-pair answer splits the secrets, and the log says nothing changed
**Severity:** Medium
**Description:** When the receiver commits the swap and the answer is lost
(timeout, dropped connection, a 5xx after the commit), the initiator keeps
its old secret and logs "the existing trust is unchanged"; its next re-pair
sends the old bearer and answers 403. Recovery is a delete on both sides.
**Location:** `actingweb/actor.py`, `create_reciprocal_trust` and its async
twin, the re-pair branch
**Recommendation:** On no answer or a 5xx, probe with the new secret
(`GET <baseuri>/trust/<rel>/<own id>`) and store it on a 200; otherwise log
that the peer may have accepted, with the recovery.

### Issue 4: a verified squat is now permanent
**Severity:** Medium
**Description:** `create_verified_trust` verifies the requester against the
requester's own base URI and never checks that the base URI serves the
claimed id (`actor.py`, the verification GET to `baseuri + "/trust/" +
relationship + "/" + self.id`). An attacker naming X's id with its own
server is stored verified (and approved under auto-accept). Since Phase 3 a
verified row is never replaced, so the real X is refused until the owner
deletes the row; before, X's own request overwrote it.
**Location:** `actingweb/actor.py` (`create_verified_trust`)
**Recommendation:** Owner decision. Bind the claim: fetch `<baseuri>/meta/id`
(or require the base URI to end in `/<peerid>`) before setting `verified`;
or accept and document the owner's `?notify=false` remedy.

### Issue 5: `prune` keeps a forged permission copy for a trusted peer
**Severity:** Low
**Description:** A pre-fix unauthenticated callback could store a current-
dated permission copy for a peer the actor trusts (pre-fix `WA2`). The
command removes only rows for untrusted peers or stamped in the future
(`maintenance/peer_state.py:197-205`), so this one stays until the peer's
next permission change.
**Location:** `actingweb/maintenance/peer_state.py:197-205`
**Recommendation:** An option that removes every `_peer_permissions` row
(they are rebuilt from the next callback or query).

### Issue 6: `FanOutManager` can still send an unauthenticated callback
**Severity:** Low
**Description:** It posts to the stored `callback_url` and adds the bearer
only when a trust is found (`fanout.py:513-515`); a 3.16 receiver answers
401. Nothing in the library calls it; it is public API.
**Location:** `actingweb/fanout.py:513-515`
**Recommendation:** Refuse delivery without a trust and secret, and build
the URL from the trust's stored base URI.

### Issue 7: the permission ordering compares the sender's clock with the receiver's
**Severity:** Medium
**Description:** A stored copy written by the receiver's own fetch
(`fetch_peer_permissions`, `peer_permissions.py`) carries the receiver's
time; a callback carries the sender's. The callback branch ignores an
update "older" than the stored copy (`handlers/callbacks.py:362`, the
early return), so a sender whose clock is behind sees its revocation
answered 204 and dropped: nothing stored, nothing deleted, no hook, no
retry. Rows stored before 3.16 keep the sender's format (`Z`, another
offset) and compare as strings, so newer updates can be ignored for hours;
`actingweb-peer-state` parses them and does not flag them.
**Location:** `actingweb/handlers/callbacks.py:362`,
`actingweb/peer_permissions.py` (`store_permissions`, the string compare)
**Recommendation:** Keep the sender's timestamp in its own field and order
callbacks only against the sender's previous timestamp; compare parsed
datetimes, not strings.

### Issue 8: the demo's webhook hooks describe an anonymous provider call
**Severity:** Low
**Description:** `sms_webhook` and `payment_webhook` docstrings tell the
reader to register `/callbacks/<name>` with Twilio or Stripe; since 3.16
such a call answers 401 (the changelog says so; the docstrings do not).
**Location:** `examples/demo/shared_hooks/app/callback_hooks.py:103` and
the payment hook
**Recommendation:** The same note as `email_verify`: an application route,
not `/callbacks`, until the specification plan's opt-in.

### Issue 9: two small gaps on the permission branch
**Severity:** Low
**Description:** A PUT is authorised as PUT, but the `permissions` hook is
told `POST` (`handlers/callbacks.py:451`); a JSON body or `data` that is
not an object answers 500, not 400 (`handlers/callbacks.py:328`).
**Recommendation:** Pass the real method; check the body's shape as the
subscription branch does.

### Issue 10: `_match_access_row` is untyped
**Severity:** Low
**Location:** `actingweb/auth.py:795`
**Recommendation:** Annotate its parameters.

### Issue 11: the guide does not say what `remote-data` removes for a trusted peer
**Severity:** Low
**Description:** `prune` removes a trusted peer's `remote:<peer>` data when
the actor holds no subscription to it, by the plan's rule; an application
that stores peer data through `RemotePeerStore` without subscribing would
lose it.
**Recommendation:** Say it in the guide's "Peer State Written Before 3.16".

## Overall Assessment

Every hole the plan set out to close is closed, and the tests and wire
rows named above demonstrate it against a caller that does not hold the
trust's secret: unauthenticated callbacks, cross-peer access through any
access row, writes through GET rows, the secret sent to a URL from the
callback body, and the trust row replaced by a creation request. The Full
tier is green on both backends, the recordings changed only where
`rows.toml` allows, and Emm's suite shows no regression.

It is not ready for the PR as is. The adversarial pass across the phases
found that an `admin` peer, which still reads other peers' secrets, can use
the new re-pair to take a trust over (Issue 1), and that the swap races the
usage write on DynamoDB (Issue 2); a lost answer can split a pairing
(Issue 3), the "never replace a verified row" rule makes a verified
squat permanent (Issue 4), and the permission ordering can drop a
revocation (Issue 7). Issues 1 and 4 need the owner's decision;
`/iterate_plan` should take Issues 1 to 3 and 7 before the PR opens, and
fold or accept the low ones.
