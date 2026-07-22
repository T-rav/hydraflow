---
id: 0276
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.032849+00:00
status: active
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
---

# Use portable shell commands in Alpine containers — Python is absent

In Alpine-based Docker containers, avoid Python and non-standard utilities. Use portable POSIX commands for memory/CPU operations.

Example: `dd if=/dev/zero bs=1M count=32 of=/dev/null` instead of a Python `bytearray` allocation.

**Why:** Alpine's minimal tooling excludes Python and many GNU utilities; scripts that rely on them fail with `command not found` in constrained CI environments.
