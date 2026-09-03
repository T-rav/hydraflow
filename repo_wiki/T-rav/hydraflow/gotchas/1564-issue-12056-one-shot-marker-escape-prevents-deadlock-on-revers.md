---
id: 1564
topic: gotchas
source_issue: 12056
source_phase: plan
created_at: 2026-09-02T21:56:47.139314+00:00
status: active
corroborations: 1
---

# One-shot marker escape prevents deadlock on reversible PreToolUse hooks

When a PreToolUse hook refuses with exit 2, use a marker file under `HF_HOOK_MARKER_DIR` (keyed by path MD5) to allow re-issue of the same call without re-triggering the check. This prevents infinite refusal loops while preserving the guard for new paths.

Example: hook refuses new file → agent re-issues Write with same path → hook detects marker → exits 0 and allows.

**Why:** PreToolUse hooks block tool calls; without an escape valve, a legitimate new file that requires guidance costs unbounded prompt cycles (see check-existing-infra guard, #12056).
