---
id: 1530
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:30:39.139196+00:00
status: active
corroborations: 1
supersedes: 1446
---

# Self-chore exclusion requires path corroboration, not prefix alone

In `src/audit/sampling.py`, never exclude a merge from re-audit based on subject prefix alone — match the subject's claimed loop against a prefix→write-scope table and exclude ONLY when every changed path sits inside that loop's scope.

Example: `chore(arch):` → `docs/arch/` excludes a merge touching only `docs/arch/generated/gauntlet-calibration.md`, but selects one touching `src/audit/`. See also: patterns — Use startswith on posix paths, not substring in.

**Why:** Subject prefix is forgeable; without path corroboration, an adversarial merge escapes the gauntlet stratum (weight 4.0) purely by wearing a maintenance prefix.
