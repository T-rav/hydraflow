---
id: 2792
topic: patterns
source_issue: 11238
source_phase: plan
created_at: 2026-08-15T09:37:15.548486+00:00
status: active
corroborations: 1
---

# Provider classification resolves role dial > repo_provider > claude

In `_loop_providers` (`src/orchestrator.py`), classify each work loop by checking in order: the loop's role dial, then `repo_provider`, then `"claude"`.

Example:
- `implement` with `implement_provider="zai"` → "zai" even if `repo_provider` unset
- `implement` with `implement_provider="claude"` → "claude" even when `repo_provider="zai"`
- Maintenance loops: unchanged classification

**Why:** A cap raised by one provider's seam must not pause loops routed to a different provider.
