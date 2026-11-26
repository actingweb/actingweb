# Feature: Version history and restore for properties, attributes and list elements

**Date:** 2026-11-26
**Author:** Greger Wedel (with Claude)

## Problem

An end user of an application built on the library keeps work in properties,
attributes and lists: in Emm (`../actingweb_mcp`), memories, wiki documents
and standing instructions. That work is edited by the user in the app's
editor and by AI agents acting for the user. An agent can replace a whole
document with a new full version; a user can make a major edit and regret
it; either can delete an item. The storage calls overwrite or remove the
value, and the previous one is gone. The owner has lost work both ways: to
a large edit of their own in the Emm editor and to an agent writing a new
full version.

The application developer has no library support and builds history on top
of the public storage calls. Emm did this once, for instructions only
(`repositories/audit_log_repository.py`, read 2026-11-26): one property list
per instruction holding a full copy of the body before each change, with who,
how, action and timestamp. It has four costs. It keeps 20 records per item:
it is a recent-history audit, not an archive, and the cap bounds every read
and scan (at the cap the oldest record is overwritten in place, because
removing it from the front of a list would shift every index). Its own
module forbids full-body snapshots for memories and documents, the only
kind a restore can use: at their write volume they "would balloon storage".
Its lists sit in the actor's ordinary property namespace, so history is
visible to the standard storage calls, and the history overview reads every
list the actor has, old bodies included, to count the audit ones. And
recording never raises, so a snapshot that fails is skipped silently: a
version can be missing exactly when it is needed.

**Demand evidence:** the owner has lost data, both ways (own edit, agent
rewrite). The consumer built a workaround for one item type and wrote down
that full copies cannot be kept that way for the other two. No third-party request
exists; that other consumers want this is a hypothesis.

## Users

- **End user of a consumer application** (the owner as an Emm user, first)
  — needs any earlier version of a memory, document or instruction back in
  one action, whether it was wrecked by an agent, by their own edit or by a
  delete.
- **Consumer application developer and operator** (the owner for Emm;
  measured on "no user loses work to an agent edit" and on storage cost per
  account) — needs to decide when a version is taken, attach who/how to it,
  bound how many are kept, and delete the hand-rolled history.
- **Operator of any deployment that does not turn this on** — must notice
  nothing: no migration, no operator step, no change in behaviour or cost.
- **Custom database backend authors** — affected by a new storage surface
  to implement, if they want the feature.
- **Peers, subscribers and SPA clients** — must be unaffected: history is
  not visible to them.

## Premises

1. This is the right problem, framed as **explicit** versions: the
   application decides when a version is taken, because it knows when an
   agent rewrite or a major edit is about to happen. Automatic versioning on
   every save is to be evaluated beside it, not instead of it. — agreed
   2026-11-26
2. Doing nothing means every consumer builds history on the public storage
   calls, as Emm did, and hits the same wall. The library should own it,
   even though it adds a storage surface both backends carry. — agreed
   2026-11-26

## Desired Outcome

A user who finds a memory or document wrecked by an agent rewrite, by their
own large edit or by a delete gets any earlier version back in one action.
The application developer keeps no history storage of their own: Emm's
hand-rolled audit list is deleted, and memories and documents have history
as well as instructions. A deployment that does not configure versioning
upgrades without noticing the feature exists.

## User Experience

The "user" of the library is the application developer; the end user's
experience is what the application builds from these steps.

**Main path:**
1. The developer turns versioning on in the application's configuration,
   optionally with an app-wide limit on versions kept per item, and
   optionally with automatic versioning.
2. Before an agent replaces a document, or when the user saves a major edit,
   the application takes a version of that property, attribute or list
   element, passing a small metadata object (who, how, what action). The
   version holds the current value, a timestamp and a stable id. Every call
   makes a new version.
3. The application goes on reading, listing and writing the item as before.
   Nothing about history shows up in those calls, over HTTP, to peers or to
   subscribers.
4. The user opens "history" in the application. The application lists the
   item's versions (id, timestamp, metadata, and for a list element the
   position it had), newest first, without content; it fetches one version's
   content by id or by `-1`, `-2`, ... (`-1` is the newest), or all of them.
