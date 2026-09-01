---
id: 0439
topic: architecture
source_issue: 11949
source_phase: plan
created_at: 2026-09-01T09:56:43.594630+00:00
status: active
corroborations: 1
---

# Re-read --body-file in same gh pr create command

When invoking `gh pr create --body-file`, re-read the body file in the SAME Bash command and verify afterwards with `gh pr view --json body`. Templates under `.claude/commands/*.md` and `.claude/agents/*.md` already use `mktemp`-derived targets; preserve that pattern and keep `tests/test_claude_md_structure.py::TestCommandTemplateBodyFiles` green. **Why:** a stale or wrong body file silently produces a PR whose body doesn't match the branch diff — the failure mode behind PR #11572.
