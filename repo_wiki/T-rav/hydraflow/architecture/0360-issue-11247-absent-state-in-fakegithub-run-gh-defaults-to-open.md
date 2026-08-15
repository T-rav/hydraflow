---
id: 0360
topic: architecture
source_issue: 11247
source_phase: plan
created_at: 2026-08-15T20:03:13.665813+00:00
status: active
corroborations: 1
---

# Absent --state in FakeGitHub._run_gh defaults to open, not all

For both `gh issue list` and `gh pr list`, omitting `--state` returns only open rows, mirroring the real `gh` CLI.

- A regression here silently empties the result set for closed/merged data.
- Changing the pr-list no-`--state` default from "not merged" to "not merged and not closed" risks `service_registry.py:230`, the only port-level `gh pr list` caller — verify before assuming safety.

**Why:** Defaulting to `all` would surface closed/merged rows that today's callers do not expect.
