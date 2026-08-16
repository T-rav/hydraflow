---
id: 0371
topic: architecture
source_issue: 11306
source_phase: plan
created_at: 2026-08-16T05:13:33.717471+00:00
status: active
corroborations: 1
---

# Gotchas audit: exports, conftest duplication, Port work, ADR-0049

Before finalizing a plan, verify: (1) new util modules export only public names — no `_`-prefixed cross-module imports; (2) no new helpers duplicating `tests/conftest.py`; (3) no new `subprocess`/`gh`/`git` calls — these require Port work; (4) no new loop — new loops trigger ADR-0049 kill-switch review. **Why:** These checks prevent scope creep and architectural violations that surface as review blockers.
