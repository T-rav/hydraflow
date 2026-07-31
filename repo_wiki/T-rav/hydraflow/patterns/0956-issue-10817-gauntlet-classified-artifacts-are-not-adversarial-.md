---
id: 0956
topic: patterns
source_issue: 10817
source_phase: plan
created_at: 2026-07-31T01:28:07.215000+00:00
status: active
corroborations: 1
---

# Gauntlet-classified artifacts are not adversarial: DiagramLoop writes gauntlet-calibration.md

Do not use "is gauntlet-class" as a discriminator between genuine maintenance and adversarial merges. `docs/arch/generated/gauntlet-calibration.md` is a gauntlet-classified artifact that `DiagramLoop` legitimately regenerates during `chore(arch):` maintenance.

**Why:** If gauntlet classification triggered sampling, every genuine `chore(arch):` regen of `gauntlet-calibration.md` would be re-audited, re-opening #10808's self-audit flux. Path-scope corroboration is the only sound discriminator.
