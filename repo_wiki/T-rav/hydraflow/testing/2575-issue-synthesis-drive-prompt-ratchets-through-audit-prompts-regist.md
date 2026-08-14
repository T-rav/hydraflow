---
id: 2575
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.701108+00:00
status: active
corroborations: 1
supersedes: 2387
---

# Drive prompt ratchets through audit_prompts registry, not module lists

When injecting a clause into every verification-instructing prompt, enumerate targets via `scripts/audit_prompts.PROMPT_REGISTRY` and `render_target()`. Never hardcode a list of `src/*.py` modules.

Example: `FOREGROUND_VERIFICATION_CLAUSE` in `src/prompt_clauses.py` is appended at each render site; the ratchet test renders live via `render_target` rather than reading `tests/fixtures/prompts/*.json`.

**Why:** Hardcoded lists go stale when new runners are added; the registry is the single source of truth so the ratchet fails rather than passing vacuously.
