---
status: proposed
approved: 2026-11-27 by Greger Wedel
---

# Implementation Plan: Version history for properties, attributes and list elements, restored by writing back

**Date:** 2026-11-26
**Feature:** thoughts/features/2026-11-26-version-history-and-restore.md
**Research:** thoughts/research/2026-11-26-version-history-and-restore.md
**Branch:** docs/version-history-and-restore (the plan). Implementation
starts on `release/4.1.0-version-history`, cut from `master` after the
`v4.0.0` tag and rebased on any later 4.0 fix; one PR, one commit per phase.

## Update Log

- **2026-11-27**: After the consumer's review
  (`thoughts/research/2026-11-27-emm-review-of-version-history-plan.md`).
  The library restore of properties and attributes is removed: its only
  known consumer keeps every versioned item as a list element, where the
  plan already has the application write a version back. All three kinds
  now restore the same way, and no backend protocol method is added
  (Removed Phases). `delete_with_versions` moves to Phase 1. A take can
  carry its own `max_versions` (AC-75). The guide gains the consumer's
  patterns. Phases renumbered: 2 is list-element history, 3 is
  documentation. Approval removed; the owner approves the updated plan.

## Overview

An application can keep explicit snapshots of a property, an attribute or a
list element, list and read them, and write one back with the item's normal
write, without the history showing up in a listing, on the
wire, in a diff or in a reverse lookup. The library owns the store, the
retention and the removal with the owner, so a consumer does
not hand-roll an audit list. Headline measures: ordinary reads do the same
store work with 0 or 1000 versions (AC-16), and a deployment that does not
opt in upgrades with no step (AC-1). Ships as 4.1.0.

## Decisions Made

- **Release** [Updated 2026-11-27]: 4.1.0 minor with
  `docs/migration/v4.1.rst` - new configuration and a new public API, no
  backend protocol method; nothing changes without opting in.
- **Specs**: no `/create_spec` first; the Spec Delta starts a partial
  `version-history` spec at merge (owner).
- **Storage**: a hidden partition `{actor_id}$ver` in the properties table
  for every kind - the `$aux` precedent; no new table, hidden by partition.
- **PostgreSQL index** (owner, after evaluation): this plan adds a
  `COLLATE "C"` index on `properties (id, name)`. Start-up requires it only
  with versioning on, so AC-1 holds.
- **Rows**: per version one small head row (timestamp, metadata, position,
  bytes, content up to 4 KB) and, for larger content, body rows; per item
  one marker row naming it and its newest version.
- **Content**: the JSON value the application passes, or the current value
  by default (properties and attributes).
- **Automatic versioning**: not in this round - every write path would have
  to take a version first.
- **Restore** [Updated 2026-11-27] (owner, after the consumer's review):
  the library has no restore call for any kind. An application reads a
  version and writes its content with the item's normal write, which runs
  that write's hooks, diff and reverse-lookup maintenance; it takes a
  version first when the current value is to be kept. The two steps are
  not one transaction. A list element's write can be conditional
  (`update_by_handle`); a property's and an attribute's public write is
  not, so a writer landing between the take and the write is overwritten
  as by any second write.
- **List elements** (owner, after evaluation): history is filed under a key
  the application passes. A re-key call moves a history to a new key. The
  application writes a restored element back itself.
- **Scope of an element key**: actor-wide for property lists, bucket-wide
  for attribute lists; two elements filed under one key share one history.
- **Access**: one namespace, `actor.versions`, so no method is added to a
  store that resolves names by attribute.
- **Reading all**: an iterator, newest first, one version's content in
  memory at a time.
- **Limit**: app-wide `max_versions`, unlimited unless set; every take
  removes all versions past it, never the one just written; a lowered limit
  takes effect at each item's next take.
- **Limit per take** [Added 2026-11-27] (owner): `take(max_versions=N)`
  replaces the app-wide value for that take, higher or lower, and uses the
  same trim. Nothing is stored per item: a take without it trims to the
  app-wide value again.
- **Retention by age** [Added 2026-11-27] (owner): no library call. The
  guide shows a sweep built on the key listing and `remove_all()`.
- **Whole-list delete or clear**: element versions are kept.
- **Replicas, library buckets, system actors**: a version call is refused.
- **Turned off**: versions are kept and unreachable until versioning is on
  again; removal with the actor and the bucket, and the purge call, still
  work.
- **Erasure** (owner, after evaluation): a normal delete keeps history. An
  actor-wide purge works with versioning off, runs when an unvouched actor
  is cleaned on adoption, and has an operator command.
- **Writing back a deleted item** [Updated 2026-11-27]: an ordinary write;
  there is no current value to take first.
- **Remove one**: by id only.
- **AC-16 proof**: exact call counts on DynamoDB, structural on PostgreSQL.
- **Bounds**: key at most 512 characters; metadata a JSON object of at most
  4 KB; content at most `max_bytes` (2 MiB default) on both backends,
  independent of the list limits; each listed version reports its bytes.
- **Falsy content** (plan) [Updated 2026-11-27, a correction]: content a
  write would store as a delete is refused. For an attribute that is any
  falsy value (`attribute.py:446-452`). For a property it is `None` and
  `""` only: a property write encodes `0`, `False`, `[]` and `{}` to JSON
  text before its empty check (`db/dynamodb/property.py:235-248`, the same
  in PostgreSQL) and stores them.
- **What a property version holds** [Added 2026-11-27]: a default take
  holds the stored string, which for a value written as an object is its
  JSON text. Written back as it is, the store holds the same string, but
  the put hook receives a string and the diff carries a JSON string where
  the original write carried an object. An application that writes objects
  decodes the content before writing it back.
- **Attributes** (plan): a version holds data only, not the row's timestamp
  or TTL; written back with `set_attr(name, data)` it has a TTL only if
  the application passes one; an expired row is absent.
- **Order** (plan): every id is minted above the item's newest stored id,
  so a version just written is always `-1`. Two hosts writing at once can
  still tie-break by the random part.
- **Long names** (plan): a name part whose escaped form is over 240 bytes
  is filed under its SHA-256; the marker and head carry the full name.

## Decisions Deferred

- **Library-minted element keys and `move_to`**: deferred by the owner on
  2026-11-26. As drafted they did not fit the consumer's moves (a move
  changes the value; minting invalidates the caller's handle; Evaluation
  Notes 12 to 15, 41, 42). Blocks nothing here. The consumer
  it was drafted for has ids that are never reused and re-keys after a
  move (triage of 2026-11-27), so no consumer waits for it. It is designed
  against a consumer's move code when an application whose elements have
  no id of their own asks for element history.
- **A write together with a version of what it replaces, in one
  transaction** (owner, 2026-11-27): deferred to
  `thoughts/todo/write-with-a-version-in-one-transaction.md`, designed once
  for all three kinds, starting from list elements. Blocks nothing here:
  the two-call form works and its gap is stated in the guide.
- **A batch take, and an export and import of an actor's versions**
  (2026-11-27): `thoughts/todo/versions-batch-take.md` and
  `thoughts/todo/versions-export-import.md`. Block nothing here.

## What We're NOT Doing

- An HTTP or peer-visible history surface - it touches the protocol
  specification.
- Diffs between versions - the application can compare two contents.
- Whole-bucket or whole-actor snapshots - a different feature.
- Stored per-item or per-prefix limits - a take can carry its own limit
  (AC-75), which needs no rule for which names a prefix matches.
- Time-based retention - the library cannot tell a deleted item from a
  live one, and any call would need the same per-actor caller as the sweep
  the guide shows (owner, 2026-11-27).
- A library restore call for a property or an attribute - no known caller;
  it carried two backend protocol methods and a cross-table transaction to
  close a gap any two writes have (owner, 2026-11-27; Removed Phases).
- Automatic versioning (AC-41, AC-42) - see Decisions.
- A library restore into a list (AC-30, AC-31) - placement after a move is
  the application's knowledge.
- Versions of replica and library buckets - not the application's to roll
  back.
- Per-element application-only data (option L3) - a feature of its own.
- A default for `max_versions` - unlimited is the owner's choice (AC-6);
  the guide states the storage risk.
- An environment variable for versioning - a builder call is enough.
- Closing the "write during actor delete" race for good - it is the open
  row V2 of `thoughts/todo/list-items-conditional-create-ttl-and-retained-bodies.md`;
  this plan narrows it and gives the operator a purge.
- Migrating a consumer's audit lists - the consumer's adoption work.

## What Already Exists

- `property_list_span.py:505` `aux_partition` and `property.py:490`
  `_delete_side_partition` - the hidden-partition precedent, its `$` refusal
  and its pre-4.0 actor guard. `ver_partition()` copies the shape.
- `property_list_span.split_parts` and `new_gen()` (`:471`) - splitting and
  id minting, reused. The span join with its length and digest check
  (`list_core.py:1136-1141`) is extracted into one helper both use.
- `list_core.py:2509` `_validate_append_key` - the 512-character,
  no-control-character key rule, reused for names and keys.
- `DbPropertyProtocol` `set`, `get`, `get_range(keys_only=)`,
  `get_last_in_range`, `batch_delete` - all Phase 1 needs. `get_range` is
  inclusive at both ends and unordered (`db/protocols.py:386-411`), so the
  store passes a sentinel upper bound and sorts; it and
  `get_last_in_range` compare bytewise on PostgreSQL
  (`db/postgresql/property.py:787`).
- `db/postgresql/schema.py:237` `ix_attributes_list_rows` and
  `_check_attribute_schema_ready` (`interface/app.py:2050`) - the pattern
  for an index a start-up gate requires.
- `interface/property_store.py:136` `__setitem__` and `:149` `__delitem__`
  - the normal write an application restores with (hook, previous value,
  write, diff) and the delete `delete_with_versions` calls.
- `maintenance/verify_orphans.py:210`, `maintenance/deletions.py`,
  `maintenance/check_ready.py` - operator tooling the plan extends.
- `tests/_read_counters.py`, `tests/_adoption_helpers.make_config(database=)`
  - reused.

## Acceptance Criteria

*Configuration and upgrade*
- **AC-1** — When an application upgrades without configuring versioning,
  it starts and serves with no migration and no operator step.
- **AC-2** — Without versioning configured, nothing new is stored.
- **AC-3** — A version call without versioning on raises
  `VersioningNotConfigured` and stores nothing.

*Taking a version*
- **AC-4** (reworded in plan: content) — Taking a version of a property or
  attribute stores the value passed, or the current value when none is
  passed, with a timestamp, a stable id and the metadata passed.
- **AC-5** — Two takes of the same unchanged item give two versions.
- **AC-6** — With no limit, the 1000th version is stored and all 1000 are
  listed.
