# Research: validating 3.16 before its tag

**Date:** 2026-11-18
**Plan:** [`plans/2026-11-15-3-16-release-validation.md`](../plans/2026-11-15-3-16-release-validation.md)
**Checked against:** `master` at `da6de67` (the library code of the branch
`release/3.16.0-release-validation` until a phase changes it), `v3.15.1`,
and `../actingweb_mcp` `main` at `c1be751c`.

The working note of the plan: each phase adds its tables here. It holds
outcomes and status lines only: no secret, token, passphrase or account
address.

## Emm's suite: the new baseline (Phase 1)

The adoption worktree (`../actingweb_mcp/.claude/worktrees/emm-3-16`, branch
`actingweb-3-16-adoption`) was fast-forwarded from `dd5e2ccb` to Emm's local
`main`, `c1be751c` (no fetch, nothing committed or pushed). Its four
uncommitted edits were saved as a patch first and put back: `application.py`
and `scripts/test-backends.sh` re-applied unchanged, the path line in
`pyproject.toml` redone on `main`'s file, `poetry.lock` regenerated. The
library worktree (`.claude/worktrees/master-5a7e07f`) was pointed at
`da6de67`. `git status` in Emm's worktree shows those four files and nothing
else.

Environment 9: the database migrated to the library's head, then
`actingweb-unique-creators creator-to-email` (dry run, then `--apply`:
scanned 1, nothing to move), then the preview server.

| Lane | Result | Failures by name |
| --- | --- | --- |
| PostgreSQL, `scripts/with-preview-env.sh 9 poetry run pytest --timeout=180 --deselect tests/test_dependency_pin_guard.py`, sequential | 2 failed, 7,698 passed, 14 skipped, 185 deselected | `tests/test_dynamodb_iam_coverage.py::test_role_grants_every_dynamodb_action_the_backend_uses`; `tests/test_stripe_integration.py::TestSubscriptionCreation::test_create_subscription_proceeds_with_expired_apple_subscription` |
| DynamoDB, `scripts/test-backends.sh 9` | 3 failed, 57 passed | `tests/integration/test_dynamodb_operation_profile.py::TestPerActorReadsUseQueryNotScan::test_property_list_fetch_issues_query_and_no_scan`; `tests/integration/test_dynamodb_operation_profile.py::TestTableExistenceChecksAreMemoised::test_repeated_construction_issues_no_describe_table`; `tests/integration/test_restore_actor_dynamodb.py::TestSnapshotThroughTheDbLayer::test_full_force_import_caps_and_confirms_the_wipe` |

**The baseline for AC-10 is these five names**, with
`tests/test_dependency_pin_guard.py` deselected while the path form is in.
All five are in the old baseline
(`2026-11-07-emm-suite-against-master.md`, "Baseline"). The sixth failure of
the earlier runs, Emm's date-dependent `tests/test_trial_state_pure.py`
case, does not fail on Emm's `main`. Emm's `main` has about 290 more tests
on the PostgreSQL lane than `dd5e2ccb` had (7,698 passed against 7,405) and
none of the new ones fails.

This is also the first run that covers `spec-1-5`'s four iteration commits
and the last commits of `3-16-pre-rc1-fixes`: no failure is theirs.

## The library version leaves the wire recordings (Phase 1)

Eight recordings carried `"version": "3.15.1"`: an actor's `/meta` in `WT1`,
`WT3` and `WT4` (two topologies each) and the MCP `serverInfo` in `WG16` and
`WG17`. Gate 3 first: the eight passed twice on DynamoDB and twice on
PostgreSQL unchanged. `tests/integration/_wire.py` now records the value as
`<library-version>` when it equals the installed library's version (any
other value under a `version` key is recorded as it is). The eight were
re-recorded (ten lines changed, each the version line) and passed twice on
each backend. With `actingweb/__init__.py` temporarily at `9.9.9` the eight
still passed, which is AC-22's proof ahead of the bump.

## The inventory (item 1, AC-1)

