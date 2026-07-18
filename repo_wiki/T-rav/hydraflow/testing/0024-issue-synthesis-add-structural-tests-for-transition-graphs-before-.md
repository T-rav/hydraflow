---
id: 0024
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.410376+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Add structural tests for transition graphs before property-based tests

Before running property-based tests on a transition graph, add structural tests: every target is a valid stage, every stage has a transition entry, no dangling references exist.

**Why:** Property-based tests discover transition paths but silently skip unreachable states caused by structural gaps in the graph definition.
