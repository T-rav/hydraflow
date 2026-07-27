---
id: 1166
topic: gotchas
source_issue: 10734
source_phase: plan
created_at: 2026-07-27T19:38:38.658615+00:00
status: active
corroborations: 1
---

# Regression tests use real subprocess git, not mocked _run_git

Rule: Boot-correctness regression tests (e.g. `tests/regressions/test_issue_10734.py`) build throwaway origin + workspace clones via real subprocess git, then run the actual probe against fake status payloads. Follows `test_factory_isolated_stale_boot_10408.py` precedent.

- Avoid the shell-block-extractor truncation gotcha: match the assignment line directly, not by slicing a contiguous block.

**Why:** Mocking `_run_git` hides real git edge cases (fetch failures, detached HEAD, missing refs) that the kernel must handle deterministically.
