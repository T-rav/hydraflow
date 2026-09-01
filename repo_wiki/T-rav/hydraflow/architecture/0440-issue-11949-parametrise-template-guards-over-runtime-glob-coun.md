---
id: 0440
topic: architecture
source_issue: 11949
source_phase: plan
created_at: 2026-09-01T09:56:43.594653+00:00
status: active
corroborations: 1
---

# Parametrise template guards over runtime glob + counter-pin

In `tests/test_claude_md_structure.py`, parametrise guards over a runtime glob of `.claude/commands/*.md` and `.claude/agents/*.md` per `docs/standards/parametrised_guards/` — never a hardcoded file list. Pair each predicate with a counter-pin (e.g. a synthetic `pr_body.md` target) that the check rejects, proving the guard isn't vacuous. **Why:** hardcoded lists drift as templates are added; without a counter-pin, a too-loose predicate passes silently and protects nothing.
