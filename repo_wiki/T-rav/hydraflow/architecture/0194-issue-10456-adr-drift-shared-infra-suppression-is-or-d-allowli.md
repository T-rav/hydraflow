---
id: 0194
topic: architecture
source_issue: 10456
source_phase: plan
created_at: 2026-07-24T12:31:36.987700+00:00
status: active
corroborations: 1
---

# ADR-drift shared-infra suppression is OR'd: allowlist OR fanout threshold

When extending `_citation_drifts` in `src/adr_drift.py` with fan-out-based suppression, OR the new check against the existing `_SHARED_INFRA_MODULES` allowlist — never replace it. A bare citation is suppressed if the path is in `_SHARED_INFRA_MODULES` **or** `_bare_citation_fanout(path, adrs) >= fanout_threshold`. Keeping both paths independent means threshold=None (default) reproduces prior allowlist-only behavior exactly, preserving regression parity while adding automatic suppression for modules that cross the citation-count threshold.

**Why:** collapsing to a single suppression path would either break existing allowlist entries or make fanout the only way to suppress, silently changing behavior for repos not yet using the threshold.
