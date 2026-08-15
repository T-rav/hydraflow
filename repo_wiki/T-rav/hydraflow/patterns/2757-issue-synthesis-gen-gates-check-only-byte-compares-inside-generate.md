---
id: 2757
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T10:07:02.030288+00:00
status: active
corroborations: 1
supersedes: 2634
---

# gen-gates-check only byte-compares inside generated markers

Hand-written prose outside `<!-- generated:gates -->` markers in `docs/standards/branch_protection/README.md` is invisible to `make gen-gates-check` — `gen_gates._readme_with_block` splices only the span between markers, so stale claims there drift permanently undetected.

Example: A README can say "2 required checks" two lines below a generated table showing 3, and `gen-gates-check` stays green. Add `validate_prose_counts` in `scripts/gates/validate.py` wired into the `violations` list in `scripts/gen_gates.py:main()`.

**Why:** Without a dedicated prose-count predicate, the generated-block check creates a false green on exactly the sentences operators read first.