- **AC-7** — With a limit of N and N versions, a take succeeds and the
  oldest is gone.
- **AC-8** — A take with no value passed, of an item that does not exist,
  raises `NothingToVersion` and creates no version.
- **AC-9** (reworded in plan: evaluation) — When the store faults during a
  take before the version is stored, `DbError` is raised, the current value
  is unchanged and no version is listed.

*Invisibility*
- **AC-10** — Versions never appear in a property or bucket listing.
- **AC-11** — Versions never appear in `/properties` over HTTP.
- **AC-12** — Versions are never returned to a peer, and the views handed
  to hooks and tools for a peer expose no version call.
- **AC-13** — Versions never appear in a subscription diff.
- **AC-14** — A value held only in a version is never found by a reverse
  lookup, nor indexed by the backfill.
- **AC-15** — Taking, listing, reading and removing versions fire no hook
  and register no diff.
- **AC-16** — Reading or listing current values does the same store work
  for an item with 1000 versions as for one with none.

*Reading history*
- **AC-17** — Listing returns id, timestamp, metadata, position, list name
  and bytes for each version, newest first, without reading a body row.
- **AC-18** — Reading by id or by `-x` returns the content; `-1` is the
  newest; `0`, a positive number or a boolean raises `ValueError`.
- **AC-19** — Iterating returns every version with its content, newest
  first.
- **AC-20** — An id that does not exist raises `VersionNotFound` and
  changes nothing.
- **AC-21** — A `-x` past the history raises `VersionNotFound`.
- **AC-22** (reworded 2026-11-27: no restore) — An item with no versions
  lists empty; reading one raises `VersionNotFound`.

*Restore*
- ~~**AC-23**~~ to ~~**AC-28**~~ — dropped 2026-11-27: no library restore
  call (owner). AC-76 states what a write-back gives.

*List elements*
- **AC-29** (reworded in plan) — A version of a list element records the
  position and list name the application passes, and the listing reports
  them.
- ~~**AC-30**~~, ~~**AC-31**~~ — dropped: the application writes a list
  element back.
- **AC-32** — The versions filed under one key are unaffected by any
  change to the list or to other elements.

*Delete and removal*
- **AC-33** — After a normal delete of an item, after
  `delete_properties()`, `clear()` and an HTTP delete, its versions are
  still listed.
- ~~**AC-34**~~ — dropped 2026-11-27: with AC-23; a deleted item is
  written back as any version is (AC-76).
- **AC-35** — Removing one version by id removes only that one, and `-x`
  closes the gap.
- **AC-36** — `remove_all()` removes every version of the item and leaves
  the current value.
- **AC-37** — `delete_with_versions()` removes the item and all its
  versions.
- **AC-38** — Deleting an actor removes every version of its data, with
  versioning on or off.
- **AC-39** — Deleting a bucket, or all buckets, removes every version of
  its attributes and its lists' elements.
- **AC-40** (reworded in plan) — A version call on a `remote:` bucket, a
  library bucket (the token buckets included) or a system actor raises
  `NotVersionable` and stores nothing.
- ~~**AC-41**~~, ~~**AC-42**~~ — dropped: no automatic versioning.
- **AC-43** — With versioning on, an ordinary write or delete creates no
  version.
- **AC-44** — Every criterion holds on DynamoDB and on PostgreSQL.

*Added in plan*
- **AC-45** (added in plan: L2) — The names and keys that have versions are
  listed, including items that no longer exist.
- ~~**AC-46**~~, ~~**AC-47**~~, ~~**AC-48**~~ — dropped: minted keys and
  `move_to` are deferred (Decisions Deferred).
- **AC-49** (added in plan: size) — A version up to `max_bytes` is stored
  and read back intact on both backends; one over it raises
  `VersionTooLarge` and stores nothing.
- **AC-50** (added in plan: bounds) — A key over 512 characters or with a
  control character, or metadata that is not a JSON object or is over 4 KB,
  raises `ValueError` and stores nothing; a 512-character non-ASCII key
  works on both backends.
- **AC-51** (added in plan: turned off) — With versioning turned off after
  use, version calls raise `VersioningNotConfigured`; on again, the earlier
  versions are listed.
- **AC-52** (added in plan: limit; reworded 2026-11-27) — After the limit
  is lowered, an item keeps its surplus until its next take and has exactly
  the limit that take applies after it.
- **AC-53** (added in plan: bounds) — Each listed version reports the bytes
  of its content.
- ~~**AC-54**~~ — dropped 2026-11-27: no backend method is added, so no
  backend is refused for lacking one.
- **AC-55** (added in plan: list delete) — After a list is deleted or
  cleared, its elements' versions are still listed under their keys.
- **AC-56** (added in plan) — `remove` with `-x`, or with an id that does
  not exist, changes nothing and raises `ValueError` or `VersionNotFound`.
- ~~**AC-57**~~ — dropped 2026-11-27: with AC-23.
- **AC-58** (added in plan: operator) — `actingweb-verify-orphans` reports
  the version rows of a gone actor and not those of a live one.
- ~~**AC-59**~~ — dropped: deferred with AC-46.
- **AC-60** (added in plan: evaluation) — A property or attribute version
  whose content the item's row cannot hold on this backend is refused at
  the take with `VersionTooLarge` (reworded 2026-11-27: no restore).
- **AC-61** (added in plan: L2 restore path) — Reading a list-element
  version returns content that, written back with the list's own calls,
  equals the element as passed to the take.
- ~~**AC-62**~~ — dropped: deferred with AC-47.
- **AC-63** (added in plan: owner, re-key) — After `rename(new_key)`, every
  version is listed under the new key with its id, and none under the old;
  a fault leaves each version under at least one key and a repeat finishes;
  a new key that already has other versions raises `VersionKeyExists`.
- **AC-64** (added in plan: owner, erasure) — `actor.versions.purge()`
  removes every version of the actor, with versioning on or off.
- **AC-65** (added in plan: owner, erasure) — `actingweb-versions report`
  prints an actor's items, versions and bytes; `purge --actor ID` removes
  its versions only with `--apply`.
- **AC-66** (added in plan: owner, index) — On PostgreSQL with versioning
  on and the index missing, start-up is refused with `VersioningNotReady`
  naming `alembic upgrade head`; with versioning off it starts.
- ~~**AC-67**~~ — dropped 2026-11-27: with AC-23; a write-back is the
  store's own write and updates its cache as any write does.
- **AC-68** (added in plan: evaluation; reworded 2026-11-27, a correction) —
  Falsy content for an attribute version, and `None` or `""` for a property
  version, raises `ValueError` and stores nothing; `0`, `False`, `[]` and
  `{}` are stored for a property and read back as passed.
- **AC-69** (added in plan: evaluation) — A listing of names or keys
  returns each with its newest version's id, timestamp and metadata, takes
  a prefix, and reads no version row; the buckets that have versions are
  listed.
- **AC-70** (added in plan: evaluation) — Removing element histories by key
  prefix removes exactly the histories whose key starts with it.
- **AC-71** (added in plan: owner, erasure) — When an unvouched actor is
  cleaned on adoption, its versions are gone.
- **AC-72** (added in plan: evaluation; reworded 2026-11-27: no restore) —
  At the limit, a take never removes the version it wrote.
- **AC-73** (added in plan: evaluation) — Creating an actor with a
  caller-supplied id that is free leaves it with no versions, whatever an
  earlier actor of that id left; creating an id that exists removes
  nothing.
- **AC-74** (added in plan: evaluation) — The names and keys listed are
  exactly those with at least one version, after any order of concurrent
  takes and removals has finished.
- **AC-75** (added 2026-11-27: owner, limit per take) — A take with
  `max_versions=N` leaves that item with at most N versions, whatever the
  app-wide limit and with none set, and never removes the version it
  wrote; N below 1 raises `ValueError` and stores nothing; a later take
  without it trims to the app-wide limit.
- **AC-76** (added 2026-11-27: owner, write-back) — With no put hook that
  changes the value: the content of a default take of a property, written
  with the property's normal write, leaves the stored value equal to the
  one taken; the content of an attribute version, written with
  `set_attr`, leaves the data equal to the data taken; both hold for an
  item that was deleted since. A property written back fires the hooks
  and diff of that write.

## Traceability

`C` `tests/test_versions_config.py`, `S` `tests/test_versions_store.py`,
`I` `tests/test_versions_invisibility.py`, `X`
`tests/test_versions_removal.py`, `E`
`tests/test_versions_elements.py`, `O` `tests/test_versions_command.py`,
`H` `tests/integration/test_versions_http.py`. All but `H` build their
config with `versions_config`, which follows `DATABASE_BACKEND`.

