# DynamoDB backend scaling defects: hash-key `Scan`s and per-construction `DescribeTable`

Date: 2026-07-23 (reviewed same day: call sites, pynamodb behaviour and live-table state
re-verified; implementation gotchas expanded; Defect 4 added)
Branch: master (commit `29783f8`)
Origin: measured in the `actingweb_mcp` production deployment (`ai.actingweb.io`,
`eu-central-1`); companion doc at
`../actingweb_mcp/thoughts/research/2026-07-23-scaling-review-apigw-lambda-dynamodb.md`

## Summary

Two independent defects in `actingweb/db/dynamodb/` dominate the scaling behaviour of any
ActingWeb deployment on DynamoDB. Both are library-side, both are invisible at small
scale, and both degrade **superlinearly** as data and traffic grow:

1. **Eight `Model.scan()` calls filter on the partition key where `Model.query()` should
   be used.** Every one reads the entire table and discards non-matching items
   client-side. Measured in production: **486,322 RCU consumed in 6 hours** on a
   16.7 MB properties table holding data for **47 actors** — ≈239 full-table scans.
   Read cost is `O(total table size) × requests`, so each new actor makes every
   *existing* actor's read more expensive.

2. **Every `Db*.__init__` issues a live `DescribeTable` control-plane call.** The
   `if not X.exists(): X.create_table()` guard is repeated at 13 sites across 8 model
   modules and is not memoised; pynamodb's `exists()` never consults its own metadata
   cache. Measured: **1,396 `DescribeTable` calls/minute** at essentially zero
   application traffic.

A third, lesser issue: tables auto-created by that same guard inherit pynamodb `Meta`
provisioned-throughput defaults (1–26 RCU) instead of on-demand billing, silently
creating hard throughput walls on any table not separately declared in the deployer's
infrastructure-as-code. **Correction from review:** in the measured deployment one of
the two affected tables (`_property_lookup`) is *live on the login path*, not dormant —
see Defect 3.

A fourth issue found in review: the `Property` model **unconditionally declares a GSI
keyed on the property `value`** (`property-index`), while the lookup-table feature that
was built to replace it is toggled by *config only*. Schema and config are decoupled, so
fresh auto-created tables carry the legacy GSI (and its 2048-byte key limit and write
amplification) even when the lookup table is enabled — and older tables created before
the GSI existed (including the measured production table, verified live: no GSIs) crash
the legacy fallback code path if config ever selects it. See Defect 4.

None of these can be mitigated by AWS limit increases. All are fixable in this library
without touching consumer code.

---

## Defect 1: `scan()` with a partition-key filter

### The pattern

```python
# actingweb/db/dynamodb/property.py:381
self.handle = Property.scan(Property.id == actor_id)
```

`Property.id` is the **hash key**:

```python
class Property(Model):
    id    = UnicodeAttribute(hash_key=True)
    name  = UnicodeAttribute(range_key=True)
    value = UnicodeAttribute()
```

pynamodb's `scan(condition)` issues a DynamoDB `Scan` with a `FilterExpression`. DynamoDB
applies filters *after* reading, so the read cost is the full table regardless of how few
items match. `Property.query(actor_id)` reads only the target partition.

### Full call-site inventory

| File | Line | Call | Verdict |
| --- | --- | --- | --- |
| `property.py` | 381 | `Property.scan(Property.id == actor_id)` — `DbPropertyList.fetch` | **Defect** → `query` |
| `property.py` | 399 | `Property.scan(Property.id == actor_id)` — `fetch_all_including_lists` | **Defect** → `query` |
| `property.py` | 418 | `Property.scan(Property.id == self.actor_id)` — `delete`, indexed collect | **Defect** → `query` |
| `property.py` | 424 | `Property.scan(Property.id == self.actor_id)` — `delete`, main | **Defect** → `query` |
| `trust.py` | 455 | `Trust.scan(Trust.id == self.actor_id, consistent_read=True)` | **Defect** → `query` (2× cost, see below) |
| `trust.py` | 521 | `Trust.scan(Trust.id == self.actor_id, consistent_read=True)` | **Defect** → `query` (2× cost) |
| `peertrustee.py` | 153 | `PeerTrustee.scan(PeerTrustee.id == self.actor_id)` | **Defect** → `query` |
| `peertrustee.py` | 171 | `PeerTrustee.scan(PeerTrustee.id == self.actor_id)` | **Defect** → `query` |
| `peertrustee.py` | 49 | `scan((PeerTrustee.id == actor_id) & (PeerTrustee.type == peer_type))` | **Defect** → `query(actor_id, filter_condition=...)` |
| `actor.py` | 162 | `Actor.scan()` — `DbActorList.fetch`, no condition | **Intentional** (list-all); see caveat |

