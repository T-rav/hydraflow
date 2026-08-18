---
id: 0405
topic: architecture
source_issue: 11425
source_phase: plan
created_at: 2026-08-18T04:29:33.971219+00:00
status: active
corroborations: 1
---

# Don't import _-prefixed fake/runner classes across modules

Port methods are public by construction; `_`-prefixed fake/runner classes must not be imported across modules.
- Resolve nested runners off a live `FakeLLM()` instance (as `tests/regressions/test_issue_11420.py` does) rather than importing `_TriageRunner` etc.
- The conformance check exercises both the fully-positional and fully-keyword call shapes of `TriageRunner`/`PlannerRunner`/`AgentRunner`/`ReviewRunner`.
**Why:** Cross-module imports of `_`-prefixed names bypass the Port boundary the fakes exist to enforce; resolving off a live instance keeps the call shapes under the conformance guard.
