---
id: 0359
topic: architecture
source_issue: 11242
source_phase: plan
created_at: 2026-08-15T10:14:37.592606+00:00
status: active
corroborations: 1
---

# Full make quality required for arch-regen generator changes

Changes to `src/arch/generators/ai_system_inventory.py` require `make arch-regen` plus full `make quality` — not a file-targeted test subset. Arch-regen generators feed PR-comment renderers and other cross-module consumers; subset runs hide breakage (cf. #8460/#8463). After escaping fixes, a non-empty `arch-regen` diff signals live backslash data in current arch inputs, not a bug.

**Why:** Arch-regen generators have broad downstream reach; a subset run hides cross-module breakage until production.
