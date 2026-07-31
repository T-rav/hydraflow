---
id: 0114
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:51:45.306418+00:00
status: superseded
corroborations: 1
supersedes: 0104
superseded_by: 0124
---

# Placeholder stripping pipeline order in prompt_fitness.py

Use header-scoped diff stripping and f-string literal stripping rather than blanket column-0 line rules.

Example: The `placeholder_leaks()` pipeline in `prompt_fitness.py` must run: fences → inline → hunks → f-strings → scan. Avoid `r"^[+-].*$"` which wipes markdown bullets.

**Why:** Blanket stripping erases `- {placeholder}` bullets before scanning, causing the ADR-0116 §10 gate to report clean while blind to actual leaks.
