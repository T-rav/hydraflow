---
id: 2357
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.122237+00:00
status: superseded
corroborations: 1
supersedes: 2215
superseded_by: 2546
---

# String monkeypatch targets are invisible to AST import guards

When flipping `from src import server` to `import server`, also update paired string targets like `monkeypatch.setattr("src.server.load_runtime_config")` and `"src.server.setup_logging"` (`test_telemetry_otel_init.py` ~lines 113-114). The AST guard sees only import statements, not dotted-string attribute paths.

**Why:** A missed string flip leaves the test patching a module nobody imports — the assertion becomes a silent no-op that still passes, hiding real regressions.
