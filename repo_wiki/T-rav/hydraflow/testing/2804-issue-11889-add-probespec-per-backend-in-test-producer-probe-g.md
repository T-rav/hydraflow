---
id: 2804
topic: testing
source_issue: 11889
source_phase: plan
created_at: 2026-09-01T10:19:26.410515+00:00
status: active
corroborations: 1
---

# Add ProbeSpec per backend in test_producer_probe_gate.py

When `TraceCollector` gains or corrects parsing for a backend's event fields, add a `ProbeSpec` in `tests/architecture/test_producer_probe_gate.py` over the corresponding fixture.

Example: a Pi `ProbeSpec` asserting `isError` is read, and a Codex `ProbeSpec` asserting `item.completed` `status` is parsed.

**Why:** A future upstream field rename then fails the architecture gate instead of silently zeroing `tool_errors`.
