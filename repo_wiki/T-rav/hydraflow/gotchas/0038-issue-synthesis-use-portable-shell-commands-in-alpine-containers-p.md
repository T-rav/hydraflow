---
id: 0038
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.697862+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Use portable shell commands in Alpine containers — Python is absent

In Alpine-based Docker containers, avoid Python and non-standard utilities. Use portable POSIX commands for memory/CPU operations.

Example: `dd if=/dev/zero bs=1M count=32 of=/dev/null` or `head -c 33554432 /dev/zero > /dev/null` instead of a Python `bytearray` allocation.

**Why:** Alpine's minimal tooling excludes Python and many GNU utilities; scripts that rely on them fail with `command not found` in constrained CI environments.
