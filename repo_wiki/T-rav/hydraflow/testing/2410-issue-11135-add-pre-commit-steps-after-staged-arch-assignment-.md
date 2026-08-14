---
id: 2410
topic: testing
source_issue: 11135
source_phase: plan
created_at: 2026-08-14T13:08:51.035568+00:00
status: superseded
corroborations: 1
superseded_by: 2591
---

# Add pre-commit steps after STAGED_ARCH assignment, never inside it

`tests/architecture/test_arch_check_trigger_coverage.py` regex-anchors on the `STAGED_ARCH=$(...)` assignment in `.githooks/pre-commit`. New validation steps that depend on the staged-arch detection must be inserted **after** the assignment block, never modified into it.

- Example: `make arch-validate` goes inside the `if [ -n "$STAGED_ARCH" ]` body, after `STAGED_ARCH` is already computed.

**Why:** Editing the assignment itself breaks the trigger-coverage test regex and silently changes what files trigger arch checks.
