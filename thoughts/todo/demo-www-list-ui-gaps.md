# Demo web UI: list pages show no items, and the item actions have rough edges

Found 2026-10-31 by the first browser walk of the demo web UI with the local
QA account (`thoughts/plans/2026-10-30-spanned-list-items.md`, iteration
batch of 2026-10-31; screenshots were kept outside the repository). All
predate the spanned-items work; none loses data.

- **The list page shows no items and has no edit or delete controls.**
  `/<id>/www/properties/<list>` renders "List with N items" only, and the
  list is not a link from `/<id>/www/properties` (Delete is the only
  action). The demo's template renders the value, not the library's list
  section, so item edit and delete through `/www/properties/<list>/items`
  are reachable only by a hand-built form POST.
- **An empty `item_value` on `update` replaces the item with `""`**
  (`handlers/www.py`, the items `update` action checks presence, not
  emptiness; `add` refuses an empty value with 400).
- **Error answers render a blank page.** A 400 for a bad index or a
  missing action carries its reason only in the status line, and the
  browser is left on `/items`.
- **A list's type badge reads "a"** on the list page instead of "list".
- At 375 px the actor id runs to the card's edge (no horizontal scroll).

Decide whether the demo should render items (with a body preview for large
items, which `items_with_handles(resolve=False)` makes cheap) or link to the
library's list template.
