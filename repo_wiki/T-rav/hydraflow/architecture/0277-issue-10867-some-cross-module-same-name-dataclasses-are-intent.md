---
id: 0277
topic: architecture
source_issue: 10867
source_phase: plan
created_at: 2026-07-31T03:20:17.216764+00:00
status: active
corroborations: 1
---

# Some cross-module same-name dataclasses are intentional, not merge artifacts

`JudgeVerdict` (`models.py`→`verification_judge`/`post_merge_handler` vs `convergence_gate`→`review_phase`) and `JudgeResult` (`models.py`→`verification` vs `spec_judge`→`plan_phase`) are same-name dataclasses with live consumers on both sides. These are intentional per ADR-0027 Rule 4 and belong on a curated allow-list, not consolidated. Merging them is a separate high-blast-radius issue.

**Why:** Forcing consolidation of semantically distinct types breaks live consumers on one side of the pair.
