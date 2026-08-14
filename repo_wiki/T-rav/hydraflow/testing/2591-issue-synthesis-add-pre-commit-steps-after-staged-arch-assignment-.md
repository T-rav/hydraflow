---
id: 2591
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.959770+00:00
status: active
corroborations: 1
supersedes: 2410
---

# Add pre-commit steps after STAGED_ARCH assignment, never inside

`tests/architecture/test_arch_check_trigger_coverage.py` regex-anchors on the `STAGED_ARCH=$(...)` assignment in `.githooks/pre-commit`. New validation steps that depend on the staged-arch detection must be inserted **after** the assignment block, never modified into it.

Example: `make arch-validate` goes inside the `if [ -n "$STAGED_ARCH" ]` body, after `STAGED_ARCH` is already computed.

**Why:** Editing the assignment itself breaks the trigger-coverage test regex and silently changes what files trigger arch checks.
