# The conditional-update fault log lines carry the row name, which can be a token

**Filed:** 2026-11-23, by the security evaluation of
`thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.md` (Low,
log readers only). Present before that plan.

A fault in `conditional_update_attr` is logged with the attribute name in
full: `db/postgresql/attribute.py` ("Error conditionally updating attribute
{actor_id}/{bucket}/{name}") and `db/dynamodb/attribute.py`
`_log_unexpected` ("{op} on {bucket}:{name} failed"). For single-use rows
the name is the token or code itself (`oauth_session.py`, the refresh-token
consume in `oauth2_server/token_manager.py`). `single_use._mask` shortens
the same value to eight characters for its own log lines.

Mask the name in both backend lines the way `_mask` does, and check
`delete_attr_conditional`'s lines for the same.
