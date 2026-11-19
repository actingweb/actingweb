# Triage: a consumer's read of 4.0.0rc1 before adopting it

**Date:** 2026-11-19. **Tree:** `master` at `acfa13c` (`4.0.0rc1`, not yet
tagged).
**Source:** `thoughts/inbound/emm-4-0-adoption-findings-and-asks.md`, filed
2026-11-19 by Emm AI (`../actingweb_mcp`), Greger Wedel with Claude, out of
Emm's research and draft plan for its migration from 3.15.1, a five-evaluator
review of that plan, and a read-only measurement of Emm's production store.
The report was read against `442ffa6`; its numbering (3.1–3.9, M1–M6,
A1–A14, V1–V4) is kept here.

**Status of this note:** triage record with a recommended scope. The inbound
file stays until the owner has settled the scope; then the plan
(`thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md`) and the todos are
filed and the report is deleted.

"Confirmed" means read in the tree at `acfa13c`. Nothing was run.

## 1. What the check changed

- **3.1 is not a wrong name set in the store; it is a verdict about the wrong
  set.** `cmd_report` computes its verdict over `config.indexed_properties`
  of the *command's* process (`maintenance/property_lookup.py:1022, 1047-1060`),
  and `--properties` narrows only what is counted (the comment at `:1029`
  says so on purpose). An application that sets its names in code
  (`with_indexed_properties([...])`) and not through `INDEXED_PROPERTIES`
  gives the command the library default, so the report says "would refuse
  externalUserId" and exits 1 for a store the application would start on.
  `backfill` and `mark-complete` do use the passed names (`_names`, `:1003`),
  so the report's question "two names or three" is answered: the passed
  two. The start-up check and the command cannot disagree about what is
  marked, only the `report` verdict is wrong for this consumer.
- **3.2 confirmed, and inconsistent with the rest of the library.**
  `_mark_one` qualifies every actor without a marker
  (`maintenance/mark_actors_vouched.py:113-117`); nothing skips the
  `_actingweb_` prefix, while `no_actors` (`unique_creators.py:1153`) and
  `properties_table_empty` (`property_lookup.py:84`) both do.
