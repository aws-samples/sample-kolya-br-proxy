# Self-Service Usage API Design

**Status:** Implemented

## Purpose

Expose an API-key-authenticated view of the quota state and daily usage that
belongs to the caller. The reported numbers must use the same calculation as
request quota enforcement so operators and clients do not see a different
remaining balance from the value enforced by the gateway.

## Motivation

Quota exhaustion is currently observable to an API-key user only after a model
request is rejected with HTTP 429. That makes the enforcement result the first
warning that the available allowance has been consumed, which is too late for
proactive production planning.

A supported query interface lets operators observe remaining allowance,
measure burn rate, forecast exhaustion risk, and alert early enough to adjust
usage or capacity before requests start failing.

## API contract

The feature adds two endpoints:

```text
GET /v1/usage/quota
GET /v1/usage/timeseries?start_date=...&end_date=...
```

Both endpoints use the existing flexible API-key authentication dependency.
The authenticated token determines the data scope; neither endpoint accepts a
caller-supplied `token_id`.

Quota endpoints remain available after a monthly, daily, or lifetime limit is
exceeded. Model request endpoints enforce those limits, while these read-only
endpoints only require a valid API key.

### Quota snapshot

`GET /v1/usage/quota` returns the current quota state, including:

- the personal or team quota scope;
- the usage window and next allowance timestamp;
- monthly base limit, effective allowance, usage cost, adjustments, quota
  impact, and remaining balance;
- daily limit state and daily quota impact;
- lifetime limit, quota impact, and remaining balance;
- exceeded flags for monthly, daily, and lifetime limits; and
- the count of usage records that could not be priced.

Money values are serialized as decimal strings to avoid floating-point
rounding in clients. A `null` limit or remaining value represents an unlimited
dimension rather than zero allowance.

### Daily time series

`GET /v1/usage/timeseries` returns half-open UTC daily buckets for the requested
range. Each bucket includes:

- model call count;
- input, output, and total token counts;
- model usage cost;
- balance adjustments;
- total quota impact; and
- unpriced request count.

The maximum query range is 90 days. `start_date` must be earlier than
`end_date`.

## Quota semantics

Quota impact is kept distinct from model usage cost:

```text
quota impact = usage cost + balance adjustments
```

Usage rows contribute to model call and token counts. Adjustment rows affect
the quota balance but do not count as model calls or tokens. Positive
adjustments consume allowance and negative adjustments restore allowance.

Unpriced usage records are included in call and token totals, reported through
`unpriced_request_count`, and contribute zero cost until pricing is available.

The existing quota rules remain authoritative, including:

- personal versus team quota selection;
- monthly reset and rollover behavior;
- team allocation of zero representing no available budget;
- optional team daily limits; and
- lifetime quota enforcement.

## Implementation

### Authoritative snapshot

`app.services.quota.get_quota_snapshot()` resolves the caller's effective quota
scope and returns an immutable `QuotaSnapshot`. It aggregates usage and
adjustments for the required daily, monthly, and lifetime windows.

`enforce_quota()` consumes this snapshot and preserves the existing enforcement
order and HTTP 429 messages:

1. lifetime limit;
2. monthly limit; and
3. daily limit.

Using the same snapshot for reporting and enforcement prevents calculation
drift between the dashboard and model request path.

### Time-series aggregation

`UsageStatsService.get_quota_timeseries()` groups records by UTC day and always
filters by the authenticated token ID. Usage and adjustment records are
aggregated separately before their combined quota impact is returned.

### Response schemas and routing

The response models live in `app.schemas.usage`, and the endpoints are
registered under the existing `/v1` router. Response fields use snake case to
match the existing API style.

The API never returns a plaintext API key, token hash, owner ID, or metadata
belonging to another token.

## Compatibility

This is an additive API change. Existing model endpoints, quota configuration,
and database schemas are unchanged. The quota enforcement refactor preserves
the previous limit precedence and error messages.

UTC boundaries are used consistently by enforcement and reporting. Clients
that display local calendar days should convert bucket timestamps only for
presentation and should not reinterpret the quota calculation window.

## Verification

Coverage includes:

- personal, team, unlimited, zero-allocation, daily, monthly, lifetime, and
  rollover quota cases;
- positive and negative balance adjustments;
- unpriced usage records;
- self-scoping to the authenticated token;
- invalid and greater-than-90-day ranges;
- endpoint response serialization and router registration; and
- SQL aggregation against a real relational schema.

The implementation was also exercised end to end with PostgreSQL 15, Alembic
at the current head, a seeded API token, model usage rows, and a balance
adjustment. The quota snapshot and daily time series returned matching quota
impact and remaining-balance values.

## Operational use

Consumers can use the quota snapshot for current remaining allowance and the
daily time series for burn-rate projections or alerting. Forecast policy stays
outside the gateway so clients can choose their own warning thresholds without
changing the authoritative quota calculation.

After deployment, verify both endpoints with a valid API key and compare the
reported quota impact with a known usage and adjustment sample before enabling
automated budget alerts.
