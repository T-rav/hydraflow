---
id: 1714
topic: testing
source_issue: 10858
source_phase: plan
created_at: 2026-07-31T01:20:45.119644+00:00
status: active
corroborations: 1
---

# Template discovery is a runtime scan, not a hardcoded list

`discovered_templates()` in `src/prompt_fitness.py` must scan `prompts/**/*.md` and `.claude/agents/*.md` at runtime. Adding a new `.md` file makes it appear in the discovered set with no code edit.

Partials (e.g. `_envelope.md`) go in a `TEMPLATE_PARTIALS` dict where every entry carries a reason string and a pinned max.

**Why:** A hardcoded list decouples the coverage denominator from the filesystem, so new templates silently sit outside coverage and the series reads 100% while real gaps exist.
