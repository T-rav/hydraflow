# GitHub cassette corpus

This directory contains two kinds of cassettes:

**Machine-recorded** (`baseline_only: false`) — refreshed by
`ContractRefreshLoop` via `record_github_mutation` in
`src/contract_recording.py`. Each recording provisions fresh sandbox
resources, runs the mutation, writes the cassette, and tears down the
sandbox state (e.g. closing the scratch issue). Currently covers:
`close_issue.yaml`, `create_issue.yaml`, `merge_pr.yaml`.

**Hand-authored baselines** (`baseline_only: true`) — not refreshed by
`ContractRefreshLoop`. Identifiable by both:

- `recorder_sha: "00000000"` (historical convention)
- `baseline_only: true` in the YAML body (Phase 4 of #8786 — the machine-
  checkable retirement marker)

All remaining cassettes (e.g. `add_labels.yaml`, `post_comment.yaml`,
`pr_create.yaml`, etc.) are hand-authored baselines.

## Retirement plan (Phase 4 of #8786)

A baseline cassette is **redundant** (and eligible for removal) once the
same `(adapter, command, args)` shape is covered by a `LiveCorpusReplayLoop`
dispatcher in `src/live_corpus_replay_loop.py`'s registry. At that point:

- The shadow corpus captures the *real* gh output continuously.
- The Pydantic shape models in `src/contracts/shapes.py` catch shape drift
  at the call site.
- The replay loop diffs sample vs fake output every 15 minutes.

The hand-authored baseline becomes a duplicate of stronger signals.

A future `FakeCoverageAuditorLoop` check (filed as follow-up) will warn
when `baseline_only=true` AND a live dispatcher exists for the same shape
— that's the retirement signal. Removal then happens in a one-PR cleanup.

Until then, baselines stay because they're the only contract test for the
respective FakeGitHub methods.

## Why some cassettes are still hand-authored

Cassettes for `gh label create`, `gh issue edit --add-label`, and other
operations not yet covered by `record_github_mutation` remain hand-authored
because extending the recorder to cover them safely is tracked separately
(#8693, #8699). The sandbox setup/teardown contract in
`record_github_mutation` is the pattern to follow when adding new
machine-recorded operations.

## How baselines stay accurate

Two safeguards keep the hand-authored baselines from drifting silently:

1. **Replay gate**: every cassette must be replayable through `FakeGitHub`
   via `_invoke_fake_github` in
   `tests/trust/contracts/test_fake_github_contract.py`. A fake
   implementation change that diverges from the cassette breaks the test
   in CI — the cassette is the contract.
2. **FakeCoverageAuditorLoop** (ADR-0045): scans `FakeGitHub` for public
   methods without a cassette and files `fake-coverage-gap` issues.
   Adding a method without a baseline is detected, not silent.

## When to add a cassette here

- A new `FakeGitHub` method that emulates a real `gh` call is added.
- A real `gh` call shape is added to production code paths via
  `subprocess_util.run_subprocess` and a corresponding fake method exists
  (or is being added in the same PR).

Always add the dispatcher entry in `_invoke_fake_github` in the same PR
so the replay test exercises the new cassette end-to-end.

## When NOT to add a cassette here

- A `gh` call shape that isn't backed by a fake method — there's nothing
  to contract-test. Add the fake method first.
- An adapter-internal helper (`_run_gh`, `_maybe_rate_limit`) — the
  contract is at the public method level, not the helper.

## Current corpus

The committed corpus is auto-discovered by
`tests/trust/contracts/test_fake_github_contract.py` (parametrized over
`list_cassettes(_CASSETTE_DIR)`). To enumerate it locally:

```bash
ls tests/trust/contracts/cassettes/github/*.yaml
```

Each cassette must have a matching dispatcher entry in
`_invoke_fake_github`. The reverse is also true — a dispatcher entry
without a cassette (e.g. the historical `merge_pr` orphan) is dead code
and a fake-coverage signal.

