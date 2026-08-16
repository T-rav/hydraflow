---
id: 3048
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T20:34:48.556766+00:00
status: active
corroborations: 1
supersedes: 2921
---

# Provider classification resolves role dial > repo_provider > claude

In `_loop_providers` (`src/orchestrator.py`), classify each work loop by checking in order: the loop's role dial, then `repo_provider`, then `"claude"`.

Example: `implement` with `implement_provider="zai"` → "zai" even if `repo_provider` unset; `implement` with `implement_provider="claude"` → "claude" even when `repo_provider="zai"`; maintenance loops: unchanged classification.

**Why:** A cap raised by one provider's seam must not pause loops routed to a different provider.
