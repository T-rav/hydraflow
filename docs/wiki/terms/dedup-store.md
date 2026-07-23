---
id: "01KY4QF8BE4Y5782543MPQNDQ0"
name: "DedupStore"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/dedup_store.py:DedupStore"
aliases: ["dedup tracking set", "dedup set store"]
related: [{"kind": "depends_on", "target": "01KTX0X7RK9NPDNYRPZ58BVT9J"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B6"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9C3"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B4"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9C1"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B9"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B8"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B5"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B2"}, {"kind": "depends_on", "target": "01KSY46G6QFVCRC5FE26Q5FKJY"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A5"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A4"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K6"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A9"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A7"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A1"}, {"kind": "depends_on", "target": "01KQZR9QW4RJ5Q7TB2220V3JZN"}, {"kind": "depends_on", "target": "01KT3WKPR5MN8QJ14CF77W6K6"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-22T10:55:46.542376+00:00"
updated_at: "2026-07-22T10:55:46.542379+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-22T10:55:46.542330+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 19
---

## Definition

DedupStore is a file-backed dedup tracking set, persisted as a sorted JSON list via atomic writes. It is the canonical shared-kernel mechanism the caretaker fleet uses to avoid re-filing or re-processing the same finding, case, or issue across ticks: a loop hashes or keys a piece of work, checks the DedupStore to see whether that key has already been handled, and records it once acted upon. It underlies idempotency for nearly every autonomous caretaker loop (ADR review, contract refresh, corpus learning, dependabot merge, diagnostics, entry evidence, fake-coverage audit, flake tracking, live corpus replay, merge-state watching, RC budget, sentry ingestion, skill-prompt eval, term proposal, wiki-rot detection).

## Invariants

- get() returns an empty set rather than raising when the backing file is missing, unreadable, or contains malformed JSON
- add/discard/set_all persist via atomic_write so a crash mid-write cannot corrupt the stored set
- discard() is a silent no-op (no write) when the value is not present