5. The user picks one. The application restores it: the current value is
   first saved as a new version, then the chosen version becomes the current
   value. Hooks and subscribers see an ordinary write. For a list element
   the application says where it goes: overwrite a given element, insert at
   a position, or append; or, in the simpler option still to be evaluated
   (L2 in the Hypothesis), the application reads the version's value and
   writes it to the right element itself.
6. The application removes a single version the user no longer wants, or
   all old versions of an item, leaving the current value.

**Edge paths:**
- **The item was deleted** — a normal delete leaves the history. The item
  is absent to the standard calls, the last content is `-1` (when a version
  was taken before the delete, by the application or by automatic
  versioning), and a restore brings the item back. A separate destructive
  delete removes the item and every version.
- **The user wants to overwrite without keeping the current value** — the
  restore is called with the pre-restore version turned off; the current
  value is replaced and lost.
- **Limit reached** — the new version is stored and the oldest is dropped.
  With no limit configured there is none.
- **A list element's old position no longer exists** — a restore with no
  placement given is refused, so the application (or the user) decides
  where it goes.
- **Nothing to show or a bad reference** — no versions, an unknown id, a
  `-x` further back than the history: a specific error, nothing changed.
- **The store fails** — a failed version is reported, never skipped; a
  failed restore leaves the current value either as it was or fully
  restored.
- **Versioning is not configured** — the calls say so; nothing else about
  the deployment differs.

## Acceptance Criteria

*Configuration and upgrade*
- **AC-1** (main path, step 1) — When an application upgrades without
  configuring versioning, it starts and serves with no migration and no
  operator step.
- **AC-2** (main path, step 1) — When an application runs without
  versioning configured, nothing new is stored for it.
- **AC-3** (edge: not configured) — When a versioning call is made in an
  application that has not turned versioning on, a specific error is raised
  and nothing is stored.

*Taking a version*
- **AC-4** (main path, step 2) — When the application takes a version of an
  existing property or attribute, a new version exists holding the current
  value, a timestamp, a stable id and the metadata passed.
- **AC-5** (main path, step 2) — When the application takes a version of the
  same unchanged item twice, two versions exist.
- **AC-6** (edge: limit) — When no limit is configured, the 1000th version
  of an item is stored and all 1000 are listed.
- **AC-7** (edge: limit) — When a limit of N is configured and an item has N
  versions, taking a version succeeds and the oldest version is gone.
- **AC-8** (edge: nothing to version) — When the application takes a version
  of an item that does not exist, a specific error is raised and no version
  is created.
- **AC-9** (edge: store fails) — When the store faults while a version is
  taken, the error is raised and the current value is unchanged.

*Invisibility*
- **AC-10** (main path, step 3) — Versions never appear in a property
  listing or a bucket listing.
- **AC-11** (main path, step 3) — Versions never appear in `/properties`
  over HTTP.
- **AC-12** (main path, step 3) — Versions are never returned to a peer.
- **AC-13** (main path, step 3) — Versions never appear in a subscription
  diff.
- **AC-14** (main path, step 3) — A value held only in a version is never
  found by a reverse lookup.
- **AC-15** (main path, step 3) — Taking, listing, reading and removing
  versions fire no hook and register no subscription diff.
- **AC-16** (main path, step 3) — Reading or listing current values does the
  same store work for an item with 1000 versions as for one with none.

*Reading history*
- **AC-17** (main path, step 4) — Listing an item's versions returns id,
  timestamp and metadata for each, newest first, without content.
- **AC-18** (main path, step 4) — Reading a version by id, or by `-x`,
  returns its content; `-1` is the newest.
- **AC-19** (main path, step 4) — Reading all versions returns every version
  with its content.
- **AC-20** (edge: bad reference) — A version id that does not exist gives a
  specific error and changes nothing.
- **AC-21** (edge: bad reference) — A `-x` further back than the history
  gives a specific error and changes nothing.
- **AC-22** (edge: nothing to show) — Listing the versions of an item that
  has none returns an empty list; reading or restoring one gives a specific
  error.

