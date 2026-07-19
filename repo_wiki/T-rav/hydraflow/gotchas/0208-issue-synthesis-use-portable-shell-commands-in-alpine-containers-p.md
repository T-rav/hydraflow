---
id: 0208
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.160069+00:00
status: superseded
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
superseded_by: 0214
---

# Use portable shell commands in Alpine containers — Python is absent

In Alpine-based Docker containers, avoid Python and non-standard utilities. Use portable POSIX commands for memory/CPU operations.

Example: `dd if=/dev/zero bs=1M count=32 of=/dev/null` instead of a Python `bytearray` allocation.

**Why:** Alpine's minimal tooling excludes Python and many GNU utilities; scripts that rely on them fail with `command not found` in constrained CI environments.
