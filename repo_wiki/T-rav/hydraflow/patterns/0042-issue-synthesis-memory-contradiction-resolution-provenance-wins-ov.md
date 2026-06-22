---
id: 0042
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.319935+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Memory contradiction resolution: provenance wins over recency

When two memory items contradict, human-sourced wins over agent-sourced regardless of timestamp; among equal provenance, newer wins.

Example: a human-written learning from 2024 beats an agent-written one from 2025.

**Why:** Agent-sourced items can encode hallucinations; provenance-first resolution ensures human corrections are never overwritten by automated entries.
