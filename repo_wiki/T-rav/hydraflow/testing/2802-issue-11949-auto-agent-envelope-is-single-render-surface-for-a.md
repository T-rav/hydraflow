---
id: 2802
topic: testing
source_issue: 11949
source_phase: plan
created_at: 2026-09-01T09:56:43.594662+00:00
status: active
corroborations: 1
---

# Auto-agent envelope is single render surface for all dispatches

Rules that must reach every auto-agent dispatch belong in `src/hydraflow_resources/prompts/auto_agent/_envelope.md`, not per-label prompts — the envelope is rendered into every auto-agent surface. Pin its content via the render helper in `tests/test_preflight_runner.py`, asserting on stable tokens (`scratchpad`, prefix phrasing, `--body-file`), never full sentences. **Why:** per-label edits drift; stable tokens survive prose rewrites, while full-sentence assertions break on every wording change.
