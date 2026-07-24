---
id: 0702
topic: gotchas
source_issue: 10458
source_phase: plan
created_at: 2026-07-24T13:01:26.369166+00:00
status: superseded
corroborations: 1
superseded_by: 0704
---

# New ADR-authoring aids belong in soft report sections, not CI gates

Author-facing nudges (like a `## Symbol-Granularity Nudges` section in `docs/arch/generated/adr_xref.md` via `src/arch/generators/adr_cross_reference.py`) should render as a visible section that can read "None", never as a build failure. This mirrors the stalled #10411 lesson: don't add a hard gate for something that's advisory, and don't block merge on background-run signals. **Why:** turning an authoring suggestion into a hard CI failure punishes valid bare citations to non-owned shared infra and creates false-positive blockers similar to what stalled #10411.
