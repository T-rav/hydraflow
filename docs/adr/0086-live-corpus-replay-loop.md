# ADR-0086 — LiveCorpusReplayLoop: Shadow-Corpus Drift Detection

**Status:** Proposed
**Date:** 2026-05-31

## Context

ADR-0047 established fake-adapter contract testing with curated cassettes. That
protects known cases, but it does not continuously compare fresh live command
shapes against fake-adapter behavior. The shadow corpus records live adapter
outputs so the trust fleet can detect drift before stale fakes make MockWorld
scenarios falsely green.

## Decision

`LiveCorpusReplayLoop` (`src/live_corpus_replay_loop.py`) reads the shadow
corpus, dispatches each supported `(adapter, command)` sample through a
registered fake/shape validator, and files `hydraflow-find` issues when live
outputs diverge from the expected fake or schema behavior.

The loop is intentionally automatic-first. A drift issue is routed as
`hydraflow-find` and `shadow-drift`; HITL escalation is reserved for drift that
survives the configured retry budget.

## Consequences

- MockWorld fake fidelity has a live-data feedback path instead of relying only
  on static cassettes.
- The fake-coverage auditor can retire baseline cassettes once an equivalent
  live replay dispatcher covers the same shape.
- Empty-corpus operation is valid and should be observable as an idle worker
  tick, not a failure.

## Related

- [ADR-0047](0047-fake-adapter-contract-testing-cassettes.md) — fake-adapter contract cassettes
- [ADR-0045](0045-trust-architecture-hardening.md) — trust-fleet hardening
- `src/live_corpus_replay_loop.py:LiveCorpusReplayLoop`
- `src/contracts/shadow.py:ShadowCorpus`
