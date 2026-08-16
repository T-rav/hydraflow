---
id: 1445
topic: gotchas
source_issue: 11328
source_phase: plan
created_at: 2026-08-16T09:56:55.839276+00:00
status: active
corroborations: 1
---

# Commit non-command phases first; .claude/commands edits hit permission gate

When a plan touches `.claude/commands/hf.issue.md`, commit all other phases first. If the command-file edit is refused, ship the rest and file a follow-up — do not retry into the attempt cap.

- PR #11324 was blocked by the same permission gate.
- P1–P3 (engine + tests) are independently shippable without the command-file change.

**Why:** Retrying a refused command-file edit burns the attempt budget without unblocking; shipping the engine first preserves value and unblocks the follow-up.