| AC | Phase | Test | Status |
| --- | --- | --- | --- |
| AC-1 | 1 | `C::test_the_versioning_gate_is_not_run_when_off` | Not run |
| AC-2 | 1 | `C::test_no_version_partition_row_without_versioning` (control: a row exists once on) | Not run |
| AC-3 | 1 | `C::test_every_version_call_is_refused_when_off` (one table, extended per phase) | Not run |
| AC-4 | 1 | `S::test_take_holds_passed_or_current_value` | Not run |
| AC-5 | 1 | `S::test_two_takes_of_an_unchanged_item_are_two_versions` | Not run |
| AC-6 | 1 | `S::test_a_thousand_versions_are_listed_without_a_limit` (2 KB metadata each, past a 1 MB page) | Not run |
| AC-7 | 1 | `S::test_the_oldest_goes_at_the_limit` | Not run |
| AC-8 | 1 | `S::test_take_of_a_missing_item_is_refused` | Not run |
| AC-9 | 1 | `S::test_a_fault_in_take_raises_and_lists_nothing` (faults the bodies, then the head); `S::test_a_marker_fault_after_the_head_is_repaired_by_the_next_read` | Not run |
| AC-10 | 1 | `I::test_listings_never_show_versions` (control: `all()` shows them) | Not run |
| AC-11 | 1 | `H::test_properties_over_http_never_show_versions` | Not run |
| AC-12 | 1 | `H::test_a_peer_never_receives_versions`; `I::test_the_authenticated_views_expose_no_version_call` | Not run |
| AC-13 | 1 | `I::test_no_diff_carries_a_version` (real subscription; control: a write registers one) | Not run |
| AC-14 | 1 | `I::test_reverse_lookup_never_finds_a_versioned_value`; `I::test_backfill_and_report_ignore_version_rows` | Not run |
| AC-15 | 1 | `I::test_version_calls_fire_no_hook_and_no_diff` (control: a write fires both) | Not run |
| AC-16 | 1 | `I::test_reads_cost_the_same_with_a_thousand_versions` (DynamoDB counts); `I::test_current_value_reads_never_name_the_version_partition` (both) | Not run |
| AC-17 | 1 | `S::test_all_is_newest_first_and_reads_no_body_row` | Not run |
| AC-18 | 1 | `S::test_get_by_id_and_by_negative_index`; `S::test_get_rejects_zero_positive_and_bool_refs` | Not run |
| AC-19 | 1 | `S::test_iter_returns_every_version_one_content_at_a_time` | Not run |
| AC-20 | 1 | `S::test_an_unknown_id_is_refused` | Not run |
| AC-21 | 1 | `S::test_an_index_past_the_history_is_refused` | Not run |
| AC-22 | 1 | `S::test_an_item_without_versions_lists_empty` | Not run |
| AC-29 | 2 | `E::test_a_version_records_position_and_list_name` | Not run |
| AC-32 | 2 | `E::test_list_changes_do_not_touch_a_history` | Not run |
| AC-33 | 1 | `X::test_versions_survive_a_normal_delete`; `X::test_versions_survive_delete_properties_and_clear`; `H::test_an_http_delete_keeps_history` | Not run |
| AC-35 | 1 | `S::test_remove_one_closes_the_gap` | Not run |
| AC-36 | 1 | `S::test_remove_all_leaves_the_value` | Not run |
| AC-37 | 1 | `X::test_delete_with_versions_removes_both` | Not run |
| AC-38 | 1 | `X::test_actor_delete_removes_versions_on_and_off` | Not run |
| AC-39 | 1, 2 | `X::test_bucket_delete_removes_attribute_versions`; `X::test_buckets_delete_removes_all_bucket_versions`; `E::test_bucket_delete_removes_element_versions` | Not run |
| AC-40 | 1 | `X::test_replica_library_and_system_scopes_are_refused`; `X::test_every_bucket_literal_in_the_package_is_refused` | Not run |
| AC-43 | 1 | `I::test_ordinary_writes_create_no_version` (control: a take creates one) | Not run |
| AC-44 | all | `C::test_the_suite_runs_on_the_configured_backend`; every row above under the Full tier's two backend runs | Not run |
| AC-45 | 1, 2 | `S::test_names_include_deleted_items`; `E::test_keys_include_deleted_elements` | Not run |
| AC-49 | 1 | `S::test_a_large_version_reads_back_intact`; `S::test_a_version_over_max_bytes_is_refused` | Not run |
| AC-50 | 1 | `S::test_key_and_metadata_bounds`; `S::test_a_long_non_ascii_key_works` | Not run |
| AC-51 | 1 | `C::test_off_then_on_again_shows_the_earlier_versions` | Not run |
| AC-52 | 1 | `S::test_a_lowered_limit_trims_at_the_next_take` | Not run |
| AC-53 | 1 | `S::test_all_reports_content_bytes` | Not run |
| AC-55 | 2 | `E::test_list_delete_and_clear_keep_element_versions` | Not run |
| AC-56 | 1 | `S::test_remove_by_negative_index_is_refused`; `S::test_remove_of_an_unknown_id_raises_version_not_found` | Not run |
| AC-58 | 1 | `tests/test_verify_orphans.py::test_version_rows_of_a_gone_actor_are_orphans`; `::test_version_rows_of_a_live_actor_are_not_orphans` | Not run |
| AC-60 | 1 | `S::test_content_the_row_cannot_hold_is_refused_at_take` | Not run |
| AC-61 | 2 | `E::test_a_version_written_back_equals_the_element` | Not run |
| AC-63 | 2 | `E::test_rename_moves_a_history`; `E::test_a_rename_fault_loses_nothing_and_a_repeat_finishes`; `E::test_rename_onto_a_used_key_is_refused` | Not run |
| AC-64 | 1 | `X::test_purge_removes_everything_on_and_off` | Not run |
| AC-65 | 1 | `O::test_report_prints_items_versions_and_bytes`; `O::test_purge_writes_only_with_apply`; `O::test_purge_of_a_live_actor_needs_the_live_flag`; `tests/test_operator_command_store.py` (the command joins its store-first and no-prefix cases) | Not run |
| AC-66 | 1 | `tests/test_versions_pg_index.py::test_start_is_refused_without_the_index`; `::test_an_invalid_index_is_refused`; `::test_start_without_versioning_ignores_the_index`; `::test_check_ready_reports_the_index_gate` (PostgreSQL only) | Not run |
| AC-68 | 1 | `S::test_content_a_write_would_delete_is_refused` (per kind); `S::test_zero_false_and_empty_containers_are_kept_for_a_property` | Not run |
| AC-69 | 1, 2 | `S::test_names_carry_the_newest_version_and_read_no_version_row`; `S::test_buckets_with_versions_are_listed`; `E::test_keys_by_prefix` (a key long enough to be filed under its digest included) | Not run |
| AC-70 | 2 | `E::test_remove_by_prefix_removes_only_matching_histories` (long keys included); `E::test_an_empty_prefix_is_refused` | Not run |
| AC-71 | 1 | `X::test_an_adoption_clean_purges_versions` | Not run |
| AC-72 | 1 | `S::test_a_take_never_trims_itself` | Not run |
| AC-73 | 1 | `X::test_a_recreated_actor_id_has_no_history`; `X::test_creating_an_existing_id_purges_nothing` | Not run |
| AC-74 | 1 | `S::test_a_take_racing_remove_all_stays_listed`; `S::test_concurrent_takes_leave_the_newest_in_the_listing`; `S::test_removing_the_only_version_unlists_the_item` | Not run |
| AC-75 | 1, 2 | `S::test_a_take_can_carry_its_own_limit` (below and above the app-wide limit, and with none); `S::test_a_per_take_limit_below_one_is_refused`; `S::test_a_take_without_its_limit_falls_back_to_the_app_wide_one`; `E::test_an_element_take_can_carry_its_own_limit` | Not run |
| AC-76 | 1 | `S::test_a_property_default_take_written_back_stores_the_same_string` (control: the hook and diff of a write fire); `S::test_an_attribute_version_written_back_equals_the_data_taken`; `S::test_a_deleted_item_is_written_back` | Not run |

The dropped criteria have no row. No criterion is manual-only.

## Spec Delta

### `thoughts/specs/version-history.md` (new spec, partial)

- **ADDED** (Configuration) — Versioning is off unless `with_versioning()`
  is called; off, nothing is stored and version calls raise
  `VersioningNotConfigured`; versions written earlier are kept and listed
  when it is on again. (AC-1 to AC-3, AC-51)
- **ADDED** (Taking) — A version holds the passed JSON value, or the
  current value of a property or attribute read from the store, with an id
  above every stored one, a timestamp, metadata and its bytes. (AC-4, AC-5,
  AC-8, AC-9, AC-53)
- **ADDED** (Bounds) — Keys, metadata and content are bounded; content
  a write would store as a delete (any falsy value for an attribute, `None`
  and `""` for a property) and content the item's row cannot hold are
  refused. (AC-49, AC-50, AC-60, AC-68)
- **ADDED** (Retention) — With `max_versions=N`, app-wide or passed to the
  take, a take removes all versions past N except the one it wrote; the
  take's own value wins; nothing else trims. (AC-6, AC-7, AC-52, AC-72,
  AC-75)
- **ADDED** (Invisibility) — Versions appear in no listing, HTTP answer,
  peer answer, diff or reverse lookup, fire no hook, and cost a read of
  current values nothing. (AC-10 to AC-16, AC-43)
- **ADDED** (Reading) — `all()` is newest first without content; `get`
  takes an id or `-x`; iteration yields content; names and keys are listed
  with their newest version. (AC-17 to AC-22, AC-45, AC-69, AC-74)
- **ADDED** (Writing back) — There is no restore call. The content read
  from a version, written with the item's normal write, makes the current
  value what it was at the take; that write fires its own hooks and diff.
  (AC-61, AC-76)
- **ADDED** (Removal) — Versions survive a normal delete; they go with
  `remove`, `remove_all`, `delete_with_versions`, `purge`, the bucket, the
  actor and an adoption clean. (AC-33, AC-35 to AC-39, AC-56, AC-64, AC-71)
- **ADDED** (Scope) — Replica buckets, library buckets and system actors
  are refused. (AC-40)
- **DECISION** — Versions live in the `{actor_id}$ver` partition of the
  properties table, for attributes too; a release that moves them migrates
  them.
- **DECISION** — An attribute version holds data only; written back, it
  has a TTL only if the application passes one.
- **DECISION** — A take and the write that follows it are two store
  calls. Only a list element's write can be conditional; a property's or
  attribute's write overwrites a value written in between.
- **DECISION** — A take racing an actor delete is not prevented: it can
  leave rows that `actingweb-versions purge` removes.
- **DECISION** — A process on 4.0.x does not know `$ver`: versioning is
  turned on only when every process, operator commands included, runs 4.1.
- **DECISION** — No automatic versioning and no wire surface; a later plan
  starts from the feature document's AC-41, AC-42 and Not In Scope.

### `thoughts/specs/property-lists.md`

- **ADDED** (History) — A list element's versions are filed under a key
  the application passes, per actor (property lists) or per bucket
  (attribute lists); they are unaffected by the list and survive its
  deletion; `rename` moves a history to a new key. (AC-29, AC-32, AC-55,
  AC-61, AC-63, AC-70)
- **DECISION** — List storage is unchanged by element history: nothing is
  written to an envelope, and the key is the application's (PLS-D2 is not
  engaged).

### `thoughts/specs/actor-creation.md`

- **ADDED** (Adoption) — When a sign-in cleans an actor in place, its
  versions are removed; its properties stay as before. (AC-71)
- **ADDED** (Factory) — When an actor is created with a caller-supplied id
  that is free, version rows an earlier actor of that id left are removed
  before the actor exists; a fault fails the create. (AC-73)

### `thoughts/specs/startup-readiness.md`

- **ADDED** (Versioning) — With versioning on, `check_ready()` refuses a
  PostgreSQL store lacking the `properties` name index, with
  `VersioningNotReady`. (AC-66)

### `thoughts/specs/operator-commands.md`

- **MODIFIED OPC-9** — "it reports each start-up gate as ready, ready at
  first start, or REFUSED" → the same, with a versioning gate reported only
  when `--versioning` is passed (OPC-D3). (AC-66)
- **ADDED** (Versions) — `actingweb-versions report [--actor ID]` and
  `purge (--actor ID | --ids-file F) [--live] [--apply]`; a dry run writes
  nothing; each id is printed as live or gone, and a live actor is purged
  only with `--live`. `actingweb-deletions resume` purges the versions of
  an unfinished deletion before marking it finished. (AC-65, AC-38)
