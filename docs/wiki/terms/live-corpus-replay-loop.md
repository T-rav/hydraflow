---
id: "01KSY46G6QFVCRC5FE26Q5FKJY"
name: "LiveCorpusReplayLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/live_corpus_replay_loop.py:LiveCorpusReplayLoop"
aliases: ["live corpus replay loop", "shadow corpus replay", "shadow drift replay"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K4"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-31T04:20:00.000000+00:00"
updated_at: "2026-06-12T04:17:13.434460+00:00"
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
