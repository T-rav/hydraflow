---
id: 2483
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T06:55:23.588245+00:00
status: active
corroborations: 1
supersedes: 2363
---

# Self-chore exclusion requires path corroboration, not prefix alone

In `src/audit/sampling.py`, never exclude a merge from re-audit based on subject prefix alone — match the subject's claimed loop against a prefix→write-scope table and exclude ONLY when every changed path sits inside that loop's scope.

Example: `chore(arch):` → `docs/arch/` excludes a merge touching only `docs/arch/generated/gauntlet-calibration.md`, but selects one touching `src/audit/`. See also: [patterns] — Use startswith on posix paths; [patterns] — Gauntlet-classified artifacts are not adversarial.

**Why:** Subject prefix is forgeable; without path corroboration, an adversarial merge escapes the gauntlet stratum (weight 4.0) purely by wearing a maintenance prefix.
