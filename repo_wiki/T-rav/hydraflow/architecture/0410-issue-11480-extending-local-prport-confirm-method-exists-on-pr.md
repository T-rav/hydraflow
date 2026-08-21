---
id: 0410
topic: architecture
source_issue: 11480
source_phase: plan
created_at: 2026-08-20T06:54:25.786722+00:00
status: active
corroborations: 1
---

# Extending local _PRPort: confirm method exists on PRPort/PRManager/FakeGitHub

Before adding a method to a terminal module's local `_PRPort` Protocol, confirm it already exists on the global `PRPort` (`ports.py`), `PRManager`, and `FakeGitHub`.

Example: `list_branch_commits` was added to `_PRPort` in `decompose_terminal.py` because `PRPort` (`ports.py:418`), `PRManager` (`:604`), and `FakeGitHub` (`:1609`) already implement it — no caller changes needed.

**Why:** Callers in `auto_agent_preflight_loop.py`, `decision.py`, and `giveup_self_solve.py` all pass full ports; adding a Protocol method not backed by every implementation breaks runtime dispatch.