All of `Property`, `Trust` and `PeerTrustee` use `id` (the actor id) as hash key, so all
eight are mechanical `scan(...)` → `query(...)` conversions.

The conversion pattern is already proven in this codebase: `attribute.py`,
`subscription.py` and `subscription_diff.py` — the same hash/range shape — use
`Model.query(actor_id, ...)` throughout, including with `consistent_read=True`. The
eight scan sites are the stragglers, not a different design.

The two `trust.py` sites are the worst per-call: `consistent_read=True` doubles RCU
consumption (1.0 rather than 0.5 per 4 KB), so a strongly-consistent full-table scan costs
twice the already-inflated figure.

`actor.py:162` is a deliberate "list every actor" operation and cannot become a `query`.
It is not a defect, but it is `O(table)` and unpaginated — worth documenting as an
admin-only call and a candidate for pagination, since it will eventually time out.

### Production evidence

Live table (`AI_properties`), key schema confirmed via `describe-table`:

```json
KeySchema:      [{"AttributeName":"id","KeyType":"HASH"},
                 {"AttributeName":"name","KeyType":"RANGE"}]
TableSizeBytes: 16,678,841
ItemCount:      2,567
```

Cost per scan: 16,678,841 B ÷ 4 KB ≈ 4,072 blocks × 0.5 ≈ **2,036 RCU per call**, versus
~1 RCU for the equivalent `query`.

`ConsumedReadCapacityUnits`, peak 5-minute sums, same window, same deployment:

| Table | Peak 5-min Sum | Access pattern |
| --- | --- | --- |
| `AI_properties` | **152,073** | `Scan` |
| `AI_attributes` | 1,246 | mixed (no scan sites) |
| `AI_actors` | 87 | `Query` / `Get` |

**1,748×** between the scanned and the queried table — for 47 actors.

Six-hour aggregate on `AI_properties`:

```
6h total RCU:      486,322
projected/day:   1,945,286
avg sustained:        22.5 RCU/s
scan-equivalents:      239 full-table scans in 6h
```

### Why this is the dominant scaling constraint

Read cost is `O(total table size) × requests` — superlinear in users. At ~2,036 RCU per
fetch, a table's on-demand read ceiling is reached at roughly **20 property fetches per
second**, and that ceiling *halves every time the table doubles in size*. This binds well
before any API Gateway or Lambda concurrency limit, and unlike those it is not raisable by
support ticket.

> The "20/s" figure infers from the documented default on-demand per-table maximum
> (40,000 RCU) and was **not** verified against the measured account's Service Quotas. The
> 2,036 RCU/fetch and 486,322 RCU/6h figures are directly measured.

Secondary effect: DynamoDB paginates `Scan` at 1 MB, so a 16.7 MB table means ~17
sequential round trips per logical fetch — a latency cost that holds a caller's execution
slot open (in Lambda deployments, a concurrency slot).

### Proposed fix

Mechanical, per call site:

```python
# before
self.handle = Property.scan(Property.id == actor_id)
# after
self.handle = Property.query(actor_id)

# before (peertrustee.py:49)
PeerTrustee.scan((PeerTrustee.id == actor_id) & (PeerTrustee.type == peer_type))
# after
PeerTrustee.query(actor_id, filter_condition=PeerTrustee.type == peer_type)
```

`query()` returns the same `ResultIterator`, so the surrounding iteration code is
unchanged. `consistent_read=True` is a valid `query()` kwarg, so `trust.py` keeps its
semantics.

**Behavioural caveats to check during implementation** (expanded in review):

1. **Delete scope.** `scan()` returns items across all partitions; `query()` is scoped
   to one. For these eight sites the filter already restricts to a single `id`, so
   results should be identical — but `property.py:418/424` (`delete`) is the one to
   verify carefully, since a silent scope change there would mean under-deletion. Worth
   a test asserting that deleting actor A's properties leaves actor B's intact, which is
   exactly the case the current scan-based code gets right by accident and a buggy
   conversion could break.
