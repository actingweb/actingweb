# Vouching and adoption: what the 4.0 adoption-findings plan left

**Filed:** 2026-11-19, by `thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md` (the rest of the consumer's A3 and A6, and
the evaluation's finding 39).

- **Leave actors with no sign of a sign-in unmarked (A3).** The marking
  writes a marker on every unmarked actor in scope; "no sign of a sign-in"
  has no definition yet (a login timestamp the library does not keep, a
  token, a trust row). `--ids-file` lets an operator choose by hand today.
- **Tell peers about an actor that was cleaned (A6).** The `actor_adopted`
  hook and the `ACTOR_ADOPTED:` line tell the application and its operator;
  peers whose trusts the clean removed learn it only from a refused call.
  A protocol question (a notification the specification does not have).
- **A bridge-created actor reads vouched for a synthesised address
  (finding 39).** An actor the MCP OAuth bridge creates is marked
  `oauth2_bearer` (`handlers/mcp.py`, the bridge's create), which vouches,
  and with no bound address it is vouched for whatever its creator is.
  Existing marker semantics, rejected for the plan; decide whether the
  bridge should record the address it vouches for.