- **M2 is partly there already.** The messages distinguish "could not be
  checked" from "not ready" (`interface/app.py:1731-1741, 1783-1792`), but
  the exception type does not, there is no retry, and a fault is raised
  from `integrate_*`. What Lambda does after a failed initialisation is
  unverified on both sides (the report's section 9).
- **M1's stated reason for the difference does not cover the case asked
  for.** The wrong-prefix guard protects the *operator command*
  (`unique_creators.py:407-413`). The application at start already tells an
  empty store apart (`no_actors`, used only to shorten the refusal,
  `app.py:1796-1803`), and the lookup gate marks an empty store ready from
  the same position (`property_lookup.py:163-166`). The comment at
  `app.py:1784-1786` is about a store *with* users.
- **A8 has a starting point.** `is_vouched_actor` and `is_vouched_store`
  exist (`oauth2.py:1819, 1846`); what is missing is a public, documented
  entry that raises on a fault. Whether the existing two fold a fault was
  not read.
- **3.8 could not be confirmed or refuted cheaply.**
  `tests/test_db_fault_contract.py:419-435` covers `DbActor.get_by_creator`
  raising; no `pytest.raises(DbError)` was found directly around
  `PropertyListStore.exists()` or `ActorInterface.get_by_id`. Treat as a gap
  until a test names them.

## 2. Section 3 of the report: defects and gaps in the candidate

| # | Claim | Check | Verdict |
| --- | --- | --- | --- |
| 3.1 | `report --properties` still names `externalUserId` | Confirmed, see above | Fix: with `--properties`, the verdict is about the passed set, and the header says where the set came from (flag, `INDEXED_PROPERTIES`, library default) |
| 3.2 | Marking dry run would mark the system actors | Confirmed | Fix: skip `_actingweb_*`, count them, say so in the summary |
| 3.3 | `creator-to-email` does not count the unvouched it skips | Confirmed: `_in_scope` returns `None` for them (`email_as_creator.py:143`), counts are `scanned, moved, held, squatted, cleared, changed, errors` (`:278`) | Fix: an `unvouched` count; a non-zero one prints the order ("mark first"). Guide: the reason goes into the top checklist |
| 3.4 | "Rows to review" query returns every registration row | Confirmed in the text (`docs/migration/v4.0.rst:2343-2349`): the example only works for an application whose client list contains `mcp_client` | Docs: exclude rows held by `_actingweb_oauth2` (registrations, not approvals), add a DynamoDB form |
| 3.5 | Discovery advertises `client_credentials`, anonymous registration refuses it | Confirmed (`oauth2_server.py:813` against `:163-168`). The grant is real for owner-created clients, so the advertisement is true of the token endpoint and false of `/oauth/register` | Decide (section 5). No connector is known to register it |
| 3.6 | `/oauth/logout` 503 has no `X-ActingWeb-Error` or `code` | Confirmed (`handlers/oauth2_endpoints.py:1248-1257`) | Fix: same shape as the other 503s |
| 3.7 | `get_by_id`/`get_by_creator` docstrings do not say they raise | Confirmed (`interface/actor_interface.py:176-186, 245-255`) | Fix (docstrings) |
| 3.8 | No direct test for `exists()`/`get_by_id` raising | Not refuted | Add both tests |
| 3.9 | A bare `Config()` takes the backend's limits | Confirmed (`config.py:225-235`) | Docs sentence in "Spanned list items"; a process-wide setting (an environment variable read by `Config`) is a small addition if wanted |

Also confirmed: the note for the guide that "a marker is present" stopped
meaning "a provider vouched" (`UNVOUCHED_AUTH_METHODS`, `oauth2.py:1787`).
One line in the guide's "OAuth sign-in" part, pointing at A8's call.

## 3. Section 4: asks that need the major

| # | Ask | Assessment | Recommendation |
| --- | --- | --- | --- |
| M1 | An empty store enables creator uniqueness itself | Sound, see section 1. DynamoDB: when `no_actors` is true and the creators table exists or auto-creation is on, write the backfill item. PostgreSQL: create the unique index on the empty table (needs the application role to hold DDL, which Alembic-run deployments may not grant: then the refusal stays, with today's message). Races: two first starts write the same item; a 3.15.1 process creating an actor between the scan and the mark is the same window the lookup gate already accepts | **Before rc1.** It removes start-enable-start from every consumer's CI, this repository's demo instructions included |
| M2 | A read fault at start does not take the function down | The refusal on a fault is deliberate (fail closed). A bounded retry of a faulting check and a distinguishable exception are additive; serving 503 from the request path while the check repeats is a new start mode with its own failure cases | **Before rc1:** retry a faulting check briefly (about three attempts, well under a function's init budget), and mark the exception (`StoreNotReady.unavailable`, or a subclass). **Later:** the deferred-check mode, after Emm reports what a failed initialisation really does |
| M3 | Factory closed by default where a sign-in provider is configured | A default change, so this release or the next major. Evidence: an unowned actor in the consumer's production made through the open factory, with the application's creation hook run for it. Cost here: every test and example that posts to `/` with OAuth configured calls `with_open_factory(True)`; a start-up log line when the factory is closed by default; guide and changelog (**Breaking**) | **Owner's decision** (section 5). Recommended: yes |
| M4 | 4 MiB item ceiling against a 6 MB function response | The arithmetic is right in kind: the ceiling is deliberately not derived from a platform. Lowering the default without the measured number would be a guess | **Docs before rc1** (deployment page: the escaping arithmetic and `with_list_item_limits(max_bytes=...)`). Revisit the default when Emm reports the measured ceiling |
| M5 | Attribute-list conversion waits for the operator | A revisit of the difference accepted on 2026-11-18 (`research/2026-11-18-3-16-release-validation.md:423`). No new evidence; the consumer has no replicas | No change. The guide already says deploying is the point of no clean return for replicas |
| M6 | Append-only grant, author stamp, per-item revision | Questions, not requests. Not answered here: it needs a read of the access matrix and the row format with that question in mind | **Answer in writing before 4.0.0 final**, not before rc1. A short research note |

## 4. Section 5 and 6: asks any 4.x could carry

Recommended before rc1 because they are small and the consumer's first
migration leans on them:

- **A8** a public strict "is this actor vouched". 4.0 silently breaks a
  gate written against 3.15.1's marker; the release should ship its
  replacement.
- **A2, the printing half:** every operator command prints backend, table
  prefix (or schema) and region before it reads, and again before an
  `--apply`. The refusing half (no `--apply` on the default prefix
  `demo_actingweb`) changes what a command does for the demo; see section 5.
- **A14 as a guide line, not a patch release:** run the marking again
  immediately before the deploy, and say why (a connector sign-up on
  3.15.1 after the marking is unmarked). A 3.15.2 that writes the marker is
  the complete fix and is the owner's call.

Filed as todos (4.x), each real, none needed for a first migration:

| # | Ask | Note |
| --- | --- | --- |
| A1 | `actingweb-check-ready`, read-only | `settle()` writes on a ready or empty store, so "no writes" needs a read-only path through each gate; not a wrapper |
| A3 | Marking: creators in the dry run, a file of ids, leave no-sign-in actors unmarked | The dry-run line is cheap and can ride with 3.2 if the plan has room |
| A4 | Client registrations: list and expire | Existing todo `dcr-registrations-and-client-trust-rows-never-expire.md`; add the measured numbers (295 registrations, 260 without a user row) and the "never authorised" class as the first sweep |
| A5 | Mixed-version rows "Not tested" | Joins `rc-pass-against-real-consumers.md`: it is rc validation work |
| A6 | A documented log line and a hook for an actor cleaned or replaced at sign-in | The hook exists (`actor_adopted`); see section 6a |
| A7 | A store fault after the write landed says so (`committed`) | `interface/property_store.py:122-125` confirmed. Relates to `conditional-write-ambiguous-after-sdk-retry.md` |
| A9 | `list_all_with_rows` strict form | Fold confirmed (`property.py:173-178`), documented as deliberate |
| A10 | `delete_attr_if_data_equals` on `Attributes`, canonical dict compare | String compare confirmed (`db/dynamodb/attribute.py:664-676`); the dict case unverified here too |
| A11 | Callback budget as a request deadline; a cut permission notice sent later | Joins `outbound-callback-backpressure.md` |
| A12 | One actor load per MCP session | Joins `mcp-cache-lifecycle-and-revocation.md` |
| A13 | `actingweb.testing` fault injection | No such module today |
| V1 | Bounded list read (tail, `start=`/`limit=`) | `slice` at `list_core.py:3163`. The first thing the comments feature needs |
| V2 | An append that creates nothing | Joins `meta-row-create-unconditional-for-description-writers.md` |
| V3 | TTL on a list item | |
| V4 | Keep the previous generation of a spanned item | Needs the envelope read with this in mind; say in the M6 note whether a 4.x can carry it |
| — | `require_actor`, `require_auth_for_initialize` | Already in `mcp-oauth-connector-conformance-followups.md` |

## 5. Decisions the owner has to make

1. **M3:** does 4.0 close the factory by default where a sign-in provider
   is configured?
2. **3.5:** drop `client_credentials` from discovery's
   `grant_types_supported` (it is not obtainable by registering), or keep
   it and document that only an owner-created client holds it?
3. **A2:** do the operator commands refuse `--apply` on the default table
   prefix unless it was set explicitly?
4. **A14:** a 3.15.2 that writes the provider marker in the MCP OAuth
   server, or the guide line only?
5. **Section 8, publishing:** rc1 goes to TestPyPI by the release workflow.
   An exact pin then needs a second source in the consumer's
   `pyproject.toml` (Poetry: a source with `priority = "explicit"` and
   `source = "testpypi"` on the dependency), which the consumer's pin guard
   has to allow. The alternative is publishing release candidates to PyPI
   (pip and Poetry do not select a pre-release unless asked). Guide text
   either way.
6. **Section 8, data:** is every stored shape frozen from rc1 (creator
   records, lookup and email markers, vouch markers, spanned items,
   `append_once` key rows), so that 4.0.0 final reads what a candidate
   wrote with no operator step? If yes, the changelog and guide say so and
   a later candidate that must change one ships its reader.

## 6. Recommended scope before the tag

One plan, one PR on a `fix/4.0.0rc1-...` branch, three phases. Since
`v4.0.0rc1` is not tagged, its entries join the `v4.0.0rc1` changelog
section.

1. **Operator commands and small defects:** 3.1, 3.2, 3.3, 3.6, 3.7, 3.8,
   A2 (printing), 3.5 per the decision.
2. **What a start does:** M1, M2 (retry and a marked exception), M3 per the
   decision, A8.
3. **Guide and docs:** 3.4, 3.9, the marker-presence line, the checklist
   order with its reason, M4's arithmetic, the A14 line, the two answers of
   section 8.

Then the todos of section 4, the M6 note before 4.0.0 final, and the
inbound file deleted.

## 6a. The deferred asks, judged one by one for rc1

Section 4 parked fifteen asks as 4.x todos. Read again with three
questions: does the consumer's first migration (the operator run against a
real store, then production on the candidate) lean on it; does it get
harder or breaking once 4.0.0 is final; how large is it.

**Move into the plan:**

| # | What goes in | Why |
| --- | --- | --- |
| A9 | `list_all_with_rows()` raises `DbError` on a fault | Not additive if done properly: the fold to `([], {})` is "kept for compatibility" (`property.py:164-167`), the last documented holdout of the fault contract 4.0 made the rule, and only a major can drop it. No caller inside the library (`grep`, 2026-11-19). A `strict=` keyword later would leave the unsafe default forever. **Breaking**, one changelog entry, one guide line |
| A1 | `actingweb-check-ready`: the four gates, read-only, each with its fix line and one exit status | On a function platform the deploy is otherwise the first test of the gates. The pieces exist (`read_readiness`, `missing_enforcement`, the email and attribute-schema probes); the work is a read-only path where `settle()` writes. Without the IAM-action list, which is a document, not a probe |
| A3 (part) | The marking dry run prints each actor's creator, stored email and current marker; `--ids-file` | The dry run is the gate before the deploy and prints ids only (`mark_actors_vouched.py:147`). After 3.2 the consumer's dry run names one actor, the one it must *not* mark; the line has to say enough to see that. "Leave actors with no sign of a sign-in unmarked" needs a definition of the sign and stays a todo |
| A6 (part) | One documented log line per actor cleaned or replaced at sign-in | The hook asked for exists: `actor_adopted` carries `mode`, the removed trusts, subscription peers, client ids and token count (`docs/reference/hooks-reference.rst:387-420`), and `actor_deleted` fires with `reason="replaced_at_adoption"`. What is missing is the stable log line, and the guide pointing at the hook. Telling peers stays a todo |

**Stay out, with the reason:**

| # | Why it can wait |
| --- | --- |
| A7 | A `committed` marker on a fault raised after the write is additive in any 4.x (a subclass or attribute), but only worth having if every post-write raise site carries it: `_register_diff` (`interface/property_store.py:122-125`), the list diff publishers, the handlers. That audit is the work. The consumer lists the fault contract under what it takes up *after* the migration. First item of 4.1 |
| A13 | A public `actingweb.testing` is new API that deserves its own design; a consumer patching library functions is fragile, but across rc and final nothing it patches is planned to move |
| A4 | A retention decision and CIMD come first (existing todo). Nothing in the migration reads the 295 registration rows |
| A5 | Validation work against the published candidate, which is what the candidate is for: into `rc-pass-against-real-consumers.md`, done before 4.0.0 final |
| A10 | Unverified on both sides; needs a look at how a dict attribute is serialised before anything is promised. For the comments feature, not the migration |
| A11 | No peer, subscription or replica in the consumer's production; no subject to test against |
| A12 | One point read per MCP request. Caching the actor across requests touches deletion and revocation freshness (`mcp-cache-lifecycle-and-revocation.md`); wait for the consumer's measured cold-start and per-call numbers |
| V1–V4 | Additive list features for comments and versioning, after the migration. V1 (bounded read) first. Whether V3 and V4 fit the stored row is answered in the M6 note |
| `require_actor` | The same seam as V2 (a write that creates nothing for an actor that is gone). Not tracked anywhere today: it gets a todo with V2 |

**Owner's rule, 2026-11-19: work we already know 4.x will need, and know
how to do, goes in now.** Applied to the stay-out table, three move in:

- **A7.** The need is stated (the consumer's tools answer "failed, try
  again" for a write that landed) and the shape is known: a `DbError`
  subclass or attribute set at every site that raises after its write. The
  site audit is work, not an open question.
- **A5.** `scripts/live_pair.py` already runs 3.15.1 beside this tree
  (`research/2026-11-18-3-16-release-validation.md:187`); the two "Not
  tested" rows (`mark-actors-vouched`, `property-lookup backfill`) are two
  more runs of it, by path, before the tag.
- **V1.** The comments feature is announced and a v2 list's ranks are its
  sort key on both backends, so a tail read and a read after a handle are a
  bounded range query plus the existing span resolution. An index-based
  `start=` is the part to leave out: an index is a count, which is what
  the bounded read avoids.

Still out, because the "how" is not known: A13 (no shared fault helper
exists even in this repository's tests, which patch per case), A4 (the
retention decision), A10 (unverified), A11 and A12 (design and
measurement), V2 with `require_actor` (the todo's own open choice of
creation path), V3 (expiry of a spanned item's body rows, the count hint
and PostgreSQL's purge are undesigned), V4 (waits for the M6 note). Of the
other open todos the rule moves none: CIMD is known to be needed but its
fetch, caching and retention interplay are not designed.

## 6b. The two features (report section 6, and M6): what has to be in 4.0.0

The question asked: comments on shared documents and versioning of
memories and documents will be built on 4.x. What must the library add
*now*, because adding it later would not work beside 4.0.0 processes or
4.0.0 data? Read at `acfa13c`; nothing run.

**What the report says exists, checked.** `AttributeListStore(actor_id,
bucket, config)` opens from an id (`attribute_list_store.py:44`);
`ListAttribute` and `ListProperty` share `ListCore`
(`attribute_list.py:286`, `property_list.py:490`), so `append_once`,
`items_with_handles` and `update_by_handle` are the same code on both;
loading an actor is one read and no longer writes the creator
(`actor.py:851-856`). That no route serves an attribute list and no diff
is registered for one was not re-checked here.

**The one thing only 4.0.0 can carry: a must-understand rule for the
stored envelope.** Every later feature that touches the stored item
(an author stamp, a revision, V4's retained or shared bodies) is written
by some 4.x and met by 4.0.0 processes and tools. Today:

- An unknown envelope field is kept in `Envelope.extra` and written back
  on every rewrite (`property_list_span.py:152, 296`, `list_core.py:931,
  940, 4531`). Good for a field an old process may ignore (an author).
  Wrong for a field it must maintain: a 4.0.0 `update_by_handle` would
  carry a revision forward unchanged.
- An envelope 4.0.0 cannot parse (neither `v` nor `span`, or a `span` of
  another shape) is "malformed", and `--repair` **removes its head**
  because it carries the library's marker (`list_core.py:4544-4560`,
  `carries_library_marker`). A 4.0.0 repair run would delete items a
  later 4.x wrote in a shape it does not know.
- A marker other than the integer `1` reads as a plain user item
  (`_envelope_obj`, `property_list_span.py:219-222`), so a second envelope
  format can never be introduced: 4.0.0 would serve the envelope as the
  item.

What to add: a reserved envelope field (for example `need`, a list of
feature names). A process that meets a name it does not implement raises
a distinct "written by a newer version" error on read and on write, and
the sweep and `--repair` report the head and never remove it. Reader-only,
no writer uses it in 4.0.0; a few lines in `parse()`, the sweep, the
verify tool's report, and tests. Without it each of the three features
below needs a major, or a release that waits until no 4.0.0 process or
tool can be running.

**Already in the plan and needed first:** V1, the bounded read (a comment
thread and a version history are read whole on every view otherwise, and
the first `append_once` on a list reads every head).

**Nothing in 4.0 closes the door, nothing to add now:**

| Feature | Why it can come in a 4.x |
| --- | --- |
| An `append` operation for grants | Operations are open strings: the evaluator denies an operation a rule does not list (`permission_evaluator.py:1166`) and the override normaliser keeps any list of names (`trust_permissions.py:885-899`); no whitelist was found. A 4.0.0 process beside a newer one checks `write` for a `POST` append and refuses an append-only grantee: closed, not open |
| An author stamp | An ignorable envelope field, kept by 4.0.0 today. Exposing it on the wire is an additive response field |
| A per-item revision | Needs the must-understand rule above, nothing else |
| V3, a time-to-live on an item | Attribute rows already carry a TTL on both backends; a v2 list's count is a hint and survives rows that vanish. Undesigned: a spanned item's body rows, `append_once` key rows, PostgreSQL's purge. Additive |
| V4, the previous generation kept | A retained generation is an orphan to the sweep unless a head in the same list names it, and a body row's name includes the list name, so a history item cannot point at it in 4.0's shape. Needs a new locating field, which is what the must-understand rule makes safe. Until then a version of a large document is a full copy, which works |
| V2 and `require_actor` | Not needed to build comments: the application can append and then read the deletion tombstone (`ActorInterface.get_deletion_status`), removing what it wrote if the owner is going. The one-step form stays a todo |

**The answer to M6's two questions.** Append-only grants and an author
stamp: the access model can take that direction later, and 4.0's matrix
does not close it. A library revision per item: possible in a 4.x if, and
only if, 4.0.0 ships the must-understand rule.

## 6c. Owner, 2026-11-19: 4.0 has reached nobody, so fix what is cheaper now

The test applied: is this cheaper before the first 4.0 process and the
first 4.0 row exist than after? Additive API costs the same in 4.1 and
stays where sections 6a and 6b put it. What the test moves:

**In, beyond the scope so far:**

- **The envelope's must-understand rule** (section 6b).
- **A pinned guarantee that list code leaves side-partition rows it does
  not recognise alone.** It holds today: the sweep, `delete()` and
  `clear()` select `$span-` and `$key-` rows by shape
  (`list_core.py:818-837`, `SPAN_ROW_RE`, `KEY_ROW_RE`), so a later row
  kind in `{actor_id}$aux` (retained or shared bodies, V4) survives a
  4.0.0 process and tool. Nothing states or tests it. A test and a spec
  statement now; a refactor of the sweep in 4.0.x could otherwise break it
  unnoticed.
- **M4, a lower default item ceiling.** The two directions are not
  symmetric: raising a ceiling later strands nothing, lowering it later
  leaves stored items no write can replace at their size. 4 MiB can exceed
  a 6 MB function response once the body is escaped twice. Proposed: 2 MiB
  where a row cap exists, with the arithmetic in the deployment page, and
  raised when the consumer's measured ceiling is in.
- **PKCE required from every client of the built-in authorisation
  server**, confidential ones included (the open item in
  `mcp-oauth-connector-conformance-followups.md`). Reversed from "no" in
  section 7: MCP's authorisation rules require PKCE of every client, the
  connectors seen so far send it, and after 4.0.0 this is a breaking
  change for a later major. With an opt-out for a deployment that has a
  client without it.
- **M3, A2's refusal and 3.5** take the stricter answer by the same test
  (factory closed where a provider is configured; no `--apply` on the
  default prefix; `client_credentials` out of discovery), unless the owner
  says otherwise.
- **The data freeze** (section 5, item 6): with the must-understand rule
  in, every shape rc1 writes can be declared final.

**Looked at and left, though now is the cheap moment:**

- **A writer token on every list item**, which would close
  `conditional-write-ambiguous-after-sdk-retry.md` for plain appends.
  It makes every item an envelope, so nothing a 4.0 process appends is
  readable after a roll-back to 3.15.1; today that holds only for keyed
  and spanned items, which an application opts into or reaches by size.
  The roll-back is worth more than the residual duplicate.
- **The `prop#`/`list#` key-prefix scheme** and the other storage items
  the owner left out on 2026-11-18: they move 3.15 data as well, so
  "before 4.0" saves no migration.
- **Unicode normalisation, the `output_schema` default, MCP 2025-03-26:**
  unchanged from section 7 (a migration of 3.15 names; tied to validation
  work; no client behind it).

**Owner's answers, 2026-11-19.** Confirmed: the factory closed where a
provider is configured (M3), no `--apply` on the default prefix (A2),
`client_credentials` out of discovery (3.5), the 2 MiB default ceiling
(M4), PKCE from every client with an opt-out, and `list_all_with_rows()`
raising (A9). rc1 is published to TestPyPI as the workflow does; the guide
gets the Poetry second-source form. A14 is a guide line (run the marking
as the last step before the deploy and once more straight after it), no
3.15.2. The key-prefix scheme stays out of 4.0; its design is written
between rc1 and 4.0.0 final, so that anything a 4.0.0 process must
tolerate for a later conversion can still land in final.

## 7. The open todos, judged for the same release

Every file in `thoughts/todo/` was read on 2026-11-19 with three questions:
does it need the major (a default, a negotiated version, a stored name),
does this consumer's migration lean on it, and is it small with nothing to
decide first. `dynamodb-known-next.md` and `prop-list-key-prefix-scheme.md`
were judged for 4.0.0 by the owner on 2026-11-18 and are not reopened.

**Owner, 2026-11-19: all five rows of the table below go into the plan.**

**Candidates to ride with the plan** (small, nothing to decide, or asked
for by the consumer):

| Todo | Item | Why now | Size |
| --- | --- | --- | --- |
| `mcp-oauth-connector-conformance-followups.md` | A way to require authentication on `initialize` (or the post-authentication hook) | Asked twice by the consumer, which keeps a middleware in front of `/mcp` for it; that middleware stops working under the modern MCP revision (`mcp-2026-07-28-dual-era-support.md`, "Downstream consumers to notify"). A new option or hook name is easiest to add in a major | Medium: needs a short design (option against hook) |
| same | `/.well-known/openid-configuration` | ChatGPT probes it on every connect and gets 404. Serve the same document | Small |
| same | `resources/templates/list` | `resources/list` returns a templated URI while the method is not found | Small |
| same | Shared registrations flip the Connections card name | Visible to the consumer's users; keep the first name seen | Small |
| `flask-spa-session-route.md` | The Flask SPA session route | Nothing to decide, one route and a test per integration. Not this consumer (FastAPI); a rider only if the plan has room | Small |

**Decisions the major is the window for** (each changes what an unchanged
application or client gets; if not taken now they wait for 5.0 or become
opt-in):

| Todo | Decision | Lean |
| --- | --- | --- |
| `mcp-oauth-connector-conformance-followups.md` | Require PKCE from confidential clients too (OAuth 2.1) | No, not without the connectors' behaviour checked: it breaks a confidential client that sends none. An opt-in later is additive |
| `mcp-batch-receive.md` | Drop 2025-03-26 from the supported MCP versions, or implement batch receive | Leave as is: no client batches, and dropping the revision changes what a header-less request is assumed to speak |
| `action-hook-output-schema-not-visible-to-mcp.md` | Advertise a hook's `output_schema` by default | No: the todo itself ties it to server-side validation and the structuredContent decision; newly advertising breaks working tools |
| `unicode-normalisation-of-names.md` | Normalise names at the permission and write choke points | No: it carries a migration of stored names and has no report behind it |

**Stay in 4.x, updated by this triage:**

- `dcr-registrations-and-client-trust-rows-never-expire.md` takes A4 and the
  measured numbers. Its design is additive (a `last_used_at`, a TTL, a
  sweep) and should be taken with CIMD, which is too large for this plan.
- `meta-row-create-unconditional-for-description-writers.md` takes V2;
  `conditional-write-ambiguous-after-sdk-retry.md` takes A7;
  `outbound-callback-backpressure.md` takes A11;
  `mcp-cache-lifecycle-and-revocation.md` takes A12.
- `rc-pass-against-real-consumers.md` takes A5, and loses its "fresh-store
  step in its CI" for `actingwebdemo` if M1 lands.
- `dynamodb-known-next.md` item 5 (table name and host frozen at import) is
  the same ground as A2's default prefix; a note there, no reopening.

**Unchanged, no reason to move:** `client-deletion-leaves-other-actors-connections`
(SDK clients only, needs a choice), `verify-orphans-subscription-tables`,
`subscriber-hooks-and-resource-diffs-after-1-5`,
`subscription-subscriber-fault-hardening`, `whole-list-rewrite-atomicity`,
`sessions-endpoint-and-advertised-options` (a minor of its own),
`dynamodb-chain-id-gsi` (trigger not fired), `attribute-list-old-layout-removal`
and `drop-python-3-11-after-eol` (waiting by design),
`ci-postgres-parallel-flakiness`, `root-todo-leftovers`,
`v2-list-access-verification-followups`, `ai-agent-discoverability-followups`,
`mcp-2026-07-28-dual-era-support`.
