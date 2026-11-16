# /create_specs addendum

These are this repository's sources, so the inventory does not have to find
them. Confirm them with the owner like any other inventory result.

**What a capability is here.** The library's users are application
developers, API clients (peers, OAuth2 and MCP clients) and operators. A
capability is what one of them would name: actors and the factory, trust,
subscriptions and callbacks, properties and property lists, grants, OAuth2
sign-in, the MCP server, the web UI, the operator commands. Not a module.

**Entry points**
- HTTP handlers: `actingweb/handlers/`, routed by
  `actingweb/interface/integrations/flask_integration.py` and
  `fastapi_integration.py`. Both integrations serve the same behaviour; a
  difference between them is a finding.
- The developer API: `actingweb/interface/` (`ActingWebApp`,
  `ActorInterface`, the managers, the hook registry).
- Operator commands: the `actingweb-*` console scripts in `pyproject.toml`.
- Storage: `actingweb/db/protocols.py` is the contract. The DynamoDB and
  PostgreSQL backends must behave the same from outside; a difference is a
  finding (expired rows and fault returns are where they diverge).

**User-facing docs (sources, never specs)**
- `docs/` (guides, references, `docs/migration/`), `CHANGELOG.rst` and
  `README.rst`. A statement they make to a consumer supports `[doc]`.
- `docs/protocol/actingweb-spec.rst` is the protocol's specification: what
  any implementation must do. It supports `[doc]` for wire behaviour. Where
  the library does more or less than it says, that is a finding, not a
  statement to copy.

**Tests**
- `tests/` (unit, against DynamoDB Local) and `tests/integration/` (a
  server per worker, both backends). Only assertions count as sources.
- Wire recordings: `tests/integration/wire/*.json`, registered in
  `tests/integration/wire/rows.toml`. A row records what the library does,
  right or wrong, and its `expected` text says what is known to be wrong:
  read it before citing the row as `[test]`.
- `examples/demo/` is exercised by `tests/test_demo_example.py`. It shows
  one application's use, not the library's rules.

**Other checks**
- `tests/integration/verify_groups.py` (the wire registry and its ownership
  trailers) and `tests/test_spec_option_tags.py` (advertised option tags
  against the protocol specification) state rules without being behaviour
  tests of a capability.
- `.oss-scanner/threat_model.md` names the security properties reviews
  check. A property seen from outside is a spec statement or a decision.

**Plans and verifications**
- `thoughts/plans/` and `thoughts/verifications/` support `[plan]`. A
  verification demonstrates a security property by naming the test and its
  assertion: prefer that test as the source.
- `thoughts/todo/` lists what is known to be wrong or missing. A behaviour
  with an open todo goes under Not supported or is marked as a known defect;
  it is never written as intended.

**Rules for this repository**
- A spec may name internals and consumers where a maintainer needs them;
  `docs/` and the changelog may not name a consumer. Do not copy a spec
  sentence into `docs/` without rewriting it for a consumer.
- A behaviour that differs between DynamoDB and PostgreSQL, or between
  Flask and FastAPI, is reviewed with the owner before it is written down.
- When proposing the order, security-relevant capabilities come first:
  grants and peer access, trust, OAuth2 and MCP sign-in.
