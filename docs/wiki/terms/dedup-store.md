---
id: "01KTAMZH9S4EH0H06BJ11QNRZE"
name: "DedupStore"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/dedup_store.py:DedupStore"
aliases: ["dedup set", "deduplication store", "dedup store"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-05T01:04:53.561737+00:00"
updated_at: "2026-06-05T01:04:53.561739+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-05T01:04:53.561621+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 14
---

## Definition

A file-backed persistent dedup set that loops use to track which signals they have already acted on, preventing re-filing the same issue or PR on subsequent ticks. Identified by a set_name and a file_path; exposes get/add/set_all operations with atomic writes and fail-open read semantics. Used across the caretaker and builder loop fleet as the canonical idempotency contract for loop-generated GitHub activity — engineers name it explicitly in design conversations ('keyed DedupStore', 'dedup key clears on close') and wire it as a first-class constructor dependency in every loop that must not act twice on the same signal.

## Invariants

- Writes are atomic — a partial write never corrupts the stored set.
- Read errors return an empty set (fail-open); write errors are logged but not re-raised.
- Each loop instance owns one DedupStore per deduplication purpose, scoped by set_name.
