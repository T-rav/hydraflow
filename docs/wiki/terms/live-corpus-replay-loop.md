---
id: "01KSY46G6QFVCRC5FE26Q5FKJY"
name: "LiveCorpusReplayLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/live_corpus_replay_loop.py:LiveCorpusReplayLoop"
aliases: ["live corpus replay loop", "shadow corpus replay", "shadow drift replay"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-31T04:20:00.000000+00:00"
updated_at: "2026-05-31T04:20:00.000000+00:00"
---

## Definition

Trust-fleet loop that replays live shadow-corpus samples against registered
fake-adapter or shape validators. `LiveCorpusReplayLoop` files
`hydraflow-find` / `shadow-drift` issues when live adapter output diverges
from the current fake or schema contract, and escalates to HITL only after the
configured drift retry budget is exhausted.

## Invariants

- Empty shadow corpus is an idle tick, not an error.
- Drift issues are auto-agent routed before any human escalation.
- Dispatcher registration is keyed by `(adapter, command)` so cassette
  retirement can prove a live replay path covers the same shape.
