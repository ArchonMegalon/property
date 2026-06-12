# PropertyQuarry Provider Quality Labels

Every provider must expose quality labels. Provider count alone is not a trust signal.

## Required Labels

```text
coverage
floorplan_reliability
duplicate_rate
tour_availability
scan_reliability
filter_pushdown_strength
official_source_quality
last_verified
```

## User-Facing Use

```text
explain why a result was included
explain when a provider filter is only post-filtered
show when a floorplan may be missed and needs a second pass
show when a provider is watch/restricted and needs verification
rank better providers ahead of weak fallback sources when fit is otherwise equal
```

## Operator Use

```text
trigger provider OODA repair when scan reliability drops
audit floorplan extraction misses by provider
separate official/cooperative/broker/community sources
record last verified date after live smoke tests
```