2. **Result ordering changes.** `Scan` returns items in arbitrary order; `Query` returns
   them sorted by range key (`name` / `peerid`). `DbPropertyList.fetch` builds a dict so
   this is invisible there, but `DbTrustList.fetch` and `DbPeerTrusteeList.fetch` return
   arrays whose order becomes deterministic after the change. Harmless — arguably an
   improvement — but observable to consumers and to any order-sensitive test.
3. **Unguarded `None` hash key.** `DbTrustList.delete()` (trust.py:521) and
   `DbPeerTrusteeList.delete()` (peertrustee.py:171) use `self.actor_id` without
   checking it was set by a prior `fetch()`. Today `scan(Trust.id == None)` fails at
   condition serialisation; `query(None)` fails too, just with a different exception.
   Not a regression either way, but add the `if not self.actor_id: return False` guard
   (which `DbPropertyList.delete()` already has) while touching these lines.
4. **Truthiness is unchanged.** Both `scan()` and `query()` return a lazily-evaluated
   `ResultIterator`, which is always truthy — so the various `if self.handle:` checks
   behave identically before and after (they never detected emptiness in the first
   place).

## Defect 2: `DescribeTable` on every accessor construction

### The pattern

Repeated verbatim at 13 sites across 8 model modules — `actor.py:143`, `property.py:81`
and `:365`, `attribute.py:334` and `:401`, `trust.py:431` and `:533`,
`subscription.py:157` and `:218`, `subscription_diff.py:103` and `:171`,
`peertrustee.py:128`, `property_lookup.py:57`. (One wrapper, `DbPeerTrusteeList`, has
*no* guard — an existing inconsistency that the centralised fix below erases rather than
preserves.)

```python
def __init__(self):
    self.handle = None
    if not Property.exists():
        try:
            Property.create_table(wait=True)
        except Exception as e:
            if "ResourceInUseException" in str(e):
                pass
            else:
                raise
```

### Why it is not free

Verified against installed pynamodb 6.1.0:

```python
# pynamodb/models.py:752
@classmethod
def exists(cls) -> bool:
    try:
        cls._get_connection().describe_table()
        return True
    except TableDoesNotExist:
        return False

# pynamodb/connection/base.py:650
def describe_table(self, table_name: str) -> Dict:
    data = self.dispatch(DESCRIBE_TABLE, operation_kwargs)   # <- always a network call
    ...
    if meta_table.table_name not in self._tables:
        self.add_meta_table(meta_table)
```

`describe_table` *populates* the `_tables` metadata cache but never reads from it first.
There is no short-circuit. So every accessor construction blocks on a control-plane round
trip before any application work begins.

### Production evidence

CloudTrail `DescribeTable`, per-minute histogram:

```
14:01  1,290/min
14:07  1,396/min
14:11  1,307/min
```

≈23 calls/second with almost no application traffic. Caller identity:

```
principal: arn:aws:sts::…:assumed-role/…-lambdaRole/actingweb-mcp-prod-app
userAgent: Botocore/1.43.40 … os/linux … lang/python#3.11.15
table:     AI_attributes
```

The distribution is bursty — 50+ calls inside 2 seconds, then idle — consistent with one
request constructing many accessors, each firing its own `DescribeTable`.

### Framing of the harm

The provable, primary harm is a **latency tax per constructed object**, scaling with
`traffic × objects-per-request`. In serverless deployments it is worse than the raw number
suggests: a cold container runs the whole sweep serially on its first request, so this
cost lands precisely during a scale-up burst.

Control-plane throttling is a plausible secondary risk. This document deliberately asserts
no `DescribeTable` quota figure, as none was verified.

### Proposed fix

Collapse from per-object to once-per-process-per-table with a module-level guard, keeping
the developer-convenience auto-create behaviour intact:

```python
# actingweb/db/dynamodb/_ensure.py  (new)
import threading

_ensured: set[str] = set()
_lock = threading.Lock()

def ensure_table(model) -> None:
    """Create the model's table if absent — at most once per process per table."""
    name = model.Meta.table_name
    if name in _ensured:
        return
    with _lock:
        if name in _ensured:
            return
        if not model.exists():
            try:
                model.create_table(wait=True)
            except Exception as e:
                if "ResourceInUseException" not in str(e):
                    raise
        _ensured.add(name)
```

Each `__init__` block becomes `ensure_table(Property)`. This removes ~99% of the calls
while preserving current semantics.

**Gotchas found in review:**