- **ADDED** (Orphans) — `actingweb-verify-orphans` treats `{id}$ver` as its
  actor's partition. (AC-58)
- **ADDED** (Reverse lookup) — The empty-store test ignores `$ver`
  partitions. (AC-1)

## Interfaces

```python
ActingWebApp.with_versioning(*, max_versions: int | None = None,
                             max_bytes: int = 2 * 1024 * 1024) -> ActingWebApp

actor.versions -> VersionStore   # also VersionStore(actor_id, config, *, property_store=None)
                                 # property_store: only delete_with_versions uses it
  .property(name) -> ItemVersions
  .attribute(bucket, name) -> ItemVersions
  .list_element(key) -> ElementVersions                    # Phase 2
  .attribute_list_element(bucket, key) -> ElementVersions  # Phase 2
  .properties(prefix="") -> list[VersionedItem]            # name, newest VersionInfo, renaming_to
  .attributes(bucket, prefix="") -> list[VersionedItem]
  .buckets() -> list[str]
  .list_elements(prefix="") / .attribute_list_elements(bucket, prefix="")   # Phase 2
  .remove_list_elements(prefix) / .remove_attribute_list_elements(bucket, prefix) -> int
  .purge() -> int                                          # works with versioning off

ItemVersions:    take(content=CURRENT, *, metadata=None, max_versions=None) -> VersionInfo
                 delete_with_versions() -> None
ElementVersions: take(content, *, metadata=None, position=None, list_name=None,
                      max_versions=None) -> VersionInfo
                 rename(new_key) -> int
both:            all() -> list[VersionInfo]; get(ref: str | int) -> Version
                 __iter__ -> Iterator[Version]; remove(version_id) -> None; remove_all() -> int

VersionInfo: id, timestamp, metadata, position, list_name, bytes;  Version: + content
```

Errors, in `actingweb/versions.py`, exported from `actingweb`, each carrying
the item and reference: `VersioningError(Exception)`;
`VersioningNotConfigured`; `NothingToVersion`;
`VersionNotFound(VersioningError, LookupError)`;
`VersionTooLarge(VersioningError, ValueError)`; `NotVersionable`;
`VersionKeyExists`; `VersionRenamePending` (carries the pending new key);
`VersioningNotReady(VersioningError)`, which `interface/app.py` subclasses
with `StoreNotReady` for the gate. Bounds and bad references are
`ValueError`.

Rows in partition `{actor_id}$ver` (`<scope>` is `p/<name>`, `l/<key>`,
`b/<bucket>/a/<name>` or `b/<bucket>/e/<key>`):

```text
vn/<scope>                 marker: {"item":[full names],"newest":{"id","ts","meta"}}
v/<scope>/h/<id>           head:   {"v":1,"item":[...],"ts","meta","pos","list","bytes","sha256",
                                    "content":<JSON value>}  or  "parts":<n> in place of content
v/<scope>/c/<id>/<nnnn>    content body, 350,000 bytes each
<id> = new_gen(), raised above the item's newest stored id
```

A name part has `%`, `/` and `~` escaped; a part over 240 bytes is `~` plus
its SHA-256 hex. Version ids are checked against their format before any
store call. Reads are by range (`get_range`, `get_last_in_range`), never
`get_prefix`: a scope prefix ends in `/` and its upper bound is the same
text ending in `0`; an application prefix is bounded by its last code point
plus one, and the result is filtered by `startswith`. A prefix listing or
removal also reads the `~` range and filters on each marker's full name.

The marker is an index, kept in step with the heads by conditional writes
only (`create_if_not_exists`, `set_if_value_equals`,
`delete_if_value_equals`): it is created before an item's first head,
advanced after a head only to a higher id, re-pointed or deleted after a
removal only if unchanged since it was read. A lost compare re-reads and
tries again; `all()` and the next take repair a marker that lags. A marker
with no newest version is not listed.

No backend protocol method is added. The store uses `set`, `get`,
`get_range`, `get_last_in_range`, `batch_delete` and the three conditional
writes, which every backend has.

Writing back: `Version.content` is what the item's normal write takes
(`actor.properties[name] = content`, `set_attr(name, content)`, a list's
own calls). A property's default take holds the stored string (Decisions).
`take(max_versions=N)`: N is an `int` of at least 1, not a `bool`; `None`
means the app-wide value. A take cannot ask for "unlimited" when an
app-wide limit is set.

## Phase 1: Index, version store, removal and operator tooling

### Changes

- `actingweb/db/postgresql/schema.py`, a new Alembic revision under
  `db/postgresql/migrations/versions/` - index `ix_properties_name_c` on
  `(id, name COLLATE "C")`, built concurrently as the attribute-list index
  revision was.
