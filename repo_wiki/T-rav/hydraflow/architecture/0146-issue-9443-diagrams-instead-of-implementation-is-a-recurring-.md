---
id: 0146
topic: architecture
source_issue: 9443
source_phase: review
created_at: 2026-06-12T14:42:30.290592+00:00
status: active
corroborations: 1
---

# Diagrams-instead-of-implementation is a recurring agent scope-creep pattern

When an agent produces architecture diagrams that describe the desired post-fix state without delivering the actual code change, all plan deliverables are absent.

Detection: after any agent run, grep for expected output file paths before reading any artifacts:
```bash
git diff --stat HEAD~1 | grep -E 'src/|tests/'
```
If only `docs/` paths appear with no `src/` or `tests/` changes, the agent did documentation instead of implementation.

**Why:** Diagrams prove understanding, not delivery — an agent can correctly model the fix domain while producing zero functional code, and the diff looks active.
