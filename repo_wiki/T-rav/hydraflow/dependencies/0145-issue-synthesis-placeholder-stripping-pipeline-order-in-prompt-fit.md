---
id: 0145
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:41:45.186230+00:00
status: superseded
corroborations: 1
supersedes: 0134
superseded_by: 0160
---

# Placeholder stripping pipeline order in prompt_fitness.py

Use header-scoped diff stripping and f-string literal stripping rather than blanket column-0 line rules in the `placeholder_leaks()` pipeline in `prompt_fitness.py`.

Example: Pipeline must run: fences → inline → hunks → f-strings → scan. Avoid `r"^[+-].*$"` which wipes markdown bullets.

**Why:** Blanket stripping erases `- {placeholder}` bullets before scanning, causing the ADR-0116 §10 gate to report clean while blind to actual leaks.