1. **Test isolation.** The integration test harness deletes tables in-process
   (`tests/integration/conftest.py:154`, `cleanup_dynamodb_tables`, invoked from
   session-scoped fixtures). Today the deletions happen at session boundaries, so the
   memoised set is safe with the current suite — but any future fixture that drops
   tables mid-process would silently break: `_ensured` would still claim the table
   exists. Ship a `reset_ensure_cache()` (or make `_ensured` clearable) and call it from
   the cleanup helper, so the invariant is enforced rather than accidental.
2. **Cold start still pays a serial sweep.** With the guard, a fresh process still
   issues one `DescribeTable` per table (~8) on its first request — tens of
   milliseconds each, serially. That is why the opt-out flag below matters for
   serverless deployments, where it takes the residual cost to zero.
3. **Multi-prefix processes.** Keying `_ensured` by `Meta.table_name` is correct today
   because the prefix is baked into `table_name` at import time from `AWS_DB_PREFIX`;
   a process can only ever see one prefix. If table names ever become dynamic, the key
   must follow.

Worth doing alongside it (not just "considering"): an opt-out env flag (e.g.
`AW_DB_AUTO_CREATE_TABLES`, default on) so production deployments that manage tables via
CloudFormation/Terraform can skip the check entirely. Auto-creating tables from
application code is convenient in development but is arguably wrong in production, where
it also demands `dynamodb:CreateTable` (and this pattern, `dynamodb:DescribeTable`) in
the runtime IAM role — with the flag off, both can be dropped from the policy.

## Defect 3 (minor): provisioned-throughput defaults on auto-created tables

Because Defect 2's guard creates tables from application code, those tables inherit the
pynamodb `Meta` defaults rather than the deployer's intent:

```python
class Property(Model):
    class Meta:
        read_capacity_units = 26
        write_capacity_units = 2

class PropertyIndex(GlobalSecondaryIndex[Any]):
    class Meta:
        read_capacity_units = 2
        write_capacity_units = 1
```

Observed in the production account, where every table declared in the consumer's
CloudFormation is `PAY_PER_REQUEST` but the two auto-created ones are not:

```
AI_property_lookup   PROVISIONED   2 RCU / 1 WCU
AI_peertrustees      PROVISIONED   1 RCU / 1 WCU
(all others)         PAY_PER_REQUEST
```

1 WCU is one write per second. `property_lookup` backs email / `oauthId` → actor
resolution, i.e. the login path — and **in the measured deployment it is already
enabled and live** (review correction: the consumer enables it via
`.with_legacy_property_index(enable=False)` in its app builder, which sets
`config.use_lookup_table = True`; the `USE_PROPERTY_LOOKUP_TABLE` env var is only one
of three ways the flag can be set — see the config-plumbing note below). Verified
against the live table: 45 items, 4 RCU / 5 WCU consumed over 24 h. So this is not a
dormant landmine: it is a **live 2 RCU / 1 WCU wall on the login path**, currently
invisible only because traffic is tiny and DynamoDB burst credits absorb spikes. Nothing
in the library warns about it.

**Proposed fix:** set `billing_mode = PAY_PER_REQUEST_BILLING_MODE` in each model `Meta`
so auto-created tables scale by default, and treat the `*_capacity_units` values as dead
configuration to be removed. On-demand is the correct default for a library that cannot
know its consumer's traffic shape. Verified against installed pynamodb 6.1.0: when
`billing_mode == PAY_PER_REQUEST`, `Connection.create_table` omits
`ProvisionedThroughput` for both the table and every GSI, so the stale
`*_capacity_units` values in `Meta` and index `Meta` classes become inert.

**For already-created tables** the fix is an in-place conversion, *not* a recreate:

```bash
aws dynamodb update-table --table-name <prefix>_property_lookup \
  --billing-mode PAY_PER_REQUEST
```

Recreating would destroy live data (the measured deployment's lookup table holds the
login-path rows). Note the AWS constraint: a table's billing mode can only be switched
once per 24 hours.

**Config-plumbing wart (related, minor):** `use_lookup_table` has three sources of
truth — the `Config` default, the `USE_PROPERTY_LOOKUP_TABLE` env override
(`config.py:254`), and the fluent `with_legacy_property_index()` setter. Core paths get
the resolved value injected via the `actingweb.db.get_property()` factory, but
`DbProperty` / `DbPropertyList` constructed *directly* with no arguments silently fall
back to reading the env var (`property.py:96`), which can disagree with the app-level
setting. All in-library call sites use the factory today; the direct-construction
fallback is a trap for consumer scripts and should either be removed or made to raise.

