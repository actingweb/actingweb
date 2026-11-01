# The attribute layer has no create-if-absent write

**Filed:** 2026-11-01, from the consumer's
`../actingweb_mcp/thoughts/todo/instructions-unlock-window-consent-gaps.md`
("Making the first ask atomic needs a create-if-absent attribute write,
which ActingWeb lacks ... a library request"). Verified against `99b2885`.

## What happens

`DbAttributeProtocol` (`actingweb/db/protocols.py`) has a compare-and-swap
(`conditional_update_attr`) and a conditional delete
(`delete_attr_conditional`), and nothing that creates a row only when none
exists. `conditional_update_attr` is documented as never an upsert ("a row
that is gone stays gone"), and both backends implement it as read, compare,
then a conditional write on the stored value, so there is no `old_data`
that means *absent*. A caller that wants "the first writer wins, every later
writer learns it lost" has only read-then-`set_attr`, which two callers
within a few milliseconds both pass. The property layer has exactly this
primitive, `DbPropertyProtocol.create_if_not_exists` (`protocols.py`),
which the v2 list rank-key inserts and `_v2_create_meta_row()` rely on;
the attribute layer never got one.

The consumer's case: two MCP clients asking for an instructions-unlock
window at once both store an ask (the later wins the slot, both raise a
banner). The ask's row is deleted when answered, so a create-if-absent on
it is the whole fix there.

## What a fix is

A `create_attr_if_absent(actor_id, bucket, name, data, timestamp=None,
ttl_seconds=None) -> bool` on the protocol, both backends and
`attribute.Attributes`: `True` when this call created the row, `False` when
a row already exists (a normal outcome), `DbError` on a fault (the 3.16
contract; note that `conditional_update_attr` and `delete_attr_conditional`
still answer `False` on a fault, which
`unique-creator-small-followups.md` records for the restore's log). DynamoDB:
a `save` with `attribute_not_exists(id)`-style condition, as
`create_if_not_exists` does in `db/dynamodb/property.py`. PostgreSQL:
`INSERT ... ON CONFLICT (id, bucket_name) DO NOTHING` and `rowcount`, as
`db/postgresql/property.py` does. The local-cache update in `Attributes`
follows `conditional_update_attr`'s.

Small (hours plus tests on both backends), but it adds a protocol method a
custom backend must implement, so it rides a minor with a **Breaking:**
"custom database backends" entry, like 3.16's `increment_seq` and
`DbActor(unique_creator=...)`. Decide whether to fold the fault behaviour
of the two existing conditional methods into the same change (raise on a
fault, keep `False` for a lost condition), which is a behaviour change for
callers that read `False` as "lost", or leave them.

## Why not urgent

The consumer's window is milliseconds wide and the loser only raises a
duplicate banner. Nothing in the library needs the primitive today.
