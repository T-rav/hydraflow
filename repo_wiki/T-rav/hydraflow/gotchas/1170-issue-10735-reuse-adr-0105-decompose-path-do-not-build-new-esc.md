---
id: 1170
topic: gotchas
source_issue: 10735
source_phase: plan
created_at: 2026-07-27T20:01:28.594807+00:00
status: active
corroborations: 1
---

# Reuse ADR-0105 decompose path — do not build new escalation

Wire the self-solve ladder to the existing ADR-0105 decompose→diagnose path and the P10.7 detector (#10358). Fold `implement` and `auto_agent` counters into `GiveUpClass` thresholds at their current caps rather than creating parallel escalation machinery.

- ADR-0115 required because this changes terminal behaviour set by prior ADRs

**Why:** Duplicate escalation paths diverge over time and create ambiguity about which terminal applies to a given failure class.
