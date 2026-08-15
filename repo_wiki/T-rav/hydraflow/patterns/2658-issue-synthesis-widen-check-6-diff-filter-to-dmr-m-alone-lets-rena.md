---
id: 2658
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T08:32:49.042061+00:00
status: superseded
corroborations: 1
supersedes: 2535
superseded_by: 2781
---

# Widen check #6 --diff-filter to DMR; M alone lets renames flip verdicts

Set `--diff-filter=DMR` (delete/modify/rename) for check #6 in `scripts/check_console_conformance.py`. Exclude `A` — new records are legal under ARCH-0001.

Example: with `--diff-filter=M` only, a branch that renames a merged record and rewrites its verdict scores as `R`, slipping past the filter and flipping the decision undetected.

**Why:** Git scores rename+rewrite as `R`, so an `M`-only filter is a contract-bypass loophole for ledger immutability.
