---
id: 0179
topic: architecture
source_issue: 10433
source_phase: plan
created_at: 2026-07-24T10:22:54.781357+00:00
status: active
corroborations: 1
---

# Reserve _SHARED_INFRA_MODULES for citations spanning multiple ADRs

Don't add a module to `_SHARED_INFRA_MODULES` just to silence one ADR's drift — that set is for cross-cutting infra cited by many ADRs. `src/issue_fetcher.py` is cited by only ADR-0019, so the correct repair is symbol-qualifying the single citation (docs/adr/0019-*.md line 121), not widening the shared-infra exemption list.

**Why:** misusing the shared-infra list masks future drift for *other* ADRs that later cite the same file, since the whole module becomes exempt globally.
