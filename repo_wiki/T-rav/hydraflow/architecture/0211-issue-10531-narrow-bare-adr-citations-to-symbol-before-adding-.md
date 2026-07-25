---
id: 0211
topic: architecture
source_issue: 10531
source_phase: plan
created_at: 2026-07-25T09:52:15.450977+00:00
status: active
corroborations: 1
---

# Narrow bare ADR citations to :Symbol before adding a shared-infra exemption

In `adr_drift._citation_drifts`, a bare `src/foo.py` citation drifts on *any* file touch, while a `` `src/foo.py:Symbol` `` citation only drifts when the diff reports that changed symbol. When a single ADR bare-cites a module and churns on unrelated PRs (a #9176-class false positive), prefer narrowing the citation to `:Symbol` granularity over adding the module to `_SHARED_INFRA_MODULES` — that list is for cross-cutting infra and would mute drift for every future ADR citing the file, not just this one. Example: ADR-0108's B5 row cited bare `src/phase_utils.py`; narrowed to `` `src/phase_utils.py:file_memory_suggestion` ``. **Why:** `_SHARED_INFRA_MODULES` is a blunt, permanent suppression — reach for it only when multiple ADRs legitimately share the module, not to silence one noisy citation.
