---
id: 1374
topic: gotchas
source_issue: 11211
source_phase: review
created_at: 2026-08-15T06:58:01.011492+00:00
status: stale
corroborations: 1
stale_reason: source issue #11211 closed
---

# HydraFlow has three agentic spawn seams, not two

When adding per-repo routing dials (e.g., `apply_repo_provider`), wire them across all three spawn seams: `base_runner._execute`, `BaseSubprocessRunner.run`, and direct `runner_utils.stream_claude_with_telemetry` callers (`src/acceptance_criteria.py`, `src/verification_judge.py`, `src/report_issue_loop.py`).
- **Example:** ADR-0134 falsely claimed all roles routed to GLM, but `ac`, `judge`, and `report_issue` bypass `apply_repo_provider` entirely via `stream_claude_with_telemetry`.
- **Why:** Wiring only the tested seams leaves direct callers silently unrouted, creating an unfalsifiably wrong ADR that operators trust.