[`2026-11-18-3-16-release-validation.inventory.md`](2026-11-18-3-16-release-validation.inventory.md)
has it: 301 rows, one per consumer-visible change, from the 18 merges of
the 28 that touched `CHANGELOG.rst` (the other ten are documentation, CI
and records). By how a row meets an upgrader who did nothing:

| How it meets them | Rows |
| --- | --- |
| refuses to start | 14 |
| an error at run time (an exception, a 4xx or 5xx that was a 2xx) | 79 |
| silent (behaviour differs with no error) | 113 |
| irreversible (a 3.15.1 process cannot read what the release wrote) | 3 |
| none (additive, or a fix nobody relied on) | 89 |
| not classed in one word | 3 |

**The three irreversible rows**, and what an unchanged application has to
do to produce each (corrected after the owner's decision; see the end):

- an attribute list in the old layout is converted on its first write, and
  a 3.15.1 process on the same store then reads it as empty. **Every
  application with attribute lists, and every subscriber with a replica,
  meets this one by upgrading and nothing else;**
- a list item over the span threshold on DynamoDB is stored across rows in
  `{actor_id}$aux`; a 3.15.1 reader returns the envelope as the item, and
  its actor delete leaves the side partition. An unchanged application
  produces one only by writing an item between 390,000 bytes and the
  400 KB row cap (3.15.1 refused anything larger), or by now writing the
  larger items it could not store before;
- the first `append_once` on a list (stated in its entry). The method is
  new, so calling it is the opt-in.

**The fourteen that refuse to start**: creator uniqueness on by default and
enforced by the database (two rows, plus the DynamoDB role's new action);
the legacy reverse lookup removed and its readiness check; the
`DbPropertyLookup` readiness functions, the nine attribute methods and
`rename_creator` for a custom backend; Alembic revision `a7b8c9d0e1f2`;
`creator-to-email` under `with_email_as_creator`; `pyjwt >= 2.15`;
`BatchGetItem` on the lookup table; `FanOutManager` and its settings;
`CallbackOauthHandler`.

Four rows had no changelog entry; each has one now (below). 93 rows have no
section in the guide: Phase 4's list, in the inventory's last column.

## `CHANGELOG.rst`, `Unreleased`, made correct (item 1)

Entries by category, at `da6de67` and after this phase:

| | `SECURITY` | `REMOVED` | `CHANGED` | `ADDED` | `FIXED` |
| --- | --- | --- | --- | --- | --- |
| before | 32 | 4 | 115 | 38 | 85 |
| after | 32 | 5 | 116 | 42 | 85 |

**`SECURITY`: 32 before, 32 after; none deleted, none moved, the order
unchanged.** Three were reworded in place, each a name or a pointer and no
request detail: the trust-request entry named `create_peer_trustee`, which
never existed (`Actor.get_peer_trustee`); the client-credentials entry
named `ActorInterface.oauth_clients.generate_access_token`
(`OAuth2ClientManager.generate_access_token`); the address-squatting entry
said a user without a verified address "cannot do that yet", which the
emailed code of the same release contradicts.

What changed, by kind (line numbers at `da6de67`):

- **Wrong against the code** (each checked at the line the finding names):
  the `strict` default (2084, 2661: `True`, not `False`); PostgreSQL
  raising `DbError` where two entries said it returns `False` (2134, 2162,
  with the guide's sentence and the `Actor.modify` docstring); "eleven"
  fault entries, of which ten remain (1993); the form client's 403 (2181);
  an admin peer sending the trustee handoff, which specification 1.5's
  entry forbids (1183, and the guide); the receiver's answer to a spanned
  reference (2227); `check_ready()` as one or two checks where it runs four
  (2600, 1818); "the fourth custom-backend requirement" (1705); a lead that
  read as its opposite (3488); `actingweb-deletions` announcing a hook it
  never runs (2078); `POST /properties/<name>` (1633); a pointer that said
  "below" (1950).
- **Names that never shipped**, removed from the text:
  `PermissionEvaluator.evaluate_property_with_exclusions` (1647) and
  `actingweb.property_list.fit_full_state` (1375, and the guide) were added
  and removed inside the release (`git grep <name> v3.15.1 -- actingweb`
  is empty for both).
- **Changes with no entry**, added: the keywords a custom trust store takes
  on `modify` and `create`; `delete_all_of_actor`, the suspension store's
  `delete_all` and `DbActorList.iter_rows` for a custom backend;
  `actingweb-deletions resume --no-notify-peers`; `Actor.deferred_callbacks()`,
  `HookRegistry.allows_anonymous_callback()`, `ListProperty.append_indexed()`;
  the five other names of `actingweb.fanout`,
  `actingweb.db.verify_tables.lookup_mode_enabled` and
  `MCPHandler.validate_google_token_and_check_actor_email` under `REMOVED`;
  the positional shift in `with_subscription_processing()`; a rollback note
  on dropping the old GSI.
- **Inline `Breaking:` marks** (941, 949, 1565, 1846): the two under
  `REMOVED` and the one inside an entry that already leads with it became
  plain "Check" sentences; `BaseHandler` requiring `config` and the
  `verify_tables` keywords became an entry with its own **Breaking:** lead.
- **One entry led with "New:" under `CHANGED`** (1601): moved to `ADDED`,
  less the keyword its neighbour already states.
- **Fifteen `FIXED` entries ended in internal review tags** ("(B1)" to
  "(BS)"): removed.
- **Eleven entries had no bold lead**: each has one. Two bullets on the
  actor delete's side-partition sweep (2255, 2323) are one entry.

**Not done here, and why.** The inventories name some twenty pairs of a
`CHANGED` entry and a `FIXED` entry on one change. They were read: in each
the `FIXED` entry states the symptom and the `CHANGED` entry the new
behaviour, from the same plan, and neither repeats a **Behavior change:**
sentence, so they stay two entries. Eleven of specification 1.5's entries
change a wire shape or a status and lead with **Behavior change:** rather
than **Breaking:** (981, 1013, 1034, 1072, 1079, 1089, 1095, 1106, 1122,
1140, and 1148, which stops start-up): whether each is **Breaking:** is the
compatibility table's outcome below, so they are re-marked in Phase 4, with
the section's order. One possible inconsistency is unverified:
`Actor.request_resync` "with synchronous callbacks ... records the ones it
misses" (2503) beside "whenever the write waited" for a resume (1005); the
two are different calls and the docstring agrees with the first.

## 3.15.1 and this release as peers (item 6, AC-14)

Three sources. The specification's 49 "Changed:" lines and the recordings'
`reason` lines are classed in
[`2026-11-18-3-16-release-validation.wire.md`](2026-11-18-3-16-release-validation.wire.md):
of the 49, 24 say what 3.15.1 already did, 14 change what is sent, 9 what
is accepted, 2 are additive. The recordings cannot stand in for 3.15.1:
every first recording is from 2026-11-07 or later. The release decides
nothing by a peer's option tag and never compares the announced protocol
version (`1.0` at 3.15.1, `1.5` here).

**The live pair.** `scripts/live_pair.py` built the same application twice:
under a fresh Python 3.11 virtualenv with `actingweb==3.15.1` from PyPI
(labelled `v3.15.1`), and under this branch on Python 3.14 (labelled
`release`; both report `3.15.1` at `/meta` until the bump, so the label is
what tells the captures apart). DynamoDB Local, one table prefix per side,
ports 5701 and 5702 on `127.0.0.1`, synchronous callbacks, devtest off. The
release side went through its first run (start, `UniqueCreatorNotReady`,
`actingweb-unique-creators enable --apply`, start). Captures and results are
outside the repository.

| Flow | 3.15.1 initiates toward the release | the release initiates toward 3.15.1 |
| --- | --- | --- |
| trust creation and approval | completes: 201, both approve, both rows approved, peer-approved and verified | completes, the same |
| permission exchange | completes: the grant is stored by the subscriber | completes |
| subscription creation | completes: one row on each side | completes |
| push callbacks | completes: the replica holds the pushed value | completes |
| pull | completes: `sync_peer` succeeds, one diff processed | completes |
| suspension | completes: a write during suspension does not reach the replica | completes |
| resync | completes: after the resume the replica holds that value | completes |
| list diffs | completes: seven list operations, the replica's list matches | completes |
| deletion | completes: subscription and trust deleted, the other side's rows gone | completes |

18 cells, 18 complete. Across them neither side answered a peer's request
with a 4xx or 5xx.

**Probes beyond the nine flows**, each also run with 3.15.1 as its own peer
and the release as its own peer, so that a difference is read against what
a 3.15.1 pair already did:

| Probe | 3.15.1 with itself | 3.15.1 subscribes to the release | the release subscribes to 3.15.1 | the release with itself |
| --- | --- | --- | --- | --- |
| a text value, an object and a delete, whole-target subscription | replica right | right | right | right |
| a write below a property (`PUT /properties/doc/a`) | the replica keeps only the changed part until a poll rebuilds it | right | only the changed part, until a poll rebuilds it | right |
| a text value, a subscription to that one property, `high` and `low` | 3.15.1 sends no callback for it; nothing stored | **3.15.1 answers the release's callback 400** (`'str' object has no attribute 'get'`); nothing stored | 3.15.1 sends no callback for it; nothing stored | stored |
| the same with `none` | the poll raises the same error | the poll raises the same error | stored after the poll; right after resume and delete | the same, right |
| a second trust request for a peer already trusted | 201; the rows go back to pending | **408 to the caller; 3.15.1 deletes its own row; the release keeps its approved row** | 201; 3.15.1's row goes back to pending and unverified, the release's keeps `approved` and loses `peer_approved` | 201; both rows stay approved (a re-pair) |

**What the pair shows.**

- **One break a 3.15.1 pair did not have: a second trust request from a
  3.15.1 application.** The release refuses it (403, the re-pair rule) and
  3.15.1 then deletes its own row while the release keeps its approved one.
  It traces to the `SECURITY` entry on trust requests (lead at line 247 of
  `da6de67`'s changelog), so by the owner's rule it can only be accepted.
  The recovery is the release owner's: delete the trust there
  (`DELETE /trust/<rel>/<peer>?notify=false`) and pair again.
- **A second difference, with the same end state as a 3.15.1 pair: a text
  value on a subscription to one property.** A 3.15.1 publisher sends no
  callback for it, so nothing is stored on either kind of subscriber. The
  release sends one, and a 3.15.1 subscriber answers it 400 and stores
  nothing (attributed by the captures' timestamps: both 400s fall in the
  mixed run, none in 3.15.1 with itself). The replica is as empty as
  before; what is new is the refused callback. The changelog entry on text
  values says a subscriber upgrades first. Not a security fix; reported to
  the owner with Phase 1's result as found after the "accept all" answer,
  which it falls under as 3.15.1's own limit.
- **In every other probe a mixed pair does what a 3.15.1 pair does, or
  better.** The lost siblings of a nested write are 3.15.1's own
  behaviour as publisher; the release as publisher sends the whole value.
- **So the order is: either side may upgrade first for the nine flows; a
  subscriber gains more from upgrading than a publisher** (it stores text
  values and whole values once its publisher is also upgraded, and it is
  the 3.15.1 subscriber that the two candidates below would hurt).

**Candidates read from code and not reproduced**, because each needs a
condition the pair did not set up (the table with lines is in the wire
appendix, B1 to B15):

| Candidate | Condition | Traces to `SECURITY` | Recommended outcome |
| --- | --- | --- | --- |
| a trust request is not approved unless the requester's host answers the verification and its `/meta` names the id (B3) | the 3.15.1 host is slow or unreachable from the release | yes (247) | accept |
| a re-pair toward 3.15.1 resets its row (B2, observed) | the release re-requests an existing trust | yes (247) | accept |
| a permission callback stamped more than five minutes ahead is 400 (B5) | the 3.15.1 host's clock runs ahead | yes (337) | accept |
| a subscription the grant cannot read is 403 (B7) | 3.15.1 subscribes to what it may not read | yes (114) | accept |
| a low-granularity diff is fetched from the stored base URI (B15) | the 3.15.1 publisher's own URL differs from the one in the trust | yes (204) | accept |
| a list item over the span threshold reaches a 3.15.1 subscriber as a reference it stores nothing for (B11) | a publisher on the release writes an item over 390,000 bytes | no | accept: 3.15.1 could not hold such an item at all; the changelog entry says it |
| a `none` subscriber on 3.15.1 gets no resync callback, and its poll clears the marker as an empty diff (B12) | a 3.15.1 application polls a `none` subscription at a release publisher that suspends | no | accept: specification 1.5 says a `none` subscription gets no callback; the subscriber upgrades first |
| a 3.15.1 publisher never resends a resync the release answered 503 (B14) | the release's baseline fetch fails | no | accept: the release's next poll repairs it |
| 3.15.1 answers 403 to a permission query for a relationship type outside its four (B6); 3.15.1 REST list edits arrive in 3.15.1's own shapes and cost the release a rebuild (B10) | custom types; REST list edits on 3.15.1 | no | accept: 3.15.1's own limits |

No row is recommended for restore or keep-both: every non-security row is
either 3.15.1's own limit or a case where restoring would re-send what
specification 1.5 removed. That keeps the plan inside its "at most three
rows" rule. Not examined: what each side sends a peer when an actor is
deleted while the other side is on the other version (the pair's actor
deletes at teardown answered 204 on both sides, with the trusts already
gone).

## 3.16 or 4.0 (item 8)

**The rule first**, drafted before the release is classed against it:

- **patch** (`x.y.Z`): no route, hook name, keyword, response field, public
  signature or configuration option changes; nothing for an operator to do.
  (CLAUDE.md has this today.)
- **minor** (`x.Y.0`): everything a patch may not do, as long as an
  application that upgrades without reading anything either keeps working
  or is told at start-up what to do; stored data stays readable by the
  previous minor, or becomes unreadable only after an operator's explicit
  step. A minor has a migration guide.
- **major** (`X.0.0`): any of: a documented name removed (a tombstone that
  raises counts as removed); stored data the previous release cannot read,
  written without an operator's step; a default that changes what an
  unchanged application does on the wire or to its users; a peer on the
  previous release losing a flow for a reason other than a security fix.

**The release against the rule.** It removes documented names (the legacy
reverse lookup, `FanOutManager`, `CallbackOauthHandler`,
`Subscription.decrease_seq`, and under them 34 public names by the names
diff). It writes three kinds of data a 3.15.1 process cannot read, none
behind an operator's step. It changes defaults (creator uniqueness on,
adoption and vouching at sign-in, fail-closed reads). Fourteen rows refuse
to start, which is the release telling the operator; 113 are silent. By
the rule it is a major.

**What the number tells whom.** The number only reaches a consumer through
how they pin:

| Pin | Takes this release as 3.16.0 | as 4.0.0 |
| --- | --- | --- |
| none (`pip install -U`) | yes | yes |
| `>=3.15` | yes | yes |
| `^3.15` (Poetry), `~=3.15` (PEP 440), `<4` | **yes, on a routine update** | no |
| `~=3.15.1`, `>=3.15,<3.16`, exact | no | no |

For the middle row a minor number delivers, unasked: a start-up refusal
(which protects), then the silent rows, and the three irreversible ones the
first time a large list item, an `append_once` or an attribute list is
written. The two consumers in the owner's hands pin exactly (Emm) or by
tag (`actingwebdemo`), so the number changes nothing for them; it matters
for whoever installed from PyPI with a caret.

**The package and the protocol apart.** The protocol goes from 1.4 to 1.5
and a peer on 3.15.1 keeps every one of the nine flows; the one break is a
security fix. Nothing about peers asks for a major. The announced protocol
version changes nothing for a peer by itself.

**The promises in the tree.** `docs/migration/v3.13.rst:1059` said the
lookup fallbacks are "removed in the next major release", and this release
removes them: under 3.16 that sentence was broken, under 4.0 it is kept.
The release makes three promises of its own (the tombstones at
`actingweb/interface/app.py:529`, `actingweb/fanout.py:6` and
`actingweb/handlers/callback_oauth.py:7`, "removed at the next major"),
which stay either way and under 4.0 mean 5.0. Nothing more can be removed
now: the old attribute-list reader is what a rollback relies on.

**Precedent.** 3.7, 3.10, 3.11, 3.13, 3.14 and 3.15 each had a migration
guide and breaking entries, so a breaking minor is what this project has
done. None of them removed a mechanism the guide before had promised to a
major, and none wrote data the previous minor could not read without an
opt-in (3.14's v2 lists were an explicit `migrate_to_v2()`).

**What each answer costs here.** 3.16: nothing in this plan; the v3.13
sentence stays broken and the rule above has to be written so that 3.16
fits it, which makes "major" mean very little. 4.0: Phase 4 renames the
guide (`docs/migration/v3.16.rst`, spelled in eleven library messages) and
sweeps "3.16" in `actingweb/` (541 lines), `docs/` (260), `tests/` (262),
`CHANGELOG.rst`, CLAUDE.md and `thoughts/todo/` (53); a major gets a rule
in `.claude/workflow/release.md`; the todos whose trigger is "the next
major" get a trigger that still means something; names outside this
repository (Emm's branch and worktree) keep theirs. The sweep is
mechanical and the tests that match on the guide's path make it checkable.

**Recommendation: 4.0.0** (`4.0.0rc1` from this plan). The evidence that
decides it is the pin table and the v3.13 promise, not the size of the
changelog.

## The two storage todos, judged on the tree (item 8)

**`prop-list-key-prefix-scheme`**, requirement by requirement:

| Requirement | Today | What is still owed |
| --- | --- | --- |
| items larger than one row | closed for list items (property and attribute lists) on DynamoDB by spanning, to `list_item_max_bytes` (4 MiB by default) | a plain property is still one row, 400 KB (`docs/quickstart/configuration.rst:659`) |
| the partition's 1 MB Query page | unchanged; spanned bodies are in `{actor_id}$aux`, so only items over the threshold left the partition | a cost (more pages), not a failure: reads follow `LastEvaluatedKey` |
| payload out of band for items under the threshold | `with_list_item_limits(span_threshold=...)` accepts any value from 1 to 390,000, and `items_with_handles(resolve=False)` skips spanned bodies: an application that lowers the threshold gets whole items out of band today | a per-field split (the vector out, the text in) is not offered |
| an attribute key delimiter that cannot collide | a colliding write fails (`AttributeKeyCollision`) instead of replacing | two such names still cannot both exist |

- **PostgreSQL, argued by itself:** it has no per-partition page limit and
  no row cap that lists meet; the scheme has no case there beyond the
  delimiter.
- **What "out" publishes that the scheme must later read beside its own:**
  the `{actor_id}$aux` side partition, the attribute-list rows
  (`list:<name>-meta`, `-#<rank>`, `<bucket>$aux`) and the pre-3.16
  attribute reader. All three ship in this release whether the scheme is in
  or out; "in" would only avoid a second conversion for attribute lists.
- **Mixed versions:** the scheme needs dual-read during a transition and an
  explicit per-list conversion, as v1 to v2 did; nothing of that exists.
- **Alembic:** a PostgreSQL layout change adds a revision; DynamoDB-only
  prefixes add none.
- **A trigger to replace "the next major":** a measured one. The 964 KB
  figure is from August; the owner is asked for the largest actor
  partition today. Proposed: the scheme is planned when a real actor needs
  more than two Query pages for its plain properties and list heads
  together (about 2 MB after spanning), or when a consumer needs a
  per-field out-of-band payload that a lower span threshold does not give.
- **What "in" costs in time:** the design's first choice (a separate
  partition key per list, or a separate table) is open, and it needs a
  migration primitive with crash recovery. Meanwhile 32 `SECURITY` entries
  stay unreleased and the public demo runs 3.15.1.

**Recommendation: out**, with the measured trigger. If the release is 4.0
the todo's "next major" would otherwise read as 5.0; with the rule above a
key scheme that converts lists only on an operator's step can ship in a
minor.

**`dynamodb-known-next`**, item by item:

| Item | Still describes the tree | Judgement |
| --- | --- | --- |
| 1, batched deletes | yes (`DbTrustList.delete` and the attribute bucket deletes are serial) | out: a cost on actor deletion, no failure behind it |
| 2, `consistent_read` audit | yes | out: a behaviour change that needs measurements first; no migration |
| 3, `SubscriptionDiff` unpadded sequence key | yes (`actingweb/db/dynamodb/subscription_diff.py:118`) | out. It is a key change, but diff rows are short-lived (cleared when read), so writing padded keys and reading both forms needs no conversion and no major; it does not have to ride with the scheme |
| 5, `Meta.table_name` bound at import | yes | out: a fix for a minor; no migration |
| 6, trust secret uniqueness through a GSI | yes (`is_token_in_db`, `actingweb/db/dynamodb/trust.py:516`) | out: secrets are random, the check is a belt; the creators table shows the conditional-write shape if it is ever wanted |
| 7, lookup-table write amplification | yes (written against 3.16) | out: "revisit only if measured" stands |

**Recommendation: none rides in this release.**

## The owner's decisions (2026-11-18, Greger Wedel)

Asked with the evidence above; each answer is the recommended one.

- **The release is 4.0.0** (`4.0.0rc1` from the plan's Phase 4).
- **The key-prefix scheme stays out**, with the measured trigger. The
  question about the largest actor partition today was not put, against
  the plan; the trigger is written so that it does not need the figure.
- **No item of `dynamodb-known-next` rides.**
- **Every difference between 3.15.1 and the release as peers is accepted**:
  the second trust request (a security fix), the spanned reference and the
  `none` subscriber's resync. No behaviour is restored or kept beside the
  new one.

**Corrections after the decision, and what was deduced rather than asked.**

- The question on the number said the release writes three kinds of data a
  3.15.1 process cannot read "with no opt-in". That holds for the
  attribute-list conversion only (see "The inventory"); a spanned item
  needs an item in a narrow size window or larger than 3.15.1 could store,
  and `append_once` is a new call. The pin table and the v3.13 promise, on
  which the recommendation rested, are unaffected.
- The rule's line on data ("writes data the previous release cannot read,
  without an operator's step") reads wider than meant: a new storage
  feature an application has to call would make a major. "By an unchanged
  application" is the intended reading; the wording in `CONTRIBUTING.rst`
  is the owner's to confirm.
- Deduced, not asked: the two sentences of `CONTRIBUTING.rst` beyond the
  draft above (a major has a migration guide; what is promised to "the
  next major" is removed there and not before; the protocol version decides
  none of this); the three `ADDED` entries that make
  `Actor.deferred_callbacks()`, `HookRegistry.allows_anonymous_callback()`
  and `ListProperty.append_indexed()` public by naming them (none starts
  with an underscore and each has a docstring; `append_indexed` has a
  private `_locate` keyword).
- `SECURITY` mapping: the 32 leads at `8e1e73a` and after this phase are
  the same text in the same order (`cmp` on the extracted leads), and no
  hunk of the phase's changelog diff lies below the `v3.15.1` heading.
- The pair's captures and results are in this session's scratchpad
  (`.../scratchpad/pair/`: `old.jsonl`, `new.jsonl`, `result2.json`,
  `control-old.json`, `control-new.json`), which a reboot clears. Phase 2
  re-runs `scripts/live_pair.py` if they are gone; a run takes a few
  minutes.

## The release read from Emm's side (Phase 2, items 3 and 4)

Three appendices, read from `../actingweb_mcp` at `main` (`c1be751c`)
through git, names only:
[`…emm-usage.md`](2026-11-18-3-16-release-validation.emm-usage.md) (how Emm
uses the library),
[`…emm-matrix.md`](2026-11-18-3-16-release-validation.emm-matrix.md) (each
use against the test here that would fail if it broke) and
[`…emm-questions.md`](2026-11-18-3-16-release-validation.emm-questions.md)
(the upgrade walked with only the changelog, the guide and `docs/`).

**How Emm uses it, in short.** 45 imported names; 12 builder calls and 5
conditional ones; 10 lifecycle hooks, one property hook on `*`, three
callback hooks, one subscription data hook, 8 method and 39 action hooks;
three trust types of its own; the asynchronous variants of the trust and
subscription SDK only; `memory_*` property lists written with `append`,
`update_by_handle`, `delete_by_handle`, `clear` and `delete`; replicas read
through `RemotePeerStore.get_list` and `AttributeListStore`. Lambda through
Mangum, synchronous callbacks, DynamoDB in production with table
auto-creation off.

**Coverage against use (item 4, AC-9).** 152 rows; in trust, subscriptions
and the diffs that share memories 51 rows, of which 24 were covered, 10
partly and 17 not: no test called `subscribe_to_peer_async`,
`unsubscribe_from_peer`, `revoke_peer_subscription` or `sync_peer_async`
between two actors, read the cached peer capabilities or the peer's
permission copy through their stores, published with the by-handle list
writes, read a replica through `get_all_properties` or `AttributeListStore`,
or delivered with synchronous callbacks. **Closed by
`tests/integration/test_consumer_sdk_calls.py`**: ten tests between two real
actors on two hosts, both backends, each the call as Emm makes it
(`api/memory_types.py:476` for the permission override, and the sites the
matrix names for the others). None needed a new kind of fixture: the
synchronous-callback test switches the running configuration, as
`test_callback_delivery_shapes.py` does for two other settings.

**What the new tests found.**

- `store_permissions_async` tells the peer through a background task
  whatever `with_sync_callbacks()` says
  (`actingweb/trust_permissions.py:340-357`). On a loop that ends with the
  call the task is cancelled; on a function platform that freezes after the
  response it may not run. Subscription callbacks have a synchronous mode
  for exactly that; this notification has none. Emm calls it from five
  sites on Lambda. The peer's copy is corrected by its next `sync_peer`.
  **A design question for the owner; not changed here.**
- `subscribe_to_peer_async` returns the subscription's URL, not its id (its
  docstring says so); nothing wrong, the first draft of the test assumed
  the id.

**The maintainer's questions (item 3, AC-8).** 73 questions: 50 answered by
the documents, 17 partly, 6 not at all. The unanswered and partly answered
ones are written into `docs/` as the generic pattern in this phase (the
start-up check on a function platform, where the operator commands run and
what they must be told, the creators table when tables are declared in a
template, what a missing `ConditionCheckItem` looks like, the PostgreSQL
order, which hooks fail a request on a fault, a callback hook's `data`,
when the `permissions` hook runs, `sync_peer`'s result, the two SPA routes).
Four are Phase 4's, with the guide's restructure: the version, installing
the candidate, rolling back, and peers that have not upgraded.

**A defect the walk found, fixed here.** `complete_client_authorization()`,
called as four documents and its own docstring show, never ran the
application's `oauth2_trust_requested` hooks: only the library's own routes
passed them, through a private callable. An application with its own
sign-in route (Emm has one) got no decision hook. New in this release, so
no released version had it. Fixed in
`actingweb/oauth2_server/oauth2_server.py` (the helper now uses the
application's hooks when no `decide_trust` is passed), with
`tests/integration/test_oauth2_trust_binding.py::test_the_helper_asks_the_applications_decision_hook`
seen failing first.

**What Emm's maintainer still has to do** is section (d) of the questions
appendix. The items the adoption worktree does not have yet: the IAM
actions `BatchGetItem` and `ConditionCheckItem` and the `<prefix>_creators`
table in its template (its IAM coverage test looks for `TransactWriteItems`,
which is not an IAM action); the two access rows it added on
`subscriptions/<id>/<subid>` are redundant and harmless
(`actingweb/config.py:359` already admits a peer to its own subscription);
`oauth2_server._store_mcp_client_info_in_trust` does not exist in the
library (it did not at 3.15.1 either); three private names it reads
(`handlers.mcp._token_cache`, `._cache_ttl`, `config._oauth2_trust_types`)
still exist.

**Requests in a 3.15.1 peer's form (AC-15).**
`tests/integration/test_wire_v315.py`, rows `WV1` to `WV4`: the data
callback with 3.15.1's space-separated timestamp, the resync callback with
a `+00:00` offset, a nested write sent as the changed part, and the second
trust request without a bearer (403, the release's row unchanged). Recorded
once, identical over repeated runs on both backends.
