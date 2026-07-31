---
id: 0078
topic: dependencies
source_issue: 10865
source_phase: plan
created_at: 2026-07-31T02:25:44.330076+00:00
status: active
corroborations: 1
---

# Placeholder stripping pipeline in prompt_fitness.py

Use header-scoped diff stripping and f-string literal stripping rather than blanket column-0 line rules. The `placeholder_leaks()` pipeline must run: fences → inline → hunks → f-strings → scan.
Avoid `r"^[+-].*$"` which wipes markdown bullets.
**Why:** Blanket stripping erases `- {placeholder}` bullets before scanning, causing the ADR-0116 §10 gate to report clean while blind to actual leaks.