*Restore*
- **AC-23** (main path, step 5) — A restore makes the chosen version's
  content the current value, after saving the previous current value as a
  new version, which is then `-1`.
- **AC-24** (main path, step 5) — The restored version itself stays in the
  history, under the same id.
- **AC-25** (edge: overwrite) — A restore with the pre-restore version
  turned off replaces the current value and creates no version.
- **AC-26** (main path, step 5) — A restore fires the same hooks and
  subscription diff as a normal write of that value.
- **AC-27** (edge: indexed property) — Restoring an indexed property behaves
  exactly as a normal write of that value would, including when another
  actor now holds the value.
- **AC-28** (edge: store fails) — When the store faults during a restore,
  the error is raised and the current value is either the old one or the
  restored one, never partial.

*List elements (AC-29 and AC-32 hold under every option in the Hypothesis;
AC-30 and AC-31 hold only if the library performs the restore into the
list, options L1 and L3, and are dropped under L2)*
- **AC-29** (main path, step 2) — A version of a list element records the
  position the element had, and the version list reports it.
- **AC-30** (main path, step 5) — A restore of a list element with
  "overwrite N", "insert at N" or "append" puts the content there, and the
  other elements keep their order.
- **AC-31** (edge: position gone) — A restore of a list element with no
  placement given, when the recorded position no longer exists, is refused
  with a specific error and nothing changes.
- **AC-32** (main path, step 2) — The versions of one element are unaffected
  by inserting, moving or deleting other elements of the list.

*Delete and removal*
- **AC-33** (edge: item deleted) — After a normal delete of an item with
  versions, its versions are still listed.
- **AC-34** (edge: item deleted) — A restore of a version of a deleted item
  brings the item back as the current value.
- **AC-35** (main path, step 6) — Removing one version by id removes only
  that one, and the `-x` numbering closes the gap.
- **AC-36** (main path, step 6) — "Delete all versions" removes every
  version of the item and leaves the current value.
- **AC-37** (edge: item deleted) — A destructive delete removes the item and
  all its versions.
- **AC-38** (edge: owner gone) — Deleting an actor removes every version of
  its data.
- **AC-39** (edge: owner gone) — Deleting a bucket removes every version of
  its attributes.
- **AC-40** (edge: owner gone) — Revoking a trust removes every version of
  the data that goes with it.

*Automatic versioning (in scope unless research finds it overly complex or
costly; see Open Questions)*
- **AC-41** (main path, step 1) — When automatic versioning is on for an
  item, overwriting it saves the previous value as a version first.
- **AC-42** (edge: item deleted) — When automatic versioning is on for an
  item, a normal delete saves the last value as a version first.
- **AC-43** (main path, step 1) — When versioning is on and automatic
  versioning is off, an ordinary write or delete creates no version.

*Backends*
- **AC-44** — Every criterion above holds on DynamoDB and on PostgreSQL.

Pass/fail before shipping. Success Measures below tell whether the outcome
happened. No living spec covers plain properties or attributes;
`thoughts/specs/property-lists.md` (partial) covers lists, and AC-29 to
AC-32 read as additions to it. `/create_plan` will offer `/create_spec`
for the rest.

## Success Measures

| Measure | Target | How we observe it |
| --- | --- | --- |
| Emm's hand-rolled audit list | deleted, replaced by this | the consumer's repository diff |
| Item types with history in Emm | memories and documents as well as instructions | manual check in Emm |
| Cost of history on ordinary reads | none: same store calls with 0 or 1000 versions | the test behind AC-16 |
| Storage per account with history on | known and bounded by the limit | not observable today: an open question below |
| Next lost-work incident | the owner restores it without help | manual; no metric exists |
| Deployments that do not opt in | no upgrade step, no report | absence of an upgrade note in the changelog beyond "new, off by default"; Emm's own upgrade |

We cannot observe whether any third party adopts it.

## Hypothesis (untested)

