---
id: 1309
topic: patterns
source_issue: 10896
source_phase: plan
created_at: 2026-07-31T12:32:01.782655+00:00
status: superseded
corroborations: 1
superseded_by: 1383
---

# Gauntlet stratum bypasses self-chore exclusion in select_sample

In `src/audit/sampling.py::select_sample`, classify blast-radius first, then apply `is_self_chore_change` exclusion **only when class != `gauntlet`**.

- `chore(arch):` merge touching `src/audit/detect.py` → sampled at `base_rate=0.25`
- Same subject touching `docs/wiki/*.md` → excluded (routine/structural)

**Why:** Prevents the factory from silently changing the audit machinery that judges it — the gauntlet cannot be self-excluded.
