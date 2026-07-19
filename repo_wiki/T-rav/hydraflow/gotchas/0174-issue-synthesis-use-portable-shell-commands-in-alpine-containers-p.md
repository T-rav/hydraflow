---
id: 0174
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.955973+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# Use portable shell commands in Alpine containers — Python is absent

In Alpine-based Docker containers, avoid Python and non-standard utilities. Use portable POSIX commands for memory/CPU operations.

Example: `dd if=/dev/zero bs=1M count=32 of=/dev/null` instead of a Python `bytearray` allocation.

**Why:** Alpine's minimal tooling excludes Python and many GNU utilities; scripts that rely on them fail with `command not found` in constrained CI environments.