A version store of its own in each backend, separate from where current
values live, keyed by the item and a version id. It is only created and used
when the application turns versioning on. Taking a version copies the current
value there with a timestamp and the application's metadata; retention (drop
the oldest past the app-wide limit) happens on that write. A restore is one
atomic step from the application's side: save the current value as a version,
write the chosen one as current, then run the ordinary write path's hooks,
diffs and indexing. Versions are removed with their owner (actor, bucket,
trust) and survive a normal delete of the item. `-1`, `-2` are resolved at
call time from the stored order; the id is what stays stable. Automatic
versioning is a configuration switch (per property name or bucket, as
proposed; the granularity is not confirmed) that makes the ordinary write
and delete paths take a version first.

**List elements: three options to evaluate, none chosen.** The library
addresses a list element by position only. The consumer's elements are JSON
objects that carry an `id` the application maintains (checked by the owner
on 2026-11-26, correcting the earlier answer that elements have no stable
id), beside the content, application metadata and, for a memory, a search
embedding of about a thousand numbers. Documents are attribute lists;
memories are property lists, because other actors subscribe to them, so the
whole element (content, metadata and embedding) is what `/properties` and
subscription diffs carry today.

- **L1, the library gives elements an identity.** Hidden from the
  application's values, followed by the versions, with list operations that
  can address an element by it. Must be optional and must not change what
  an existing list stores or sends.
- **L2, the application names the history; restore returns the value.**
  A version of a list element is filed under a key the application passes
  (its own `id`), with the position recorded as information. Restoring is
  reading the version: the application writes the value to the right
  element itself, and takes a version of the current element first if it
  wants one. No list identity, no placement rules, and hooks and diffs come
  from the application's own write. Cost: for list elements the restore is
  not one all-or-nothing step (AC-28 would cover properties and attributes
  only), and "save current first" is the application's job.
- **L3, L1 plus application-only data per element.** A place for metadata
  that belongs to an element but is never sent on the wire (to
  `/properties`, peers or subscribers), with the stable id as its key. This
  answers a second problem, that content, metadata and embedding travel
  together today, and is probably a feature of its own.

**Constraint (owner, 2026-11-26):** Emm's element ids are stable, but the
library cannot assume every consumer has one. So L2 alone is not enough: a
consumer whose elements carry no id has nothing to pass as the key, and a
position is not a key (AC-32).

Recommendation going into research (untested): L2 as the base, because it
needs nothing from existing lists, which is what "no migration" asks for;
and L1 evaluated inside this feature, as the optional way a consumer
without ids gets a key (the library hands out an element identity the
application can pass where Emm passes its own `id`). If L1 turns out too
costly, the fallback is to say plainly that list-element history needs a
stable key from the application, which is the owner's call. L3 stays a
separate capability.

**Alternatives considered:**
- **Minimal: a helper on today's storage** — versions as ordinary
  attributes in a reserved, hidden bucket per item, no backend change. Not
  chosen: a restore is two writes, so "never partial" (AC-28) is hard, and
  hidden-by-naming is the weakness the consumer's workaround already has.
- **Lateral: append-only storage** — every write adds an immutable row and
  "current" is a pointer, so versions are free and a restore moves the
  pointer. Not chosen: it changes how all storage works and makes every
  write of every deployment pay for history.
- **Automatic versioning as the only mode** — every overwrite keeps the
  previous value, no explicit call. Not chosen as the framing (premise 1):
  the application knows which writes matter, and paying storage on every
  save is what stopped the consumer's workaround. Kept as an opt-in
  addition.

## Not In Scope

- An HTTP or peer-visible history surface — history is private to the
  application in this round; a wire surface touches the protocol
  specification.
- Diffs between versions — the application can compare two contents itself.
- Whole-bucket or whole-actor snapshots — a version is one value; a
  point-in-time copy of many is a different feature.
- Per-item or per-call limits — the limit is app-wide (owner, 2026-11-26).
- Time-based retention (keep 30 days) — count-based is enough to bound
  storage; no one has asked for age.
- Migrating Emm's existing audit lists into the new history — the
  consumer's own adoption work.

## Open Questions

