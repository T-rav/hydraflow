---
id: 0327
topic: architecture
source_issue: 11146
source_phase: plan
created_at: 2026-08-14T15:08:46.027506+00:00
status: active
corroborations: 1
---

# FakeGitHub mirrors stay literal and get allowlisted

`FakeGitHub` has no config, so its `find_label_drift` mirror in test code cannot consume `HydraFlowConfig.hitl_queue_label`. Leave the literal in the mirror and add it to the AST ratchet allowlist with a comment noting the divergence.

- Do not attempt to thread config into `FakeGitHub`.
- The allowlist entry is intentional scope, not a filesystem mirror.

**Why:** Forcing config into test fakes couples test infrastructure to production config lifecycle; allowlisting with a documented divergence keeps the ratchet honest without that coupling.
