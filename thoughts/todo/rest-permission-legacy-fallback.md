# The REST property handlers fall back to legacy authorization when the permission evaluator raises

Found while planning the MCP `*/list` fail-closed change
(`thoughts/plans/2026-10-30-spanned-list-items.md`, "What We're NOT
Doing"). Verified against the tree at `release/3.16.0-spanned-list-items`.

`actingweb/handlers/properties.py` has three permission checks that catch any
non-`DbError` exception from the evaluator and then answer with the legacy
`auth_obj.check_authorisation(path="properties", ...)` result instead of
denying (the comment is "Fall back to legacy authorization on errors"; `:212`, `:1894`,
`:2079`, in `PropertiesHandler._check_property_permission`,
`PropertyMetadataHandler._check_property_permission` and
`PropertyListItemsHandler._check_property_permission`).

This is the REST counterpart of the MCP `*/list` fail-open the 3.16 plan
closed: a peer whose trust type would deny a property path gets whatever the
coarse legacy `access` table grants the relationship when the evaluator has
a bug or cannot be built. For the default `access` table a `friend`,
`partner` or `admin` peer is then allowed every property method, so a
broken evaluator turns an `excluded_patterns` denial into an allow.

The `NOT_FOUND` branch (no rule for the peer) falls back to the same legacy
check by design, for backward compatibility; that is not part of this item.

What doing it buys: one policy across MCP and REST (an evaluator fault
denies). What has to be decided first: whether a fault should deny (403) or
answer 503 so a client can tell a server fault from a denial, and whether the
change waits for a minor, since a deployment whose evaluator raises today
would see 403s where it saw 200s.
