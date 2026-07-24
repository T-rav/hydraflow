---
id: 0177
topic: architecture
source_issue: 10434
source_phase: plan
created_at: 2026-07-24T10:19:32.942793+00:00
status: active
corroborations: 1
---

# adr_drift only skips drift for genuine :Symbol-qualified citations

`adr_drift._citation_drifts` flags a bare `src/foo.py` citation on *any* touch to that file, but a `src/foo.py:Symbol` citation only drifts when the diff evidence names that exact symbol. Use `:Symbol` tails (e.g. `src/base_background_loop.py:BaseBackgroundLoop._execute_cycle`) when an ADR governs one specific method/class rather than the whole module, per the pattern already used in ADR-0084, ADR-0093, ADR-0099, and ADR-0004.

**Why:** bare citations over-trigger drift on orthogonal changes to the same file (e.g. PR #10414's cadence-logic change tripping ADR-0055, which actually governs `@loop_span()` OTel decoration).
