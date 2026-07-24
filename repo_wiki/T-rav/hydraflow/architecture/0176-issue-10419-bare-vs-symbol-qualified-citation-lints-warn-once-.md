---
id: 0176
topic: architecture
source_issue: 10419
source_phase: plan
created_at: 2026-07-24T07:06:01.754987+00:00
status: active
corroborations: 1
---

# Bare-vs-symbol-qualified citation lints: warn once per file, not per occurrence

When an ADR cites the same shared-infra file both bare (`` `src/config.py` ``) and symbol-qualified (`` `src/config.py:HydraFlowConfig` ``), decide the dedup rule up front: warn iff ≥1 bare citation to a shared-infra file exists, regardless of how many symbol-qualified citations also appear. `src/adr_pre_validator.py`'s new `_check_shared_infra_bare_citations` follows this rule with its own private bare-citation regex (kept local per the `adr_index` idiom of modules owning their own regex copies).
**Why:** without a single fixed dedup rule, a mixed-citation ADR can double-warn or wrongly warn depending on scan order.
