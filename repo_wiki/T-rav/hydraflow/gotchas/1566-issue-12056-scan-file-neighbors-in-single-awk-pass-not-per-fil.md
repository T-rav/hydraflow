---
id: 1566
topic: gotchas
source_issue: 12056
source_phase: plan
created_at: 2026-09-02T21:56:47.139355+00:00
status: active
corroborations: 1
---

# Scan file neighbors in single awk pass, not per-file subshells, in PreToolUse hooks

For hooks that check multiple candidates (e.g., check-existing-infra): use `git ls-files -- <root>/*.py | awk '...'` once, not separate git/grep invocations per file. Single-pass awk on 2230 test files: ~30ms; per-file subshells: 36s.

Example: tokenize basenames, drop generic tokens (`test`, `py`, `loop`), report files sharing ≥2 distinct tokens in one awk pass.

**Why:** PreToolUse hooks block tool invocation; latency >5s destroys agent responsiveness. Pre-hooklet, the naive loop was a gotcha (#12056).
