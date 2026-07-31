---
id: 0269
topic: architecture
source_issue: 10820
source_phase: plan
created_at: 2026-07-31T00:58:39.724651+00:00
status: active
corroborations: 1
---

# Architecture test enforces loop classification coverage + no-I/O

`tests/architecture/test_loop_classification_coverage.py` does double duty: (1) every loop from `arch.extractors.loops` must have a row in `docs/arch/loop_signal_classification.yml`, and (2) `src/stillness/` must not import `subprocess`/`httpx`/`requests`. A classification row missing `signal_source` fails to load, naming the offending field.

**Why:** Prevents silent gaps where a new loop has no classification row and prevents I/O from leaking into pure analysis modules.
