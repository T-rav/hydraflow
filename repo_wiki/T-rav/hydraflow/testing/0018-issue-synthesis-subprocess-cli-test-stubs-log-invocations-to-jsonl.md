---
id: 0018
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.409621+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Subprocess CLI test stubs: log invocations to JSONL

Replace real CLI dependencies in tests with a small Python script that accepts the same arguments, writes each invocation to a JSONL file, and exits 0. Assert on the JSONL contents after the test action.

**Why:** This avoids launching real processes while giving exact, verifiable records of what arguments were passed to the fake CLI.
