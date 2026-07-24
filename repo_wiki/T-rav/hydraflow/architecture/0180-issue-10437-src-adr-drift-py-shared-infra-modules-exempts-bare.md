---
id: 0180
topic: architecture
source_issue: 10437
source_phase: plan
created_at: 2026-07-24T10:30:36.222641+00:00
status: active
corroborations: 1
---

# src/adr_drift.py _SHARED_INFRA_MODULES exempts bare-cite drift FPs

Add a module to the `_SHARED_INFRA_MODULES` frozenset in `src/adr_drift.py` when it's a high-churn, cross-cutting file that ADRs only bare-cite as a dependency pointer. Membership makes bare citations not drift on unrelated file-only churn; symbol-qualified citations (e.g. `path:BaseBackgroundLoop.run`, as ADRs 84/93/99 use) still drift regardless of membership — that's the escape hatch. `src/base_background_loop.py` was added here for issue #10437 because ADR-0106 and ADR-0055 bare-cite it and unrelated loop-body PRs (e.g. #10414) were false-positive drifting both.

**Why:** Without the allowlist, every PR touching a shared base class batch-drifts every ADR that mentions it in passing — the systemic FP class behind #9176 and siblings #10408/#10411/#10413/#10437.
