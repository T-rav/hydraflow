# Per-change artifact chain

One directory per change: `issue-<N>/`, holding the artifacts that change
was built from. Declared in [`charter.yaml`](../../charter.yaml) under
`artifacts.chain`, decided by
[ADR-0149](../adr/0149-the-per-change-artifact-chain.md).

| File | What it is | Written when |
|---|---|---|
| `intent.md` | The issue body, snapshotted at plan time | plan |
| `criteria.md` | Acceptance criteria drafted from the plan **before any code existed**, plus the SpecJudge verdict | plan |
| `plan.md` | The implementation plan the agent was given | plan |
| `evidence.md` | Merge receipt — approver identity and role, change class, CH-1 chain position | merge |

## Nothing here is hand-edited

These files are written by the harness
([`src/change_chain_writer.py`](../../src/change_chain_writer.py)) and by
nothing else. They are materialised into the issue worktree and committed
**before** the implementing agent starts, so the agent inherits them as
history rather than authoring the files the merge gate later reads.

Their digests are anchored at plan time on the append-only, hash-chained
`change_chain` stream (CH-1), which lives outside any worktree. The gate
([`src/change_chain_gate.py`](../../src/change_chain_gate.py)) re-derives
each digest from the committed file and compares. Editing a file here
without editing the stream — which is not reachable from a worktree —
produces a `chain-digest-mismatch` finding.

If you are an agent working in this repo: do not create, edit or regenerate
anything under this directory. `tests/architecture/test_change_chain_no_agent_write_path.py`
sweeps every prompt in the repo to keep that instruction from appearing.

## Retention

Live change directories stay flat here. Each quarter folds into
`archive/YYYY-Qn/` (ADR-0149 ruling 2) — at roughly 1,700 merged PRs per
four months, keeping every directory flat reaches ~5,000 a year and this
becomes the largest tree in the repo. A move is not a delete, so
`git log --follow` still reaches an archived change's intent and plan.

**Never reference a change directory by path.** Compaction rewrites paths.
Readers resolve through `change_chain.resolve_chain_dir`, which searches
live then archive; `evidence.md` cross-references records by id and digest,
never by a `docs/changes/...` path.
