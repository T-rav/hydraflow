---
id: 0252
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.230151+00:00
status: active
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
---

# Memory contradiction resolution: provenance wins over recency

When two memory items contradict, human-sourced wins over agent-sourced regardless of timestamp; among equal provenance, newer wins.

Example: A human-written learning from 2024 beats an agent-written one from 2025.

**Why:** Agent-sourced items can encode hallucinations; provenance-first resolution ensures human corrections are never overwritten by automated entries.
