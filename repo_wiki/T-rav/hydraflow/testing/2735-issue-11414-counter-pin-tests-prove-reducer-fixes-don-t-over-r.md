---
id: 2735
topic: testing
source_issue: 11414
source_phase: plan
created_at: 2026-08-18T03:10:06.299887+00:00
status: active
corroborations: 1
---

# Counter-pin tests prove reducer fixes don't over-reach unchanged paths

Rule: When a fix narrows a mutation to a conditional branch (e.g., `...(changed && {...})` inside `SELECT_REPO`), add a counter-pin test asserting the unchanged case leaves prior state intact.

Example: Dispatch `SELECT_REPO` with the same repo slug and assert `pipelineSnapshotAt` is not nulled. Place alongside the invariant suite in `railResyncInvariant.test.jsx`.

**Why:** Without a counter-pin, a reviewer cannot distinguish "the fix is correctly scoped" from "the fix nukes the clock on every dispatch regardless of whether the repo actually changed."
