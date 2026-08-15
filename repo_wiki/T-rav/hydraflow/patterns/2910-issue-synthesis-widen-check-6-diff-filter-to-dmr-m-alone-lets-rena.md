---
id: 2910
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:52.445251+00:00
status: active
corroborations: 1
supersedes: 2781
---

# Widen check #6 --diff-filter to DMR; M alone lets renames flip verdicts

Set `--diff-filter=DMR` (delete/modify/rename) for check #6 in `scripts/check_console_conformance.py`. Exclude `A` — new records are legal under ARCH-0001.

Example: with `--diff-filter=M` only, a branch that renames a merged record and rewrites its verdict scores as `R`, slipping past the filter and flipping the decision undetected. See also: [patterns] — Immutability check needs merge-base range; [patterns] — Pass -M explicitly in check #6.

**Why:** Git scores rename+rewrite as `R`, so an `M`-only filter is a contract-bypass loophole for ledger immutability.
