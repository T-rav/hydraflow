---
id: 1273
topic: gotchas
source_issue: 11103
source_phase: plan
created_at: 2026-08-14T07:34:32.949740+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Coverage job is non-gating — absent from ci-gate.needs

The `Coverage (trailing)` job in `.github/workflows/ci.yml` is not listed in `ci-gate.needs`, so it cannot block merges. This is intentional: the coverage lane experiments with leg splits and `--cov` flags that would be too risky to gate on.

- A bad iteration that trips `--cov-fail-under=70` shows red on the job but does not block the PR.
- Use this freedom for pre-merge empirical checks (e.g., statement-count verification after a re-split).
- Do not treat a coverage-job green as a merge signal on its own.

**Why:** Knowing which CI jobs gate prevents both false confidence (treating non-gating green as a merge signal) and over-caution (blocking on a job that cannot block).
