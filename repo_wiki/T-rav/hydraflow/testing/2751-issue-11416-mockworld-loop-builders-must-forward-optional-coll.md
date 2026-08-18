---
id: 2751
topic: testing
source_issue: 11416
source_phase: review
created_at: 2026-08-18T04:59:41.421013+00:00
status: stale
corroborations: 1
stale_reason: source issue #11416 closed
---

# MockWorld loop builders must forward optional collaborators from ports

Every `_build_*` function in `loop_registrations.py` must forward all optional collaborators a loop accepts, or the loop lazily substitutes a real side-effecting implementation. Known live gaps:
- `_build_skill_prompt_eval` omits `refine_llm` → `_CLIRefineLLM` spawns real `claude` (`src/skill_prompt_eval_loop.py:1055`)
- `_build_escape_ledger` omits `auto_diagnoser` → real `EscapeAutoDiagnoser` does git reads (`src/escape_ledger_loop.py:717`)
- `_build_diagnostic`/`_build_pr_red_repair` omit `workspaces` → dead worktree paths
**Why:** Optional collaborators with `None` defaults silently fall back to real implementations, not fakes.