- `actingweb/versions.py` (new) - `ver_partition()` (refuses an id with `$`
  and a partition that is a live actor's own id), row names, ids, the
  encoding, `VersionStore`, `ItemVersions`, markers,
  retention, bounds, name guards (`list:` prefix, control characters), the
  scope rule, errors, and `purge` at item, bucket and actor level.
  - Take: read current from the backend (an expired attribute is absent),
    create the marker if absent, read the newest id, write bodies, then the
    head, then advance the marker. A fault after the head is logged, not
    raised: the version is stored and listed. With
    a limit (the take's `max_versions`, else the app-wide one): one range read of the item's head names, then for each surplus
    version a point read of its head, delete the head, delete its bodies.
    A trim fault is logged, not raised; the next take trims again.
  - Removal order is head, then bodies; `remove` of the newest re-points
    the marker, and of the only version deletes it; `remove_all` sweeps the
    item's prefix for body rows no head names and deletes the marker last,
    conditionally, so a take that landed meanwhile stays listed.
  - A read joins bodies through the shared helper; a wrong length or digest
    raises `VersionNotFound`.
    - `delete_with_versions`: the item's delete, only if the store holds a
    current value, then `remove_all`; so a repeat after a fault finishes
    and sends no second delete diff. The delete is not a version call
    (AC-15 covers the removal half only). A property is deleted through
    `property_store` when the store has one, so it registers its diff as
    `del actor.properties[name]` does; a core-level `VersionStore` deletes
    as the core store does. An attribute is deleted with `delete_attr` on
    an `Attributes` object of its own; one the application already loaded
    keeps its cached value, as after a delete by any other object.
  - Purge walks marker names (keys only), purges item by item, then
    sweeps what is left under its scope (`v/` and `vn/` for an actor,
    `v/b/<bucket>/` and `vn/b/<bucket>/` for a bucket), so an interrupted
    purge has made progress and a row without a marker still goes. A scope
    that cannot have versions is skipped without a read.
  - The check that `{id}$ver` is not a live actor's own id runs once per
    `VersionStore`.
- `actingweb/constants.py` - `LIBRARY_BUCKETS` and the `mcp_`, `spa_`
  prefixes; `oauth2_server/token_manager.py`, `client_registry.py` and
  `oauth_session.py` take their bucket names from it.
- `actingweb/config.py`, `actingweb/interface/app.py` - `with_versioning`;
  `max_versions` below 1 is a `ValueError`; `_check_versioning_ready` as a
  gate run only with versioning on (the PostgreSQL index);
  `VersioningNotReady`.
- `actingweb/interface/actor_interface.py` - the `versions` property, which
  passes `property_store=`.
- `actingweb/actor.py` - `Actor.delete` purges once, directly before the
  actor row goes (`:1716`), with `step()` around it, on or off. A create
  with a caller-supplied id reads whether `{id}$ver` holds a row, after a
  read has shown the id free and before the actor row is written, and
  purges it; a fault fails the create, as a failed tombstone clear does
  (`:1223-1247`).
- `actingweb/attribute.py` - `Attributes.delete_bucket()` purges the
  bucket's versions first, and a purge fault raises before the bucket's
  rows go; `Buckets.delete()` purges every bucket's versions first, with
  the same fault order.
- `actingweb/oauth2.py` - the adoption clean-in-place calls `purge` after
  `purge_relationships` (`:3101`); a purge fault leaves the actor unvouched
  for the next sign-in, as a failed relationship wipe does. The properties
  themselves stay, as today.
- `actingweb/maintenance/versions.py` (new) and `pyproject.toml` -
  `actingweb-versions report | purge`; `docs/requirements.txt` regenerated
  in the same commit.
- `actingweb/maintenance/deletions.py` - the unfinished branch of `resume`
  purges `{id}$ver` once the actor row is confirmed absent and before
  `mark_finished`, so a fault leaves it for the next run.
- `actingweb/maintenance/verify_orphans.py` - `classify_rows` strips `$ver`.
- `actingweb/maintenance/property_lookup.py` - `properties_table_empty`
  ignores ids ending in `$ver` (both statements).
- `actingweb/maintenance/check_ready.py` - the gate behind `--versioning`.
- `actingweb/__init__.py` - exports, with `tests/test_init_docstring.py`.
- `thoughts/todo/bounded-list-read.md` - its index prerequisite is met.
- `tests/_versions_helpers.py` (new) - `versions_config`,
  `property_fault(config, method, matches)` (faults one chosen property
  row), `record_partitions(config)` (the partition each read named);
  `tests/integration/test_harness.py` - a `versioning` argument.

### New Tests (written first: `/implement_plan` sees them fail before coding)

- Every Phase 1 row of the Traceability table.
- `tests/test_versions_pg_index.py::test_each_version_read_shape_uses_the_index`
  — `EXPLAIN` through PREPARE/EXECUTE names the index for the item range,
  the marker range, the newest-id read and the prefix read (PostgreSQL
  only; precedent `tests/integration/test_attribute_list_migration.py:243`).
- `S::test_take_cost_per_kind` (the reads and writes of a store's first
  take and of a later one, stated per kind) and
  `S::test_a_limited_take_reads_no_body_row` — DynamoDB call counts.
- `S::test_a_head_never_exceeds_the_row_cap` — 4 KB content of quotes,
  4 KB metadata, a 512-character non-ASCII key.
- `S::test_a_trim_fault_is_logged_and_the_next_take_trims`.
- `S::test_orphan_bodies_are_invisible_and_removed_by_remove_all`.
- `S::test_a_get_racing_a_remove_raises_version_not_found`.
- `S::test_names_with_slash_percent_and_tilde_do_not_collide` — `a/b`
  against `a%2Fb`, `x` against `x/y`, a literal `~<digest>` against a long
  name with that digest.
- `S::test_empty_none_and_list_prefixed_names_are_refused`;
  `S::test_explicit_none_is_content_not_current`;
  `S::test_content_json_cannot_encode_is_refused`;
  `S::test_content_with_a_lone_surrogate_reads_back_as_a_write_stores_it`.
- `S::test_two_takes_in_one_millisecond_are_both_kept_in_order`.
- `S::test_take_reads_current_from_the_store_not_the_instance`.
- `X::test_a_recreated_bucket_has_no_history`;
  `X::test_a_bucket_purge_fault_keeps_the_bucket`;
  `X::test_an_interrupted_purge_leaves_fewer_rows`;
  `X::test_an_actor_whose_id_ends_in_ver_is_never_written_to`;
  `X::test_an_unfinished_deletion_resume_purges_versions`;
  `X::test_a_purge_fault_in_resume_leaves_it_unfinished`;
  `X::test_a_create_time_purge_fault_fails_the_create`;
  `X::test_a_replica_bucket_delete_reads_no_version_row`;
  `X::test_a_bucket_purge_removes_rows_without_a_marker`;
  `X::test_an_expired_attribute_is_absent`.
- `C::test_properties_table_empty_ignores_version_rows` (DynamoDB, and
  PostgreSQL in an isolated schema).
- `tests/test_actingweb_app.py::TestWithVersioning`.
- `X::test_delete_with_versions_finishes_after_a_fault`;
  `X::test_delete_with_versions_of_a_property_registers_the_delete_diff`;
  `X::test_a_repeated_delete_with_versions_registers_no_second_diff`;
  `X::test_delete_with_versions_of_an_attribute_deletes_the_row`.
- `S::test_a_written_back_default_take_registers_the_stored_string` (the
  diff blob and the hook's argument are the string; decoded first, they
  are the object).
- `S::test_a_per_take_limit_that_is_a_bool_is_refused`;
  `S::test_a_per_take_limit_trims_no_other_item`.
- `S::test_an_attribute_written_back_carries_no_ttl`;
  `S::test_a_write_back_onto_a_name_a_list_took_raises_list_name_taken`
  (the write's own refusal, pinned here because the guide relies on it).

### Failure Scenarios

- Take, fault after bodies - orphan bodies, invisible, reaped by
  `remove_all` and the purges, counted by `report` - tested.
- Two hosts take at once at the limit - both trim; deleting an absent row
  is a no-op - `S::test_concurrent_takes_at_the_limit_end_at_the_limit`.
- Hosts with different limits in a rolling deploy - each trims to its own;
  stated in the guide.
- A take lands during an actor delete - the purge runs last, so only a
  take after it leaves rows; `actingweb-versions purge` removes them, and a
  later create of that id clears them - stated.
- A 4.0.x process deletes an actor - its versions stay; the migration guide
  says when to turn versioning on.
- Purge interrupted - progress kept; a repeat finishes - tested.
- Takes of one item with different per-take limits, or one take without
  its limit - each trims to the limit it carries, so the smallest one seen
  decides what is left; stated in the guide (pass it at every take of that
  kind).
- A write between a take and the write-back of a property or attribute -
  overwritten, as by any second write; its value is in no version unless
  its writer took one; stated in the guide.
- `delete_with_versions` faults after the delete - the versions stay, as
  after a normal delete; a repeat removes them - tested.

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] The Phase 1 unit tests alone with `DATABASE_BACKEND=postgresql`
- [ ] `alembic upgrade head`, then `alembic downgrade -1`, on the test
      database
- [ ] Full tier before the phase commit

### Implementation Status: Not Started

---

## Phase 2: List-element history by key

### Changes

- `actingweb/versions.py` - the element scopes, `ElementVersions` (its
  `take` carries `max_versions` as the item one does), `rename`, the key listings with a prefix, removal by prefix. No change to
  `list_core.py`, `property_list.py` or `attribute_list.py`.
  - `rename` first records the new key in the old key's marker, then
    copies each version to the new key, oldest first (bodies, head), writes
    the new marker, removes the old key's versions and its marker last. A
    repeat finds the record and resumes, whichever step the earlier call
    reached. A new key that has versions, with no such record naming it, is
    `VersionKeyExists`. While the record is there, a take under the old
    key, or a rename of it to another key, raises `VersionRenamePending`
    naming the pending key, and the listing shows it. Before the old marker
    goes, the old key's range is read again and anything a concurrent take
    left is copied too.
  - Removal by prefix refuses an empty prefix.
  - A key is the application's string, stored as given; it is validated as
    an `append_once` key is.
- `actingweb/interface/actor_interface.py` - nothing new; the methods are
  on `VersionStore`.

### New Tests (written first)

- Every Phase 2 row of the Traceability table, on the real backends.
- `E::test_two_elements_filed_under_one_key_share_a_history`.
- `E::test_property_and_attribute_element_keys_are_separate_scopes`.
- `E::test_rename_to_the_same_key_is_refused`.
- `E::test_a_rename_that_died_while_removing_the_old_key_is_finished`.
- `E::test_a_take_under_a_key_being_renamed_is_refused`.
- `E::test_a_pending_rename_is_listed_and_a_different_target_is_refused`.
- `E::test_a_take_that_slipped_past_the_record_is_carried_over_or_stays_listed`.
- `E::test_rename_of_a_large_history_keeps_every_body`.
- `E::test_element_calls_are_refused_for_replica_and_library_buckets`.
- `C::test_every_version_call_is_refused_when_off` - extended.

### Failure Scenarios

- Rename dies part-way - each version is under at least one key; a repeat
  finishes - AC-63.
- Two calls of the same rename at once - both find the record and copy
  the same ids with the same content -
  `E::test_concurrent_calls_of_one_rename_lose_nothing`.
- A take that read the marker before the record and wrote after the last
  re-read - its version stays under the old key, listed, and nothing is
  lost; stated in the guide.
- An application files an `append_once` key here - it is stored in plain
  text, unlike in the list; stated in the guide.

### Verification

- [ ] Fast tier; `E` with `DATABASE_BACKEND=postgresql`
- [ ] Full tier before the phase commit

### Implementation Status: Not Started

---

## Phase 3: Documentation

No acceptance criterion: this phase tells consumers what Phases 1 and 2
built. `docs/` and the changelog name no consumer.

### Changes

- `docs/guides/version-history.rst` (new, in `docs/guides/index.rst`):
  - turning it on; explicit snapshots, not an automatic audit; take, list,
    read, remove;
  - restoring: read a version and write it back with the item's own write,
    after a take when the current value is to be kept; what that write
    fires; that the two calls are not one transaction, and that a property
    or attribute write is not conditional, so a writer in between is
    overwritten; a put hook that transforms values runs again on stored
    content; a property's default take is the stored string, to be decoded
    first by an application that writes objects (what the hook and the
    subscribers get otherwise); an attribute comes back without its TTL;
  - the limit, its lazy lowering, the limit a take carries (pass it at
    every take of that kind) and the unlimited default's storage risk;
  - what one take costs: the store calls `S::test_take_cost_per_kind` pins,
    per kind, and one body row per 350,000 bytes of content over 4 KB;
  - a delete keeps history and `purge` erases; turned off means kept;
    rolling deploys;
  - list elements: choosing a key that is never reused and namespacing it;
    editing with history (take the value the handle read, write with
    `update_by_handle`, remove the version by its id when the write
    returns `False`, and what a duplicate costs at the limit); re-keying on
    a move, in an order that needs no record of a rename owed, and that a
    started rename is listed and finished by a repeat; passing what a
    restore needs, not derived fields; writing an element back; removing a
    deleted list's histories by prefix; what versioning a bulk delete
    costs per element;
  - keeping deleted items for a period: mark the take before a delete in
    its metadata, list keys with their newest version, `remove_all()` the
    ones past the period; the listing can lag a take whose marker write
    faulted, so call `all()` after a take that precedes a delete.
- `docs/guides/property-lists.rst`, `docs/sdk/actor-interface.rst`,
  `docs/sdk/attributes-buckets.rst`, `docs/reference/interface-api.rst`,
  `docs/reference/hooks-reference.rst`, `docs/reference/actor-deletion.rst`
  - the new names; a delete leaves history; versions go with the actor and
  the bucket; version calls fire no hook.
- `docs/quickstart/configuration.rst` - `with_versioning`.
- `docs/reference/database-backends.rst` - the `$ver` partition, the
  index, the start-up refusal; a custom backend needs no new method;
  line 180 corrected to 100 items and 4 MB per transaction.
- `docs/guides/database-maintenance.rst` - `actingweb-versions`,
  `verify-orphans` and `$ver`, `check-ready --versioning`, that table
  scans grow with history, and that a backup or copy of one actor includes
  the partitions `{id}$ver` and `{id}$aux`, with version rows written after
  the actor is created (a create with that id clears them).
- `docs/guides/postgresql-migration.rst` - the new revision.
- `docs/migration/v4.1.rst` (new) with its `docs/migration/index.rst` row -
  nothing to do unless opting in; on PostgreSQL `alembic upgrade head`
  builds the index for every deployment that runs it, and it must be there
  before versioning is turned on; turn it on only when every process runs 4.1;
  a custom backend needs no new method; after a downgrade, 4.0.x leaves versions behind and
  reports them as orphans, and `actingweb-versions purge` from 4.1 removes
  them.
- `CHANGELOG.rst` - `ADDED` under `Unreleased`, with a **Behavior change:**
  sentence for what applies without opting in: the actor and bucket deletes
  read the version partition, a create with a caller-supplied id clears
  version rows left under it, and `ActorInterface` gains `versions`.

### New Tests

- None; `tests/test_version_consistency.py` and the docs build cover it.

### Failure Scenarios

- A guide example drifts from the API - the examples are copied from the
  passing tests of Phases 1 and 2.

### Verification

- [ ] The Full tier's `sphinx-build -W` line
- [ ] Fast tier (docstrings)

### Implementation Status: Not Started

---

## Removed Phases

### Restore and destructive delete (was Phase 2; removed 2026-11-27)

**Why:** the consumer the feature names keeps memories, documents and
instructions as list elements
(`thoughts/research/2026-11-27-emm-review-of-version-history-plan.md`,
finding 1), where this plan already leaves the write-back to the
application. The phase gave the simpler kinds a guarantee the valuable
kind did not get, for the cost of two backend protocol methods, a
cross-table transaction on both backends and a start-up refusal for custom
backends. What it closed is the gap between a take and a write, which any
two property writes have. `delete_with_versions` moved to Phase 1. The
design below is kept for
`thoughts/todo/write-with-a-version-in-one-transaction.md`.

**Its criteria:** AC-23 to AC-28, AC-34, AC-54, AC-57, AC-67, and the
restore halves of AC-22, AC-60 and AC-72. **Its error:** `VersionConflict`.
**Its test files:** `tests/test_versions_restore.py`,
`tests/test_versions_restore_backend.py`.

```mermaid
sequenceDiagram
    participant A as Application
    participant V as ItemVersions.restore
    participant B as Backend
    A->>V: restore(ref, keep_current=True)
    V->>B: read version (head, bodies)
    V->>V: name guards, size check, put hook (property)
    V->>B: read current value
    alt no current value, or keep_current=False
        V->>B: ordinary write
    else current value exists
        V->>B: read newest id, write pre-restore bodies once
        V->>B: set_with_version_rows(value, expected=current, head + marker)
        B-->>V: True, or False (re-read current; three compares, then VersionConflict)
    end
    V->>V: update the store object's cache
    V->>A: register diff (property), trim except the restored id, return
```

#### Changes

- `actingweb/db/protocols.py` - the two methods, their docstrings (an
  attribute backend writes property rows here; a custom backend with two
  stores must make that atomic or not offer restore), and
  `VERSION_RESTORE_PRIMITIVES`.
- `actingweb/db/dynamodb/property.py` - one transaction: the value
  conditioned on `expected`, the lookup items of `_write_indexed`, then the
  version rows as unconditional puts placed last in the main, takeover and
  collision-fallback shapes, so the positional cancellation codes
  (`:460-464`) keep their meaning.
- `actingweb/db/dynamodb/attribute.py` - a consistent read, the JSON-value
  compare in Python, then one transaction pinned to the stored data as read
  (`:511-529`), with the version rows; `ensure_table(Property)`.
- `actingweb/db/postgresql/property.py`, `db/postgresql/attribute.py` - one
  connection: `SELECT … FOR UPDATE`, compare, write, lookup maintenance as
  `_set_indexed`, insert of the version rows; the deadlock retry of
  `_set_indexed`.
- `actingweb/versions.py` - `restore` as in the diagram. The pre-restore
  bodies are written once and reused across compares, and deleted when the
  call gives up or raises. A name a list has taken raises
  `ListNameTakenError` as a write does. A core-level `VersionStore` (no
  `ActorInterface`) restores without hooks or diff, as the core property
  store writes. `delete_with_versions`: the item's normal delete, then
  `remove_all`; a repeat after a fault finishes.
- `actingweb/interface/actor_interface.py` - passes `property_store=`, so
  a property restore runs `_execute_property_hook`, `_previous` and
  `_register_diff`.
- `actingweb/property.py`, `actingweb/attribute.py` - a way for restore to
  set the instance cache.
- `actingweb/interface/app.py`, `maintenance/check_ready.py` - the gate
  also probes the restore primitives on both backends' classes.

#### New Tests (written first)

- Every Phase 2 row of the Traceability table.
- `B` per backend: commit; lost compare (nothing written); indexed name;
  held value (the baseline of `tests/test_property_lookup_sync.py:124-181`);
  `::test_an_indexed_restore_takes_over_a_stale_lookup_row`;
  `::test_an_indexed_restore_of_the_current_value_heals_the_lookup_row`;
  `::test_a_past_collision_is_retried_without_the_delete`;
  `::test_the_dynamodb_property_restore_is_one_transaction`;
  `::test_the_dynamodb_attribute_restore_is_one_read_and_one_transaction`;
  `::test_the_postgresql_restore_takes_one_connection`;
  `::test_a_deadlock_is_retried_inside_the_call`;
  `::test_an_expired_attribute_answers_false`.
- `tests/test_db_protocols.py::test_the_restore_primitives_have_the_protocol_signature`.
- `R::test_a_lost_compare_retries_then_raises_version_conflict`;
  `R::test_the_pre_restore_bodies_are_written_once`;
  `R::test_bodies_of_a_failed_pre_restore_version_are_removed`.
- `R::test_a_diff_fault_after_restore_is_db_error_after_write`.
- `R::test_restore_onto_a_name_a_list_took_raises_list_name_taken`.
- `R::test_restore_of_a_default_take_registers_the_stored_string`.
- `R::test_an_attribute_restore_writes_no_ttl`.
- `R::test_restore_reads_current_from_the_store_not_the_instance`.
- `R::test_restore_without_check_ready_on_a_bare_backend_raises_versioning_not_ready`.
- `R::test_delete_with_versions_finishes_after_a_fault`.

#### Failure Scenarios

- A write between the read and the restore - the compare fails; re-read;
  `VersionConflict` after three - tested.
- Fault inside the transaction - nothing written - `B`.
- Fault after commit, before the diff - `DbErrorAfterWrite`, as a write -
  tested.
- A write racing the restore of a deleted item - last writer wins, as for
  two writes; stated in the guide.
- A put hook that transforms values runs again on stored content - stated
  in the guide; a hook must be idempotent to be restored through.

#### Backend additions

Probed as `VERSION_RESTORE_PRIMITIVES`:

```python
# DbPropertyProtocol
def set_with_version_rows(self, actor_id: str, name: str, value: str, *, expected: str,
                          version_partition: str, version_rows: dict[str, str]) -> bool
# DbAttributeProtocol; writes rows of the properties table in the same transaction
def set_attr_with_version_rows(self, actor_id: str, bucket: str, name: str, data: Any, *, expected: Any,
                               version_partition: str, version_rows: dict[str, str]) -> bool
```

`version_rows` is the head and the marker. True: value and rows were
written together. False: the current value is not `expected` (attributes:
by JSON value, SFT-8) or the row is absent or expired. A fault raises
`DbError`; a deadlock or serialization failure is retried inside the call.

---

## Evaluation Notes

**Outside voice:** codex (`codex exec -s read-only`, outside the sandbox) and a fresh-context Claude reviewer.

Pass 2 findings (rows 1 to 62, deduplicated), Pass 3 findings (63 to 77), and a second outside-voice pass over the design written after them (78 to 92).

| # | From | Finding (`file:line` quoted) | Disposition |
| --- | --- | --- | --- |
| 1 | Scalability, Architecture, Tests, Security | `db/protocols.py:500` "**no capacity saving on DynamoDB**, where a projection still pays for the whole item"; `db/dynamodb/property.py:697` `results[str(item.name)] = "" if keys_only else str(item.value or "")` — listing needs head values (metadata, bytes), and heads with inline content up to the span threshold make list, trim, `get(-x)` and purge pay for content. | Folded: content over 4 KB goes to body rows (Interfaces, Phase 1) |
| 2 | Scalability | `db/postgresql/schema.py:73` `__table_args__ = (PrimaryKeyConstraint("id", "name"),)`; `db/postgresql/property.py:639` `WHERE id = %s AND starts_with(name, %s)` — no index serves a prefix on `properties.name`; each per-item version read walks the actor's whole `$ver` partition. | User decided: index in Phase 1, required only with versioning on (AC-66) |
| 3 | Scalability | plan `version_names() -> list[str]` over `get_prefix` (`db/protocols.py:448`, no limit, no cursor) — reads every version row to list names. | Folded: one marker row per item |
| 4 | Scalability, Architecture | `actingweb/property.py:495` `names = list(db.get_prefix(actor_id=aux, prefix="list:", keys_only=True))`; `constants.py:264` `DELETION_LEASE = 120  # seconds` — a read-everything-then-delete purge makes no progress when interrupted; placement relative to `actor.py:1684` `step()` and `:1712`. | Folded: purge item by item, `step()` around it, repeated before the actor row |
| 5 | Scalability | `property_list_span.py:45-49` headroom sized for list rows; `db/dynamodb/property.py:98` `MAX_ROW_BYTES: int | None = 409_600` — a head with 390 KB inline JSON-in-JSON plus metadata and names can exceed the row cap. | Folded with 1 |
| 6 | Scalability | plan "one keys-only read after the write and deletes the surplus" — the trim needs each surplus head's `parts`; reaping orphan bodies at every trim reads body bytes. | Folded: trim point-reads surplus heads; orphan bodies go with `remove_all` and the purges |
| 7 | Scalability | `list_core.py:2613` `return self._keyed_by_hash(self._v2_load_full()).get(key_hash, [])` — `move_to` and a guarded mint can read a whole list. | Moot: `history_key` and `move_to` deferred |
| 8 | Scalability, Architecture | `maintenance/property_lookup.py:568` `results = Property.scan(`; `maintenance/verify_orphans.py:255` `for item in Property.scan(` — table scans grow with history. | Folded: Phase 4 maintenance guide |
| 9 | Scalability | plan rows under `ver/` and `vb/` — two prefix reads on every bucket and actor delete. | Folded: one prefix per scope |
| 10 | Scalability | `db/dynamodb/actor.py:804` `TRANSACT_ATTEMPTS = 3`; plan "retry up to 3" — retries stack and each lost compare rewrites bodies. | Folded: one budget of three compares, bodies written once |
| 11 | Scalability | `db/postgresql/property.py:343-348` `except (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure)` — the restore call must reuse this retry. | Folded: Phase 2 |
| 12 | Usability, Architecture, Tests | `list_core.py:3803` `expected=handle.raw_value,` — minting rewrites the head; the caller's handle goes stale and `history_key` returns only a string. | User decided: minted keys deferred; re-key call (AC-63) |
| 13 | Usability | research:402-403 "An existing element cannot be given one, and delete plus insert loses it." — a deleted element written back cannot rejoin its history. | User decided: as 12 |
| 14 | Usability | `actingweb_mcp repositories/local_memory_repository.py:475-477` `moved_item["id"] = new_id`; `output_repository.py:1510-1511` `new_item["category"] = target_category` — both consumer moves change the value; `move_to` cannot carry one. | User decided: as 12 |
| 15 | Usability | research:466 memory identity is a "per-type integer counter ... reassigned on a move" — own ids do not work as keys for memories; the minted path must work end to end. | User decided: as 12 |
| 16 | Usability | `actingweb_mcp repositories/audit_log_repository.py:206,248` `summaries()` returns `{"count": len(items), "last_changed": last}` — the planned key listing gives no summary, so an overview is one read per key. | Folded: listings return each item's newest version (AC-69) |
| 17 | Usability, Architecture, Tests, Security | `interface/property_store.py:173` `def __getattr__`; `:738` `PropertyListStore.__getattr__` — new method names shadow a property or list of that name. | Folded: one `actor.versions` namespace, no new name on a store |
| 18 | Usability | `pyrightconfig.json:46` `"reportIncompatibleMethodOverride": "warning"` — `Versions.take` overrides `ElementVersions.take` incompatibly; a method named `list`. | Folded: sibling classes, `all()` |
| 19 | Usability, Architecture, Tests | `property.py:326` `self.__dict__[k] = v`; `attribute.py:403` `if name not in self.data:` — restore bypasses the instance caches. | Folded: AC-67 |
| 20 | Architecture, Usability, Tests | `attribute.py:452` `# {} / [] / "" / 0 / False all delete on the backend too.`; `db/dynamodb/property.py:248` `if not value or ...` — restoring falsy content is a delete. | Folded: AC-68 |
| 21 | Usability | plan `take(content, *, metadata, position)` with an actor-wide key — a position without a list name. | Folded: `list_name` recorded beside `position` |
| 22 | Usability | `actingweb_mcp repositories/output_repository.py:1658` `def delete_type` — deleting a list leaves every element history, with no bulk removal. | Folded: removal by key prefix (AC-70) |
| 23 | Usability | feature:262 "Storage per account with history on | known and bounded by the limit" against plan "no per-actor total". | Folded: `actingweb-versions report` (AC-65) |
| 24 | Usability, Architecture | `interface/app.py:31` `class StoreNotReady(RuntimeError):` — error bases, attributes and layering unspecified; `ListKeyExists` naming. | Folded: Interfaces, Errors |
| 25 | Usability, Tests | plan `get(self, ref: str | int)` — `0`, positive ints, `bool`, the return of `restore`, unknown id on `remove` unspecified. | Folded: AC-18, AC-56 and their tests |
| 26 | Usability | `interface/app.py:425,654,753` builders with `enable: bool` — `with_versioning` shape. | Rejected: calling `with_versioning()` is the opt-in; the `_UNSET` wording is gone |
| 27 | Usability | `actingweb/__init__.py:35-37` "NOT the recommended API" — attribute versions hang off the legacy `Attributes`; no interface accessor. | Folded with 17 |
| 28 | Usability, Tests | `db/dynamodb/property.py:127` `get(...) -> str | None` — a default take holds the stored string, an explicit take any JSON value; the put hook runs again on stored content. | Folded: guide note and `R::test_restore_of_a_default_take_registers_the_stored_string` |
| 29 | Usability, Architecture, Tests | `config.py:247` "one without (PostgreSQL) never spans and sets no"; `db/postgresql/property.py:61` `MAX_ROW_BYTES: int | None = None` — AC-49 and AC-60 have no ceiling on PostgreSQL. | Folded: versions have their own threshold and ceiling on both backends |
| 30 | Usability | research:615-640 names `docs/sdk/actor-interface.rst`, `docs/sdk/attributes-buckets.rst`, `docs/reference/hooks-reference.rst`; changelog needs **Behavior change:** sentences for what applies without opting in. | Folded: Phase 4 |
| 31 | Security | `oauth2_server/token_manager.py:67` `self.tokens_bucket = "mcp_tokens"`; `oauth_session.py:39` `_ACCESS_TOKEN_BUCKET = "spa_access_tokens"` — the bucket rule misses the token buckets. | Folded: AC-40, `LIBRARY_BUCKETS` |
| 32 | Security | `handlers/properties.py:2740` `actor_interface.properties.clear()`; `oauth2.py:3087` adoption clean; `attribute.py:429` `ttl_seconds` — a delete keeps history, no erase path with versioning off, adoption keeps the earlier creator's history, a TTL value outlives its expiry. | User decided: purge call, purge on adoption, operator command (AC-64, AC-65, AC-71); an expired attribute is absent |
| 33 | Security, Tests | `interface/property_store.py:80` `return result if result is not None else value` — a Python write has no hook rejection; the planned test has no baseline. | Folded: restore mirrors the write |
| 34 | Security, Tests | `property.py:286` `if k.startswith("list:"):`; `:320-321` `raise ListNameTakenError(` — restore and take skip the core name guards. | Folded: Phase 1 and 2 name guards |
| 35 | Security, Architecture | `property.py:498-500` "a consumer could have created "{id}$aux" before then"; `property_list_span.py:512` `if "$" in actor_id:` — the pre-4.0 `{id}$ver` actor is guarded on delete only. | Folded: `ver_partition()` |
| 36 | Security, Tests | plan "a part over 240 bytes is `~` plus its SHA-256 hex" — a literal `~` name can equal a hashed one; version ids unvalidated. | Folded: `~` escaped, ids validated |
| 37 | Security, Architecture | `attribute.py:814` `self.list.delete(actor_id=self.actor_id)`; `handlers/devtest.py:96` `buckets.delete()` — bypasses the bucket purge. | Folded: `Buckets.delete()` purges |
| 38 | Security, Architecture | `maintenance/deletions.py:198-204` "The row is gone; what can remain is the client index rows"; `actor.py:1090` caller-supplied ids — leftover `$ver` rows attach to a re-created id. | Folded: unfinished-deletion resume and create with a supplied id purge |
| 39 | Security | `oauth2_server/state_manager.py:255` `sys_actor.property.oauth2_state_encryption_key = key_str` — system actors are versionable. | Folded: AC-40 |
| 40 | Security | plan `max_versions: int | None = None` — unbounded by default; metadata depth. | Rejected for the default (owner: no limit unless set, AC-6); the guide states the risk |
| 41 | Architecture, Tests | `list_core.py:3817` "The envelope's key, token and unknown fields are carried into the new head"; `interface/property_store.py:528` `if result.announced:` — a repeated move can delete a newer source and never announces the insert. | Moot: deferred |
| 42 | Architecture | `list_core.py:2804`, `:4137` `if report["duplicate_keyed_items"]:` — `move_to` into the same list. | Moot: deferred |
| 43 | Architecture | `db/dynamodb/property.py:460` `if len(codes) > offset and codes[offset] == "ConditionalCheckFailed":` — cancellation codes are read by position; the head put must come last in all three transaction shapes. | Folded: head put last in every transaction shape |
| 44 | Architecture | `db/dynamodb/attribute.py:1071-1072` `ensure_table(Attribute)` — the attribute restore call writes a property row: two contracts coupled. | Folded: protocol docstring, backend docs, `ensure_table(Property)` |
| 45 | Architecture | `attribute.py:751` `side_fault = e`, `:754` `raise side_fault` — bucket purge fault order. | Folded: a purge fault raises before the bucket's rows go |
| 46 | Architecture, Security | `interface/actor_interface.py:364` replicas live in `remote:{peer_id}` — `history_key` and `move_to` not refused on replica or library buckets. | Moot: deferred |
| 47 | Architecture | `list_core.py:1044` `span = self._write_bodies(value_str) if spans else None` — minting on a spanned element rewrites its bodies. | Moot: deferred |
| 48 | Architecture | `list_core.py:2828` "The key is never stored or logged" — an application-passed element key is stored in plain text. | Folded: guide; keys validated as `append_once` keys are |
| 49 | Tests | `tests/_attribute_parity.py:36` `return property_list.get_property(config)`; `:51` `raise AssertionError(f"unexpected bucket {bucket!r}")` — `L` under `list_class` runs on a fake and one bucket; no backend coverage. | Folded: element tests run on the real backends (`E`) |
| 50 | Tests | `tests/_adoption_helpers.py:107` `unpatched = get_attribute(config)`; `:162` `with patch.object(target, "get_connection", down)` — no helper faults a chosen property row or a statement inside a transaction. | Folded: `property_fault` and the transaction fault tests |
| 51 | Tests | plan AC-24 against "register diff (property only), trim" — restoring the oldest at the limit trims the restored version. | Folded: AC-72 |
| 52 | Tests | `tests/_read_counters.py:14-15` "A test that asserts a zero should also assert a non-zero elsewhere"; `maintenance/verify_orphans.py:222` `elif owner not in actor_ids:` — AC-1, 2, 9, 10-15, 43, 58 tests cannot fail as named. | Folded: positive controls in each named test |
| 53 | Tests | `tests/_read_counters.py:49` `counts[operation_name] += 1` — counters cannot see the partition a read named. | Folded: `record_partitions` |
| 54 | Tests | `tests/integration/test_harness.py:90` builder chain; `verify_groups.py:358` — `H` has no way to turn versioning on. | Folded: harness argument |
| 55 | Tests | `tests/test_authenticated_views.py:494`, `:581`; `tests/test_v2_value_addressed_reads.py:243`; `tests/test_init_docstring.py:18` `assert actingweb.__all__ == [`; `tests/test_list_core_fault_suite.py:1-3` — surface pins and the fault suite are not where the plan says. | Folded: `tests/test_init_docstring.py`; list surface pins no longer touched |
| 56 | Tests | plan "`move_to` registers the insert diff on the target and the delete diff on the source" — no test on the notifying wrapper. | Moot: deferred |
| 57 | Tests | `db/dynamodb/property.py:475` `taken = take_over(`; `:315` `if old_value == value:` — takeover and heal branches of an indexed restore untested. | Folded: Phase 2 tests |
| 58 | Tests | plan AC-28 "if and only if the value changed" — equal value and the race on a deleted item undefined. | Folded: AC-28 reworded; the race is last-writer-wins and stated |
| 59 | Tests | plan `Versions.restore` in the Phase 1 interface — phase independence; whether `history_key`/`move_to` are refused when off. | Folded: Phase 1 ships without `restore` |
| 60 | Tests | plan `<id> = {unix_ms:013d}-{16 hex}` — order inside one millisecond is random. | Folded: every id is minted above the newest stored one |
| 61 | Tests | `property_list_span.py:471` `def new_gen()`; `list_core.py:1136-1141` span join with digest; `list_core.py:126` `_APPEND_ONCE_KEY_MAX_LEN = 512` — duplication. | Folded: `new_gen`, one span join helper, `_validate_append_key` |
| 62 | Tests | `tests/test_check_ready_command.py:67` `mock.patch.multiple(P, create=True, **mocks)`; `tests/test_db_protocols.py:201` — gate and signature pins. | Folded: Phase 2 tests |
| 63 | Outside voice (codex) | plan Phase 3 "`history_key`: … written to the head's envelope by compare-and-swap" — the list work carries most of the release's risk; split it out. | User decided: deferred; this plan ships element history by key with a re-key call |
| 64 | Outside voice (codex) | `property.py:480` "Actor deletion assumes the actor is quiescent."; `actor.py:1651` "The actor row is removed **last**" — a take during the wipe outlives the actor. | Folded: purge repeated directly before the actor row; the residual window is stated, with the operator purge |
| 65 | Outside voice (codex) | plan "a fault in the trim is logged and not raised" against AC-7 — a failed trim is reported as success. | Folded in part: every take trims all surplus, so the next take restores the bound; not raised, since the version is stored |
| 66 | Outside voice (codex) | plan "removed by `remove_all`, by the item's next trim" with `max_versions=None` — orphan bodies have no reaper. | Folded: reaped by `remove_all` and the purges; `actingweb-versions report` counts them |
| 67 | Outside voice (codex) | `db/dynamodb/attribute.py:912` "DynamoDB deletes expired items automatically"; `db/postgresql/attribute.py:361` "only reclaimed by an explicit `delete_expired()` sweep" — an expired attribute gives backend-dependent history. | Folded: an expired row is absent on both backends |
| 68 | Outside voice (codex) | plan "app-wide `max_versions`" — hosts with different limits during a rolling deploy. | Folded: guide |
| 69 | Outside voice (fresh context) | `pyproject.toml:3` `version = "4.0.0rc4"` — nothing gates this on the 4.0.0 tag. | Folded: precondition in the header |
| 70 | Outside voice (fresh context) | `thoughts/todo/bounded-list-read.md:12-14` "The `properties` table has no `COLLATE "C"` index on `name`" — two todos overlap. | Folded: the index lands here and the todo is updated; the delete race and list versioning rows of `list-items-conditional-create-ttl-and-retained-bodies.md` stay open |
| 71 | Outside voice (fresh context) | `maintenance/verify_orphans.py:22` "Report only. There is no `--delete` flag" — nothing ever reaps a `$ver` row. | Folded: `actingweb-versions purge`; downgrade note reworded |
| 72 | Outside voice (fresh context) | research:186-189 "`DbAttributeBucketList.fetch` queries the whole actor partition and groups by bucket" — a bucket holding only versions cannot be discovered. | Folded: `actor.versions.buckets()` (AC-69) |
| 73 | Outside voice (fresh context) | plan "after a downgrade, deleting an actor leaves its versions" — also true in a mixed fleet. | Folded: migration guide |
| 74 | Outside voice (fresh context) | `attribute.py:403-405` `if name not in self.data:` / `if self._bucket_loaded:` / `return None` — "current" from a cache that claims absence. | Folded: take and restore read current from the backend |
| 75 | Outside voice (fresh context) | plan "A restore mints its pre-restore id above the newest stored one" — a just-taken version can be the one its own trim deletes. | Folded: AC-72 and 60 |
| 76 | Outside voice (fresh context) | plan "the head deleted before its bodies" — a read racing a removal can join short content. | Folded: the join checks length and digest; `VersionNotFound` |
| 77 | Outside voice (fresh context) | `db/dynamodb/attribute.py:511` `if not json_values_equal(item.data, wanted):` — the DynamoDB attribute restore is a read plus a pinned transaction. | Folded: Phase 2 contract |
| 78 | Delta review (codex, fresh context) | plan Phase 1 "write bodies, then the head, then the marker"; "`remove_all` deletes the marker last"; `db/protocols.py:519` `create_if_not_exists`, `:544` `delete_if_value_equals` — the marker was a second source of truth written by plain `set`: heads without a marker, a marker naming an older or removed version. | Folded: marker kept by conditional writes only, repaired on read (Interfaces, AC-74) |
| 79 | Delta review (fresh context) | plan AC-9 "no version is listed" against the head-then-marker order. | Folded: AC-9 reworded; a marker fault after the head is not raised |
| 80 | Delta review (codex) | `db/protocols.py:459-463` "a prefix has no exact inclusive upper bound" — range bounds over arbitrary Unicode. | Folded: delimiter and code-point bounds with a `startswith` filter (Interfaces) |
| 81 | Delta review (fresh context) | plan "filed under its SHA-256" against AC-70 "whose key starts with it" — prefix reads miss digest-filed names. | Folded: the `~` range is read and filtered on the full name |
| 82 | Delta review (codex, fresh context) | plan Phase 3 "A take under the old key during a rename is refused" — not atomic with a take; an unrepeated rename blocks the key unseen; a used target contradicted "the result is the union". | Folded: final re-read, `VersionRenamePending`, pending key listed, scenario corrected |
| 83 | Delta review (fresh context) | `actor.py:1712` `buckets.delete()` and `:1716` are consecutive — the "second purge" closed no window. | Folded: one purge, directly before the actor row |
| 84 | Delta review (codex, fresh context) | `actor.py:1217-1285` work after the row is live; `:1223-1247` a failed tombstone clear fails the create — the create-time purge could remove live versions and had no fault rule or AC. | Folded: purge before the row is written, a fault fails the create (AC-73) |
| 85 | Delta review (codex) | `maintenance/deletions.py:203-244` — placement of the resume purge. | Folded: after the row is confirmed absent, before `mark_finished` |
| 86 | Delta review (codex, fresh context) | `thoughts/specs/operator-commands.md:18-22,103-107` — no test held `actingweb-versions` to OPC-1, OPC-2, OPC-D2; one actor per run; a live actor unannounced. | Folded: store-first and no-prefix cases, `--ids-file`, `--live` |
| 87 | Delta review (codex, fresh context) | `db/postgresql/property.py:561-575,787-791`; `db/postgresql/attribute.py:63-69` INVALID index — one `EXPLAIN` shape; INVALID unpinned; the index is not partial. | Folded: each read shape, an INVALID case, the migration guide says who builds it |
| 88 | Delta review (codex) | plan Phase 2 "passes the property store" — how a `VersionStore` gets it. | Folded: `property_store=` in Interfaces |
| 89 | Delta review (fresh context) | `tests/_read_counters.py:47-49` counts every call — the take read budget against the two guards. | Folded: per-kind budget; the live-actor check runs once per store |
| 90 | Delta review (fresh context) | `remote_storage.py:439` `db.delete_bucket()` — replica bucket deletes paid a version read. | Folded: skipped without a read |
| 91 | Delta review (fresh context) | plan AC-1 row against "Phase 1: the PostgreSQL index"; OPC-9 cited AC-54 only. | Folded |
| 92 | Delta review (codex) | "content body, 350,000 bytes each" against `MAX_ROW_BYTES` 409,600. | Rejected: `db/dynamodb/property.py:240-243` stores a string unchanged; the large-version test pins it |
| 93 | Consumer review (2026-11-27) | `actingweb_mcp repositories/instruction_repository.py:75` "Document-style CRUD over instruction_* and template_* property lists." — all three item kinds of the named consumer are list elements; the restore phase has no caller. | User decided: phase removed, one write-back story (AC-76) |
| 94 | Consumer review (2026-11-27) | `list_core.py:3801-3803` `self._storage.set_if_value_equals,` … `expected=handle.raw_value,` — the report's lost version in a two-call element edit does not occur: a writer in between fails the swap. What is left is a duplicate version, which at the limit has trimmed an older one. | Folded: guide pattern; the one-transaction write is a todo |
| 95 | Consumer review (2026-11-27) | `actingweb_mcp helpers/output_limits.py:9` `MAX_STORED_BYTES = 380_000` against memories under 2 KB — one app-wide count fits one kind. | User decided: a limit a take carries (AC-75); `max_bytes` is a ceiling and needs none |
| 96 | Consumer review, triage (2026-11-27) | plan Phase 1 "A fault after the head is logged, not raised" with Interfaces "A marker with no newest version is not listed" — a sweep of deleted items by the key listing misses a take whose marker write faulted; a deleted item never takes again. | Folded: guide (`all()` after a take that precedes a delete) |
| 97 | Consumer review, triage (2026-11-27) | `db/dynamodb/property.py:910` `for d in Property.query(actor_id):` — a per-actor export reads the actor's own partition; `{id}$ver` and `{id}$aux` are missed, and AC-73 clears `$ver` at a create with that id. | Folded: maintenance guide; export and import is a todo |
| 98 | Consumer review (2026-11-27) | plan Phase 1 take sequence (marker, newest id, head, marker, trim read) — a bulk delete of 500 elements that versions each is about 2,500 store calls. | Folded: guide states the cost; a batch take is a todo |
| 99 | Consumer review (2026-11-27) | Interfaces `.list_elements(prefix="")` — a limit and cursor on the key listing, for "the newest N". | Rejected: markers are keyed by name, so the newest N reads every marker with or without a cursor; a prefix narrows the read |

Rows 10, 11, 19, 33, 43, 44, 57, 58, 62, 75 and 77 were folded into
the restore phase and went with it (Removed Phases). Row 20's falsy-content rule (narrowed by row 102), row 28's stored string
(row 101) and row 34's name guards stay for the take.

| # | From | Finding (`file:line` quoted) | Disposition |
| --- | --- | --- | --- |
| 100 | Update review (codex, fresh context) | plan AC-76 "makes the current value what it was at the take"; `db/dynamodb/property.py:239` `value = json.dumps(sanitized_value)`; `interface/property_store.py:139` `transformed = self._execute_property_hook(key, "put", value, [key])` — not true for a passed non-string value or under a transforming hook. | Folded: AC-76 scoped to a default take with no transforming hook |
| 101 | Update review (fresh context) | `interface/property_store.py:111` `blob = json.dumps(value if value is not None else "")` — a written-back default take sends subscribers a JSON string where the original write sent an object; row 28's test went with the restore phase. | Folded: decision, guide line, `S::test_a_written_back_default_take_registers_the_stored_string` |
| 102 | Update review (fresh context) | `db/dynamodb/property.py:235-248` `json.dumps` runs before `if not value` — `0`, `False`, `[]`, `{}` are stored for a property; the plan refused them. | Folded: AC-68 and the decision narrowed for properties (a correction of row 20) |
| 103 | Update review (codex, fresh context) | `interface/property_store.py:149-153` `__delitem__` registers a diff with no existence check; plan `delete_with_versions` named no attribute call. | Folded: delete only a current value; the attribute call and its cache rule named |
| 104 | Update review (fresh context) | plan AC-52 "exactly the limit after it" against a take that carries its own limit; "`None` means the app-wide value" against "higher or lower". | Folded: AC-52 reworded; no per-take "unlimited" |

**Unverified notes** (concerns that could not cite a line):
- PostgreSQL may use the primary key for `starts_with` only under C collation; no `EXPLAIN` was run.
- All of an actor's versions share one DynamoDB partition key; large takes and purges may throttle.
- PostgreSQL's planner may prefer the primary key on a small table; the index tests use PREPARE/EXECUTE.
- Whether a purge of a very large history inside one `step()` can outlast the 120-second deletion lease was not measured.
- `DbProperty.set` sanitises strings (`db/dynamodb/property.py:245`); a head holding a lone surrogate was not traced. `S::test_content_with_a_lone_surrogate_reads_back_as_a_write_stores_it` pins it.
- `delete_with_versions` racing a `take` that already read the value can leave that value in a new version.
- A default take of an attribute whose stored data is falsy (`attribute.py:394-396` suggests a null row can exist): treated as absent, not traced.
- Whether two concurrent takes that each carry `max_versions=1` can each spare their own version and leave two was not traced; `S::test_concurrent_takes_at_the_limit_end_at_the_limit` covers the app-wide case.
- What one version of several megabytes costs in DynamoDB write capacity, and whether a burst of takes on one actor throttles on the shared `$ver` partition key, were not measured (consumer review, 2026-11-27).
