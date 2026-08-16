---
id: 3552
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:22.692318+00:00
status: superseded
corroborations: 1
supersedes: 3405
superseded_by: 3697
---

# Gauntlet stratum bypasses self-chore exclusion in select_sample

In `src/audit/sampling.py::select_sample`, classify blast-radius first, then apply `is_self_chore_change` exclusion **only when class != `gauntlet`**.

Example: `chore(arch):` merge touching `src/audit/detect.py` → sampled at `base_rate=0.25`; same subject touching `docs/wiki/*.md` → excluded (routine/structural). See also: [patterns] — Self-chore exclusion requires path corroboration.

**Why:** Prevents the factory from silently changing the audit machinery that judges it — the gauntlet cannot be self-excluded.