## Defect 4 (design, found in review): the legacy `value` GSI is schema, but the toggle is config

The `Property` model unconditionally declares a GSI whose **hash key is the property
value**:

```python
# actingweb/db/dynamodb/property.py:18
class PropertyIndex(GlobalSecondaryIndex[Any]):
    class Meta:
        index_name = "property-index"
        projection = AllProjection()
    value = UnicodeAttribute(default="0", hash_key=True)

class Property(Model):
    ...
    property_index = PropertyIndex()
```

The lookup-table feature (`use_lookup_table` / `with_legacy_property_index(False)`) was
introduced precisely to escape this GSI's 2048-byte key limit — the library's own
docstring says the legacy path is "limited to 2048 bytes". But the flag only selects
which *code path* `get_actor_id_from_property()` takes. The GSI itself is part of the
model schema, and `create_table` always includes all declared indexes. The schema and
the config can therefore disagree in both directions:

1. **Fresh deployments get the legacy GSI even in lookup-table mode.** A newly
   auto-created `_properties` table carries `property-index` with `AllProjection`,
   which means (a) every property write is duplicated into the GSI — double write cost
   and double storage for a table that the lookup-table mode never reads — and (b) per
   DynamoDB's documented limit, **a write whose `value` exceeds 2048 bytes is rejected
   outright** (`ValidationException`), regardless of which lookup mode the app runs in.
   List/memory properties routinely exceed 2 KB. *Caveat: the write-rejection behaviour
   is asserted from AWS documentation and the library's own docstring; it was not
   empirically reproduced in this pass (no local DynamoDB was running) — verify with a
   >2 KB property write against a freshly auto-created table before treating it as
   confirmed.*
2. **Old tables lack the GSI, and the legacy code path assumes it exists.** The
   measured production table was created before `PropertyIndex` existed and has **no
   GSIs at all** (verified live: `GlobalSecondaryIndexes: null`). pynamodb never adds
   indexes to existing tables. On such a table, any config that selects the legacy path
   (`use_lookup_table = False`, the library default) makes
   `Property.property_index.query(value)` fail at runtime on the missing index. The
   library default configuration is therefore broken on this class of table.

The likely explanation for why production large-value writes work today is exactly (2):
the table predates the GSI, so the limit never applied there. That is luck, not design.

**Proposed direction:** stop declaring `PropertyIndex` on the model unconditionally.
Options, in rough preference order: (a) drop the GSI from the model and make
lookup-table mode the only reverse-lookup mechanism, with a migration/release note for
legacy-GSI users; (b) keep the legacy code path but build the index list dynamically at
table-creation time so lookup-table deployments create tables without the GSI; (c) at
minimum, fail fast with a clear error when the legacy path is selected but the index is
absent from the live table. Whichever is chosen, the invariant to restore is: *the
schema a deployment creates matches the code path its config selects.*

(`Trust.secret_index` and `Actor.creator_index` are also model-declared GSIs, but both
are keyed on short, code-generated values and are actively used by their query paths —
no equivalent problem.)

## Suggested sequencing

1. **Defect 2** first — smallest diff, no behavioural risk, immediate and large win.
2. **Defect 1** next — mechanical but wants the per-site delete-scope tests described
   above.
3. **Defect 3** — trivial code change, but note it only affects *newly* created tables;
   existing provisioned tables must be converted out-of-band by the deployer via
   `update-table --billing-mode PAY_PER_REQUEST` (in place, once per 24 h — never by
   recreate, which loses data), so it needs a release-note line.
4. **Defect 4** — needs a design decision (deprecate the legacy GSI vs. conditional
   schema) before code; the fail-fast guard in option (c) is a cheap interim step that
   can ship with Defect 1.

All four are library-internal; no consumer API changes are implied beyond a possible
deprecation note for the legacy GSI path. Nothing in this document has been
implemented — it is a research pass only.

## Reproduction commands

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=DescribeTable \
  --start-time <iso> --region <region>

aws cloudwatch get-metric-statistics --namespace AWS/DynamoDB \
  --metric-name ConsumedReadCapacityUnits \
  --dimensions Name=TableName,Value=<prefix>_properties \
  --start-time <iso> --end-time <iso> --period 300 --statistics Sum

aws dynamodb describe-table --table-name <prefix>_properties --region <region>
```
