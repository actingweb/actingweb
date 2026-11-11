# Grant enforcement differs per route and per level of a property

**Security, unpublished.** Keep local until fixed, under the same rule as the
peer-authorisation records: never push this file before its fix.

The second security plan the owner decided on 2026-11-09, after
`verifications/2026-11-09-peer-authorisation-fixes-audit.md`. The
peer-authorisation PR closes identity and approval (audit A1 to A3, A9).
This plan closes how a granted peer's access is enforced. A4 (push of a
subtarget's single value) closed with reverify-6 Issues 4 to 6 in the PR's
iteration 50. Every item below
is on `master` (except A19, which the branch introduced); the audit has the
evidence (`file:line`) for each.

- **A5.** Permission patterns have no hierarchy (`permission_evaluator.py:114-134`):
  - a parent (`private` vs `private/*`) is readable and writable whole;
  - `/properties/<list>/<x>` returns the whole list past an exact-name
    exclusion;
  - list diffs pass the same way.
- **A6.** `/resources/<name>` never evaluates the resource grant
  (`handlers/resources.py:15-27`).
- **A7.** `POST /properties` applies list changes before its permission
  check, and the hook check fails open (`handlers/properties.py:1196-1690`;
  `hooks.py:438-446`).
- **A8.** Revocation deletes too little:
  - only `patterns` are compared, so an `excluded_patterns` entry or a
    dropped `read` is never a revocation;
  - only lists are deleted, never scalars;
  - copies stored by query skip the deletion.
- **A10.** Open client registration chooses its trust type, `admin`
  included (`oauth2_server/client_registry.py:114`). Trace what the
  `client_credentials` token reaches through `/mcp` first.
- **A11.** `FanOutManager` sends one unfiltered payload to every subscriber
  (`fanout.py:535`).
- **Lows:**
  - A12, owner base-URI changes are not `/meta`-checked;
  - A13, trust deletes are unconditional;
  - A14, approval and delete hooks differ by route;
  - A15, a PUT approves before writing its grant;
  - A16, the async create drops its row only on some errors;
  - A17, `shared_properties` discloses every name as excluded;
  - A18, evaluator errors fail open on methods, actions and hooks;
  - A19, the pull accepts only ALLOWED where a direct read falls back on
    NOT_FOUND (introduced);
  - A20, an unapproved row can list its peer id's subscriptions.

Every fix is checked against `docs/protocol/actingweb-spec.rst` (owner).
