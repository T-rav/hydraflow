---
id: 1228
topic: gotchas
source_issue: 10870
source_phase: plan
created_at: 2026-07-31T06:08:36.407884+00:00
status: active
corroborations: 1
---

# Test auto-agent templates via runtime glob, not hardcoded lists

Assert every `*.md` file under `prompts/auto_agent/` is covered by globbing the directory at runtime in `tests/test_auto_agent_prompt_templates.py`. Partition the two direct-family templates by referencing the public `PROMPT_TEMPLATE` constants exported by `src/pr_red_repair_loop.py` and `src/sandbox_failure_fixer_loop.py` rather than hardcoding filenames.

**Why:** Hardcoded filename lists silently miss newly added templates, allowing unknown `{field}` `KeyError` failures to slip into production.
