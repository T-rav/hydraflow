---
id: 0270
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.486582+00:00
status: superseded
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
superseded_by: 0295
---

# Add structural tests for transition graphs before property-based tests

Before running property-based tests on a transition graph, add structural tests: every target is a valid stage, every stage has a transition entry, no dangling references exist.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`

**Why:** Property-based tests discover transition paths but silently skip unreachable states caused by structural gaps in the graph definition.
