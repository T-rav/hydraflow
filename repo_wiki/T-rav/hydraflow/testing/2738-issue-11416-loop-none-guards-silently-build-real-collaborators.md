---
id: 2738
topic: testing
source_issue: 11416
source_phase: plan
created_at: 2026-08-18T03:21:19.601663+00:00
status: stale
corroborations: 1
stale_reason: source issue #11416 closed
---

# Loop None-guards silently build real collaborators, not fakes

Rule: A loop constructor parameter that defaults to `None` and builds a real implementation when `None` (e.g., `_CLIRefineLLM`, `EscapeAutoDiagnoser`) is NOT optional for the catalog builder — the builder MUST seed it from `ports`.

Example:
- `_build_skill_prompt_eval` without `refine_llm` → `run_lightweight_agent` → real `claude` subprocess inside a scenario.
- `_build_diagnostic` without `workspaces` → worktree branches silently dead, fall back to `repo_root`.
- `_build_escape_ledger` without `auto_diagnoser` → real `EscapeAutoDiagnoser` doing live git reads.

**Why:** The `is None`-guard makes omissions invisible — tests pass but hit real external systems or skip functionality silently.
