# Research: DynamoDB fault reporting audit

**Date:** 2026-11-04
**Branch:** release/3.16.0-dependency-security
**Commit:** ec62ca6
**Origin:** the dependency-security roll-up's verifications found a shared
helper (`DbActor._run_transaction`) logging a creator-uniqueness remedy
for unrelated tables. On 2026-11-04 the owner asked for an audit of how
the DynamoDB backend reports faults.

Method: a read-only audit (no tests run). Defect 1 was fixed on the branch
(plan Iteration 14, commit `ec62ca6`) and is recorded here for
completeness.

## Research Questions

1. **Does every fault log name the operation and table that failed and a
   remedy that applies?** Mostly not. Only transaction ResourceNotFound
   faults and a few lookup paths log at the source. Everything else
   becomes `DbError(op)` ("database error during <op>") with no table,
   cause or remedy.
2. **Is any remedy reached from a caller it does not apply to?** Yes, the
   guarded branch (defect 1, fixed).

## Findings

**Medium**

1. **(Fixed in Iteration 14.)** The "guarded" missing-table ERROR named the
   actor table as the likely one, then gave only the creator remedy
   (`missing_enforcement_message`: "Run `actingweb-unique-creators enable
   --apply`"), which never creates the actor table. Each candidate table
   now gets its own remedy.
2. **Most faults are unlogged where they happen.**
   - Single-item calls raise `DbError` without a log for every fault:
     `actor get` (`db/dynamodb/actor.py:126` and others), `actor
     create/modify/delete`, `creator record get`, `actor list scan`,
     `property write/read/reverse lookup` (`property.py:219,283,299`),
     and lookup `owner read`, `delete`, `mark`, `unmark` and `record`
     (`property_lookup.py:152-208,292-294`).
   - `_run_transaction` logs only ResourceNotFound. AccessDenied,
     throttling and a conflict that lasts past the final attempt are
     silent.
   - `ensure_table` (`_ensure.py:95-105`) lets a `DescribeTable` or
     `CreateTable` fault escape unwrapped and unlogged.

   An operator then sees only "database error during actor get", with no
   table or cause.

**Low**

3. The probe-fault ERROR (`actor.py:57-62`) suggests `dynamodb:GetItem` for
   any exception, including throttling and network errors.
4. `property.py:389,587` log `str(DbError)`, which is only the op, so the
   cause is lost.
5. Raw exception text, which in botocore AccessDenied messages includes the
   role ARN, account id and table ARN, is logged at `actor.py:59,128,194,445,532,537,727`,
   `property_lookup.py:345,411,417,438,447,458`, `attribute.py:38`, and in
   the non-strict read helpers of `trust.py`, `peertrustee.py`,
   `subscription*.py` and `property.py`. This is consistent across the
   backend.
6. `read_readiness` raises "lookup table missing: <table>" with no remedy;
   PostgreSQL names `alembic upgrade head`.
7. PostgreSQL's index-probe fault (`postgresql/actor.py:73-74`) raises
   without a log, which is quieter than DynamoDB's.

## Recommended pattern

Classify a fault once in a shared helper, from `cause_response_code`:
ResourceNotFound, AccessDenied, throttling or other. Log a single ERROR
carrying the op, the table or tables involved, and a remedy for that kind
of fault:
- a missing table: name it, check `AWS_DB_PREFIX`, create the table;
- the creator remedy only when the missing table is the creators table;
- AccessDenied: name the IAM action and the table, without echoing the
  ARN;
- throttling: transient, or a capacity setting.

Call the helper from every `raise DbError(op) from e` on a strict path,
and from `ensure_table`.
