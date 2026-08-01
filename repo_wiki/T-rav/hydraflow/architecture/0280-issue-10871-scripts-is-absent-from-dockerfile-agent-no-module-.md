---
id: 0280
topic: architecture
source_issue: 10871
source_phase: plan
created_at: 2026-07-31T06:30:13.825313+00:00
status: stale
corroborations: 1
stale_reason: source issue #10871 closed
---

# scripts/ is absent from Dockerfile.agent — no module-scope imports

Never import `scripts.*` at module scope in `src/`. `scripts/` is excluded from `Dockerfile.agent`, so a module-scope `from scripts.audit_prompts import ...` crashes the container. To load `scripts/audit_prompts.py` from `src/prompt_fitness.py`, use `importlib.util.spec_from_file_location` with the file path.

Enforced by `tests/architecture/test_src_does_not_import_scripts.py`.

**Why:** A passing local test suite can still ship a broken agent image; the architecture test is the only gate that catches the import boundary before deploy.
