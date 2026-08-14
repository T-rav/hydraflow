---
id: 2569
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.635073+00:00
status: active
corroborations: 1
supersedes: 2381
---

# render_prompt uses str.format — add kwargs unconditionally

`render_prompt` in `src/preflight/runner.py` calls `str.format` over a fixed kwarg set. Adding a placeholder to a shared template (e.g. `_envelope.md`) or omitting a kwarg raises `KeyError` for all sub-labels.

Example: add new kwargs (like `sublabel_extras_block`) unconditionally to the format call; reference them only in the specialist template. Keep a test asserting an unrelated sub-label still renders.

**Why:** A missing kwarg breaks every playbook at once, not just the one you intended to extend.
