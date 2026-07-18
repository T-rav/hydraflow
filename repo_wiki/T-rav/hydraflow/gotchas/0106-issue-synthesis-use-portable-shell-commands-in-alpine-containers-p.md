---
id: 0106
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:33:11.849546+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Use portable shell commands in Alpine containers — Python is absent

In Alpine-based Docker containers, avoid Python and non-standard utilities. Use portable POSIX commands for memory/CPU operations.

Example: `dd if=/dev/zero bs=1M count=32 of=/dev/null` or `head -c 33554432 /dev/zero > /dev/null` instead of a Python `bytearray` allocation.

**Why:** Alpine's minimal tooling excludes Python and many GNU utilities; scripts that rely on them fail with `command not found` in constrained CI environments.