### About the codebase
- Evaluate L1, L2 and L3 (Hypothesis). For L1: how can a list element get
  an identity that survives inserts, moves and deletes of other elements,
  optional per list, without changing what an existing list stores or sends
  (AC-32, with AC-1's "no migration")? Can that identity be the same kind
  of key an application with its own ids passes under L2, so there is one
  interface and not two? For L3: where could per-element data
  live that `/properties`, peers and subscription diffs never carry, and
  what would stop being sent that subscribers rely on today?
- What exactly do `/properties` and a subscription diff carry for a list
  element today: the whole stored value, embedding included?
- Under L2, can the version key be any application string, and is a version
  filed under a key whose element is gone still listed and removable
  (AC-33 applied to lists)?
- Should a version hold the whole stored element or a value the application
  passes? A memory's embedding is most of its bytes and can be recomputed;
  copying it into every version is the storage growth the consumer's
  workaround ruled out.
- Can a version store be added to PostgreSQL with no migration for a
  deployment that does not opt in, and what does a deployment that opts in
  later have to run? Same question for DynamoDB table creation and for
  `check_ready()`.
- Can a restore (save current, write chosen, register diff, re-index) be
  made all-or-nothing on both backends, and where does it sit against
  `DbErrorAfterWrite` (AC-28)?
- Is automatic versioning overly complex or costly? Specifically: how many
  write and delete paths would have to take a version first (properties,
  attributes, list operations, compare-and-swap, conditional create,
  HTTP handlers), and what one extra write per save costs on each backend.
  The answer decides whether AC-41 to AC-43 stay.
- What granularity can automatic versioning be configured at (app-wide, per
  property name, per bucket)?
- How do versions interact with large values: spanned list items, the
  2 MiB ceiling, DynamoDB's row cap, the PostgreSQL key-row limit?
- How is "all versions with content" (AC-19) bounded when there is no limit
  and values are large: paging, or a documented cost?
- Which removal paths exist for an actor, a bucket and a trust, and does
  each reach a new store (AC-38 to AC-40)? Do peer-written data and trust revocation
  delete rows directly, as the property-lists spec says (PLS-D4)?
- What must a custom backend implement, and does a backend without it fail
  at configure time or at the first call?
- Is this a patch, a minor or a major by the release rule, given new
  configuration and a new backend protocol method?
- Can AC-16 be observed with an existing store-call counter in the tests?
- What does a normal write of an indexed value another actor holds do today
  (a logged collision, per the project notes), so that AC-27 can be tested
  against it?
- What does a full copy per version cost in storage on each backend, what
  bounds growth when no limit is configured, and can storage per account be
  observed (the operator is measured on it, and full copies at memory and
  document volume are the wall the consumer's workaround named)?
- When a whole list is deleted or cleared, what happens to the versions of
  its elements?

### About users and the outside world
- **Undecided by the owner:** when versioning is turned off after having
  been on, are existing versions kept, ignored or removed?
- **Undecided by the owner:** L1, L2 or L3 for list elements; research
  evaluates all three.
- **Undecided by the owner (only under L1 or L3):** when a list element is
  restored with no placement given and the recorded position still exists, is the element
  there overwritten or is the version inserted before it? After a move that
  position can hold a different element, so overwriting can destroy data.
- **Undecided by the owner:** with automatic versioning on, does a restore
  create one version of the previous value or two, and does a restore with
  the pre-restore version turned off (AC-25) still leave one?
- **Undecided by the owner:** when a deleted item is restored, there is no
  current value to save first: is nothing saved, or an "empty" version?
- **Undecided by the owner:** is a single version removed by id only, or
  also by `-x`?
- **Accepted by silence, to confirm:** at the limit the oldest version is
  dropped and the new one stored (proposed 2026-11-26, not contradicted).
- **Undecided by the owner:** when the limit is lowered, are the surplus
  versions dropped at once, or at each item's next version?
- **Undecided by the owner:** if L1 is too costly, may list-element
  history require a stable key from the application (consumers without
  element ids then get history for properties and attributes only)?
- Does Emm need a version for a list element that was deleted (AC-33
  applied to lists)?
- What metadata size does Emm need per version (who, how, action today),
  and should the library bound it?
