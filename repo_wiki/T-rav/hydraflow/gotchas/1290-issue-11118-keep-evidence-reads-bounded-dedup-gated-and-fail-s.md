---
id: 1290
topic: gotchas
source_issue: 11118
source_phase: plan
created_at: 2026-08-14T10:22:06.549512+00:00
status: active
corroborations: 1
---

# Keep evidence reads bounded, dedup-gated, and fail-soft in filing path

Wrap the `load_inferences()` read inside `_file_inefficiency_issue` (`src/skill_prompt_eval_loop.py`) in a guarded block. Bound the read with a module constant in `src/prompt_inefficiency_evidence.py`, and keep it inside the already-dedup-gated filing branch so it runs at most once per source per open issue. On any read failure, still file with snapshot-derived evidence plus an explicit coverage disclosure; use `logger.warning` with a literal format string and args, not an interpolated variable.

**Why:** An unbounded read on a busy repo makes filing slow or memory-heavy, and a telemetry failure must never block or crash the issue filing.
