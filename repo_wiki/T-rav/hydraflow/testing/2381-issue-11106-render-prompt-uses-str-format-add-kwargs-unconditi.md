---
id: 2381
topic: testing
source_issue: 11106
source_phase: plan
created_at: 2026-08-14T07:39:28.346565+00:00
status: active
corroborations: 1
---

# render_prompt uses str.format — add kwargs unconditionally

`render_prompt` in `src/preflight/runner.py` calls `str.format` over a fixed kwarg set. Adding a placeholder to a shared template (e.g. `_envelope.md`) or omitting a kwarg raises `KeyError` for all sub-labels.

- Add new kwargs (like `sublabel_extras_block`) unconditionally to the format call
- Reference them only in the specialist template (e.g. `trust-loop-anomaly.md`)
- Keep a test asserting an unrelated sub-label still renders

**Why:** A missing kwarg breaks every playbook at once, not just the one you intended to extend.
