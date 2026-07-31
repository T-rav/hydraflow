---
id: 0296
topic: architecture
source_issue: 10871
source_phase: review
created_at: 2026-07-31T16:47:39.085945+00:00
status: stale
corroborations: 1
stale_reason: source issue #10871 closed
---

# Use importlib spec_from_file_location for script loading in src/

Load script-style modules dynamically via `importlib.util.spec_from_file_location`, never via direct `import`. This is enforced by `tests/architecture/test_src_does_not_import_scripts.py`.

- `src/prompt_fitness.py` `load_audit_module()` uses this loader pattern.

**Why:** Direct imports of script files break in containerized/runner environments where file layout differs from installed package paths; the architecture test exists specifically to catch this.
