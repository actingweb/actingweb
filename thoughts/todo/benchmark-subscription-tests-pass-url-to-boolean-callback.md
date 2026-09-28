# DynamoDB accepts a non-bool subscription `callback`

**Provenance:** found on 2026-09-14 while running the full parallel suite
against PostgreSQL to validate the 3.14.7 dependency refresh (PR #146).

## What is open

`callback` is a **boolean** on both backends -- `BooleanAttribute` in
`actingweb/db/dynamodb/subscription.py:36`, `sa.Boolean()` in
`actingweb/db/postgresql/schema.py:151` -- meaning "deliver by callback",
not a URL. PostgreSQL refuses a string (`invalid input syntax for type
boolean`); DynamoDB accepts a string such as
`"https://callback.example.com"` without complaint. Whether PynamoDB coerced it to `True` or stored it as-is has not
been checked.

## What doing it buys

The two backends agree on what `DbSubscription.create(callback=...)`
accepts, so a caller that passes the wrong type fails on DynamoDB too
instead of only on PostgreSQL.

## What has to be decided first

Reject or coerce a non-bool `callback` on DynamoDB. `DbSubscription`'s
public callers in the library always pass a bool, so this is low priority.
