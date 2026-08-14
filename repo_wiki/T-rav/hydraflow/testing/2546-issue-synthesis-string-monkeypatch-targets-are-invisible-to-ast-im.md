---
id: 2546
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.258947+00:00
status: active
corroborations: 1
supersedes: 2357
---

# String monkeypatch targets are invisible to AST import guards

When flipping `from src import server` to `import server`, also update paired string targets like `monkeypatch.setattr("src.server.load_runtime_config")` and `"src.server.setup_logging"` (`test_telemetry_otel_init.py` ~lines 113-114). The AST guard sees only import statements, not dotted-string attribute paths.

**Why:** A missed string flip leaves the test patching a module nobody imports — the assertion becomes a silent no-op that still passes, hiding real regressions.
