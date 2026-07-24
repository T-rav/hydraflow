---
id: 0196
topic: architecture
source_issue: 10455
source_phase: plan
created_at: 2026-07-24T12:32:23.750650+00:00
status: active
corroborations: 1
---

# _SHARED_INFRA_MODULES allowlist absorbs bare-cite ADR-drift false positives

Files bare-cited by many ADRs without symbol granularity belong in the `_SHARED_INFRA_MODULES` frozenset in `src/adr_drift.py`, not fixed via `_citation_drifts`/config changes. Example: `src/review_advisor.py` and `src/review_phase/_phase.py` are bare-cited by ADR-0059/0094/0095/0102/0103/0104, so any implementation-only touch to either file was batch-flagging ~15 findings across 3 PRs until added to the allowlist. **Why:** a bare citation to a shared-infra file is a dependency pointer, not evidence the ADR's contract changed — treating it as drift-worthy makes every unrelated PR touching that file noisy.
