---
id: 2215
topic: testing
source_issue: 10906
source_phase: plan
created_at: 2026-07-31T12:53:04.027129+00:00
status: active
corroborations: 1
---

# String monkeypatch targets are invisible to AST import guards

When flipping `from src import server` to `import server`, also update paired string targets like `monkeypatch.setattr("src.server.load_runtime_config")` and `"src.server.setup_logging"` (test_telemetry_otel_init.py ~lines 113-114). The AST guard sees only import statements, not dotted-string attribute paths.

**Why:** A missed string flip leaves the test patching a module nobody imports — the assertion becomes a silent no-op that still passes, hiding real regressions.
