# Extend `actingweb-verify-orphans` to subscriptions, diffs and suspensions

**Origin:** `thoughts/plans/2026-11-06-subs-list-cache-lifetime.md` (the
redraft of 2026-11-12, "What We're NOT Doing", "Finding rows the deletion
race leaves"; found by the outside voice on that redraft). Still open after
its implementation: `thoughts/verifications/2026-11-12-subs-list-cache-lifetime.md`
(Issue 3 is the related `actingweb-deletions` resume path).

`actingweb-verify-orphans` sweeps property, attribute and trust rows across
the whole table for rows whose actor no longer exists
(`actingweb/maintenance/verify_orphans.py:3`). It does not look at
subscriptions, subscription diffs or subscription suspensions.

The actor row is removed last in a deletion, and nothing on the
subscription-create path reads the deletion tombstone, so a request already
past authentication can insert a subscription, and a diff for it, after the
last wipe. The `subs-list-cache-lifetime` plan narrows that window (a final
subscription wipe, an actor-wide diff delete, the suspension rows cleared)
but does not close it. A row left that way is reported by nothing.

**What doing it buys:** an operator can find, and remove, subscription,
diff and suspension rows that belong to no actor, on both backends; today
they are invisible. A leftover suspension is the one with an effect (an id
created again starts mute), and that case is closed at create by the plan;
the others are dead rows.

**What it needs:**

- The three tables added to the sweep on DynamoDB and PostgreSQL, with the
  same report-then-`--apply` shape the command has for the other tables.
- A decision on whether a subscription row whose actor exists but whose
  trust does not counts as an orphan (the sibling leaves those on a read
  fault, by design).
- Docs: the command's reference page.
