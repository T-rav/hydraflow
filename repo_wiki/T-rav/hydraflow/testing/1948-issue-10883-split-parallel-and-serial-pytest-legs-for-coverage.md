---
id: 1948
topic: testing
source_issue: 10883
source_phase: plan
created_at: 2026-07-31T07:40:16.907009+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Split parallel and serial pytest legs for coverage accumulation

Run `pytest` in two legs for coverage: parallel (`-n auto`) and serial.
- Leg 1: `--cov-fail-under=0 --cov-report=`
- Leg 2: `--cov-append`, `--cov-report=term-missing`, `--cov-fail-under=70`
Both legs must share a working directory.

**Why:** Without `--cov-append`, parallel workers drop data, lowering the reported total coverage while silently passing the 70% floor.
