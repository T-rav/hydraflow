---
id: 3391
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:57.720332+00:00
status: superseded
corroborations: 1
supersedes: 3254
superseded_by: 3538
---

# Gauntlet-classified artifacts are not adversarial

Do not use "is gauntlet-class" as a discriminator between genuine maintenance and adversarial merges. `docs/arch/generated/gauntlet-calibration.md` is a gauntlet-classified artifact that `DiagramLoop` legitimately regenerates during `chore(arch):` maintenance.

Example: If gauntlet classification triggered sampling, every genuine `chore(arch):` regen of `gauntlet-calibration.md` would be re-audited, re-opening #10808's self-audit flux. See also: [patterns] — Self-chore exclusion requires path corroboration.

**Why:** Path-scope corroboration is the only sound discriminator; gauntlet classification is orthogonal to adversarial intent.
