# A public compare-and-delete on `Attributes`, comparing dicts by value

**Filed:** 2026-11-25, from a consumer's inbound report (Emm AI,
`actingweb_mcp`, the same day). The report came out of its verification of
its ActingWeb 4.0 improvements plan (the Low finding "the sweep's live
decision and its delete race") and items 1 and 4 of its sharing todo. The
consumer asked for this **before 4.0.0 is cut**: added afterwards, it would
be a new public method, which means a minor release. This file also
replaces the earlier todo `attribute-conditional-delete-on-dict-values.md`
(filed 2026-11-19 from the consumer's A10), which asked for the dict test
this triage has now run.

## What the consumer needs

From the public `Attributes` class, a way to delete an attribute only when it
still holds the value the caller read:
- **True** when this call deleted it
- **False** when the row holds something else, or is gone
- **`DbError`** on a store fault, never False

It closes three races in the consumer:
- the "live" branch of its deletion-cleanup sweep, which can lose a new
  deletion's record
- a reader's decline that loses their own accept, made from another tab
- a decline that loses a "Share again" listing written at the same moment

The races were not checked in the consumer's code. The library side was.

## What the triage verified (4.0.0rc3, `a74ae35`)

**`Attributes` has no such method.** It has:
- `delete_attr`, unconditional
- `delete_attr_conditional`, which deletes when the row exists and compares
  nothing (`attribute.py:643-678`)
- `conditional_update_attr(old_data=…, strict=True)` (`attribute.py:495-600`)

**Both backends already implement it as `delete_attr_if_data_equals`.**
- The protocol lists it (`db/protocols.py:1689-1693`) with `expected: str`.
- It already has the 4.0 fault contract: a failed condition is False, and
  anything else raises `DbError`.
- The library's own callers pass strings:
  - `attribute_list.py:283`, which stores string values
  - `maintenance/email_as_creator.py:335`, whose value is an email string

**PostgreSQL compares by value.**
- `DELETE … AND data = %s::jsonb` (`db/postgresql/attribute.py:979-999`).
- Tested against PostgreSQL in the test container: a dict with its keys in
  another order deleted the row, and `1.0` matched a stored `1`.

**DynamoDB compares the stored text, so key order matters.**
- The row's `data` is a `JSONAttribute` (`db/dynamodb/attribute.py:80`),
  stored as `json.dumps` of what the writer passed, in the writer's key order
  (`set_attr`, `265-298`).
- The condition `Attribute.data == expected` (`691-711`) serialises
  `expected` the same way and compares the two texts.
- Tested on DynamoDB Local, with a row written as `{"x": 1, "y": 2}`:
  - `{"x": 1, "y": 2}` as a dict: True (deleted)
  - `{"y": 2, "x": 1}` as a dict: **False, row kept**
  - the same JSON passed as a string: False. The string is serialised as a
    JSON string, not as an object.
- `set_attr_if_data_equals` (`666-689`) uses the same condition, so it has
  the same defect.
- The library's own callers aren't affected, because they store and compare
  strings.

**`conditional_update_attr` already does it correctly on DynamoDB.**
- It reads the row with a consistent read and compares `normalize_json` of
  both sides.
- It then writes with the stored value as the condition
  (`db/dynamodb/attribute.py:341-440`).
- The compare-and-delete can use the same shape.

## The change

1. **Fix the DynamoDB backend.** `delete_attr_if_data_equals` and
   `set_attr_if_data_equals` compare by value, the way
   `conditional_update_attr` does:
   - a consistent read
   - a `normalize_json` compare, where a mismatch or a missing row is False
   - then the conditional write, conditioned on the stored data

   Strings keep comparing as they do now.
2. **Widen the protocol annotation** from `expected: str` to `Any`. It is an
   annotation only, so custom backends keep working. A line in
   `docs/reference/database-backends.rst` says the compare is by JSON value.
3. **Add a public method:**
   `Attributes.delete_attr_if_data_equals(name, expected) -> bool`, with the
   strict contract above. On success it removes `self.data[name]`, as
   `delete_attr_conditional` does. On a fault it unloads the cached entry, as
   `delete_attr` does.
4. **Tests on both backends:**
   - a dict with its keys in another order
   - a nested dict
   - a string value
   - an absent row
   - a row holding another value
   - a fault, which raises `DbError`
5. **Docs:** the attribute API reference, and a changelog entry under
   `ADDED`. It sits with 4.0's strict-semantics section in the migration
   guide.

## Release

About 100–150 library lines plus tests. The method is additive and the fix
changes no wire behaviour. Inside 4.0.0 it costs nothing in version terms;
after 4.0.0 the new method needs 4.1.

**In 4.0.0, through an rc4** (owner, 2026-11-25). The work goes on a
`fix/4.0.0-…` branch with its own PR, and 4.0.0rc4 follows, so the consumer
can confirm the three races are closed before final.
