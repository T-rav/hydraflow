---
id: 2067
topic: patterns
source_issue: 11170
source_phase: plan
created_at: 2026-08-14T20:23:54.672687+00:00
status: superseded
corroborations: 1
superseded_by: 2180
---

# Widen check #6 --diff-filter to DMR; M alone lets renames flip verdicts

Set `--diff-filter=DMR` (delete/modify/rename) for check #6 in `scripts/check_console_conformance.py`. Exclude `A` — new records are legal under ARCH-0001.

Example: with `--diff-filter=M` only, a branch that renames a merged record and rewrites its verdict scores as `R`, slipping past the filter and flipping the decision undetected.

**Why:** Git scores rename+rewrite as `R`, so an `M`-only filter is a contract-bypass loophole for ledger immutability.
