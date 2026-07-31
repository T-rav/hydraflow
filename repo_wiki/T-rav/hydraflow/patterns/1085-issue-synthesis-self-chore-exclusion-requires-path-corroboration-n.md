---
id: 1085
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:49:30.685224+00:00
status: superseded
corroborations: 1
supersedes: 1018
superseded_by: 1154
---

# Self-chore exclusion requires path corroboration, not prefix alone

In `src/audit/sampling.py`, never exclude a merge from re-audit based on subject prefix alone — a `chore(arch):` merge touching `src/audit/sampling.py` must still be sampled. Match the subject's claimed loop against a prefix→write-scope table and exclude ONLY when every changed path sits inside that loop's scope.

Example: `chore(arch):` → `docs/arch/` excludes a merge touching only `docs/arch/generated/gauntlet-calibration.md`, but selects one touching `src/audit/`.

**Why:** Subject prefix is forgeable; without path corroboration, an adversarial merge escapes the gauntlet stratum (weight 4.0) purely by wearing a maintenance prefix.
